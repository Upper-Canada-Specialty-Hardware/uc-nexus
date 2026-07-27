"""Inventory reservations: the claim a request holds on stock between creation and the pull (#342).

Creating a shop-assembly or shipping-out request reserves what it needs, so

    available = on-hand - deficient - active reservations

and the creator is held to what is genuinely free at creation time. Approving the pull *consumes*
the source request's reservations and deducts FIFO in the same transaction; every other way a
request can die *releases* them. Both are the same DB operation - delete the request's rows - and
the two names exist because the two moments mean opposite things (`release_reservations` documents
the whole table).

Everything here aggregates with `func.sum`; there is no path that loads reservation rows to count
them in Python (CLAUDE.md perf rules).
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.orm import Session

from app.models.enums import ReservationSource
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.inventory_reservation import InventoryReservation as InventoryReservationModel

# The FK column each source discriminator writes to / filters on.
_SOURCE_COLUMN = {
    ReservationSource.SHOP_ASSEMBLY_REQUEST: InventoryReservationModel.shop_assembly_request_id,
    ReservationSource.SHIPPING_OUT_REQUEST: InventoryReservationModel.shipping_out_request_id,
}


def _combo_filter(combos: Iterable[tuple[str, str]] | None, category_col, code_col):
    """OR of (hardware_category, product_code) equality pairs, or None for "no filter"."""
    if combos is None:
        return None
    pairs = list(combos)
    if not pairs:
        # An explicit empty set means "nothing", not "everything".
        return category_col.is_(None) & category_col.is_not(None)
    return or_(*[and_(category_col == cat, code_col == code) for cat, code in pairs])


def get_reserved_quantities(
    session: Session,
    project_id: uuid.UUID,
    combos: Iterable[tuple[str, str]] | None = None,
    *,
    exclude_source: ReservationSource | None = None,
    exclude_request_id: uuid.UUID | None = None,
) -> dict[tuple[str, str], int]:
    """Active reserved quantity per (hardware_category, product_code) in one project.

    One grouped scalar aggregate - never a `len()` or a Python sum over loaded rows. `combos`
    narrows it to the combos a caller actually cares about (an empty iterable returns `{}`; `None`
    means every combo in the project).

    `exclude_source` / `exclude_request_id` are **self-coverage** (#342): when the warehouse
    approves request R's pull, R's own reservations are exactly what backs the deduction, so they
    must not be counted against R. Without the exclusion a fully-reserved request could never be
    approved - its own claim would read as competing demand. Every other caller leaves it unset and
    therefore sees the whole book of claims.
    """
    stmt = (
        select(
            InventoryReservationModel.hardware_category,
            InventoryReservationModel.product_code,
            func.sum(InventoryReservationModel.quantity),
        )
        .where(InventoryReservationModel.project_id == project_id)
        .group_by(
            InventoryReservationModel.hardware_category,
            InventoryReservationModel.product_code,
        )
    )
    combo_clause = _combo_filter(
        combos,
        InventoryReservationModel.hardware_category,
        InventoryReservationModel.product_code,
    )
    if combo_clause is not None:
        stmt = stmt.where(combo_clause)
    if exclude_source is not None and exclude_request_id is not None:
        # Exclude exactly one row set: the given request's own claims. It has to be written as a
        # negated conjunction, not as `column != id`, because that column is NULL on every row of the
        # *other* source - a shipping-out reservation has no `shop_assembly_request_id` - and
        # `NULL != <id>` is NULL, which SQL drops. Written the naive way this silently subtracted
        # every opposite-source claim in the project from the aggregate, so the cross-type guarantee
        # the reservation table exists for was void on the one path that matters (pull approval).
        stmt = stmt.where(
            not_(
                and_(
                    InventoryReservationModel.source == exclude_source,
                    _SOURCE_COLUMN[exclude_source] == exclude_request_id,
                )
            )
        )

    return {(cat, code): int(total or 0) for cat, code, total in session.execute(stmt).all()}


def get_reserved_total(session: Session, source: ReservationSource, request_id: uuid.UUID) -> int:
    """How much stock one request currently holds, summed across every combo. One scalar aggregate.

    The question this answers is "does this request hold a claim at all", which is not the same as
    "was this request created after #342": the backfill deliberately left the pre-existing in-flight
    population *unreserved and flagged* rather than inventing claims for it, and a re-upload or a
    cancelled-and-not-re-reservable pull can strip a claim from a live request too.
    """
    total = session.scalar(
        select(func.coalesce(func.sum(InventoryReservationModel.quantity), 0)).where(
            InventoryReservationModel.source == source,
            _SOURCE_COLUMN[source] == request_id,
        )
    )
    return int(total or 0)


def get_project_availability(session: Session, project_id: uuid.UUID) -> list[dict]:
    """Per-combo availability for one project, as the Start-a-Task wizard needs it: what is on hand,
    what of it is condemned, what other requests have claimed, and what is therefore left to claim.

    Two grouped scalar aggregates merged by combo key - one over `inventory_locations`, one over
    `inventory_reservations`. Reservation-only combos (stock fully claimed, or written off after the
    claim) are included with `on_hand = 0`, so a creator sees *why* a combo reads zero rather than
    finding it silently missing.

    `available` is floored at 0: an over-reservation (stock written off under a live claim) is a
    real state, and reporting it as a negative number would only invite arithmetic on it downstream.
    """
    inv_stmt = (
        select(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.sum(InventoryLocationModel.quantity),
            func.sum(InventoryLocationModel.deficient_quantity),
        )
        .where(InventoryLocationModel.project_id == project_id)
        .group_by(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
    )
    rows: dict[tuple[str, str], dict] = {}
    for cat, code, on_hand, deficient in session.execute(inv_stmt).all():
        rows[(cat, code)] = {
            "hardware_category": cat,
            "product_code": code,
            "on_hand_quantity": int(on_hand or 0),
            "deficient_quantity": int(deficient or 0),
            "reserved_quantity": 0,
        }

    for (cat, code), reserved in get_reserved_quantities(session, project_id).items():
        row = rows.get((cat, code))
        if row is None:
            row = {
                "hardware_category": cat,
                "product_code": code,
                "on_hand_quantity": 0,
                "deficient_quantity": 0,
                "reserved_quantity": 0,
            }
            rows[(cat, code)] = row
        row["reserved_quantity"] = reserved

    result = []
    for row in rows.values():
        row["available_quantity"] = max(
            0,
            row["on_hand_quantity"] - row["deficient_quantity"] - row["reserved_quantity"],
        )
        result.append(row)
    result.sort(key=lambda r: (r["hardware_category"], r["product_code"]))
    return result


def create_reservations(
    session: Session,
    project_id: uuid.UUID,
    source: ReservationSource,
    request_id: uuid.UUID,
    needs: Iterable[tuple[str, str, int]],
) -> list[InventoryReservationModel]:
    """Write one reservation row per (hardware_category, product_code) for a request just created.

    `needs` is aggregated by combo first, so a request that names the same product on five openings
    holds one row for the total rather than five rows that every availability sum then has to add
    back up. Zero/negative quantities are dropped (nothing to claim), which is also what keeps the
    `quantity >= 1` check constraint from being reachable by an empty opening.

    The caller must already have gated on availability in the same transaction - this function
    writes the claim, it does not decide whether the claim is allowed.
    """
    totals: dict[tuple[str, str], int] = {}
    for cat, code, qty in needs:
        if qty is None or qty <= 0:
            continue
        totals[(cat, code)] = totals.get((cat, code), 0) + qty

    created: list[InventoryReservationModel] = []
    for (cat, code), qty in sorted(totals.items()):
        row = InventoryReservationModel(
            id=uuid.uuid4(),
            project_id=project_id,
            hardware_category=cat,
            product_code=code,
            quantity=qty,
            source=source,
            shop_assembly_request_id=(request_id if source is ReservationSource.SHOP_ASSEMBLY_REQUEST else None),
            shipping_out_request_id=(request_id if source is ReservationSource.SHIPPING_OUT_REQUEST else None),
        )
        session.add(row)
        created.append(row)
    if created:
        session.flush()
    return created


def release_reservations(session: Session, source: ReservationSource, request_id: uuid.UUID) -> int:
    """Drop every reservation a request holds and return how many rows went. Idempotent.

    This is the single exit from the reservation table, and every path a request can leave the
    in-flight state on goes through it:

    | Path                                     | Effect                                            |
    | ---------------------------------------- | ------------------------------------------------- |
    | Reject (either request type)             | release - the request is dead, the claim dies too |
    | Reject after a reopen                    | release - same call, same result                  |
    | Reopen an accepted request (#325)        | **no release** - see below                        |
    | Pull approval (the reserved path)        | consume - the claim becomes the FIFO deduction    |
    | Pull approval that comes up short        | **no release** - the pull stays blocked, holding  |
    | Re-upload drops the request's openings    | release, by rebuilding from what survived         |
    | Re-upload leaves the request empty       | auto-reject, which releases                       |

    **Reopen deliberately does not release.** A reopen undoes the *accept*, not the *creation*: the
    request goes back to PENDING and is still a live claim on stock, exactly as it was between
    creation and the accept it is unwinding. Releasing here would let a second request grab the
    hardware while the first is still on the board waiting to be re-accepted - which is the
    accept-time shortfall this whole slice removes, reintroduced through the back door. Rejecting
    it afterwards is what finally releases, and that path is unchanged.

    Bulk DELETE in one statement (not a load + per-row delete). The ORM's default synchronisation
    evaluates the criteria against the identity map, so any of these rows the session had already
    loaded are expunged with it rather than left behind as phantoms.
    """
    result = session.execute(
        delete(InventoryReservationModel).where(
            InventoryReservationModel.source == source,
            _SOURCE_COLUMN[source] == request_id,
        )
    )
    session.flush()
    return int(result.rowcount or 0)
