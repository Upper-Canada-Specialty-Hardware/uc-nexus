"""Inventory reservations: the claim a request holds on stock between creation and the pull (#342).

Creating a shop-assembly or shipping-out request reserves what it needs, so

    available = on-hand - deficient - active reservations

and the creator is held to what is genuinely free at creation time. Confirming the pull's pick
*consumes* the source request's reservations and deducts the dictated rows in the same transaction
(#367 moved that moment from approval); every other way a request can die *releases* them.

Consumption is per combo and partial (`consume_reservations`), because a pick can be confirmed
short and the un-picked remainder is still owed. Release is whole-holder (`release_reservations`,
which documents the whole table), because a dead request is owed nothing.

Everything here aggregates with `func.sum`; there is no path that loads reservation rows to count
them in Python (CLAUDE.md perf rules).
"""

import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.orm import Session

from app.models.enums import ReservationSource
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.inventory_reservation import InventoryReservation as InventoryReservationModel

# The FK column each source discriminator writes to / filters on. A REPLACEMENT_PULL claim is held
# by the PR-REPL pull itself, because a deficiency has no request behind it (#342 follow-up).
_SOURCE_COLUMN = {
    ReservationSource.SHOP_ASSEMBLY_REQUEST: InventoryReservationModel.shop_assembly_request_id,
    ReservationSource.SHIPPING_OUT_REQUEST: InventoryReservationModel.shipping_out_request_id,
    ReservationSource.REPLACEMENT_PULL: InventoryReservationModel.pull_request_id,
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


def get_available_quantities(
    session: Session,
    project_id: uuid.UUID,
    combos: Iterable[tuple[str, str]],
    *,
    lock: bool = False,
) -> dict[tuple[str, str], int]:
    """Free stock per combo: `on-hand - deficient - every active reservation`, floored at 0.

    The same arithmetic `check_inventory_sufficiency` applies, exposed as a number rather than a
    pass/fail, because the replacement-reservation paths do not ask "does all of it fit" - they ask
    "how much of it can I claim right now" and take whatever that is. **No self-exclusion**: a
    reservation the caller already holds is stock it has already claimed, so counting it here is what
    stops a top-up from claiming the same units twice.

    `lock=True` takes `SELECT ... FOR UPDATE` on the inventory rows, so a mint that reads this number
    and writes a claim against it serialises with any concurrent one.
    """
    pairs = list(combos)
    if not pairs:
        return {}

    inv_stmt = select(InventoryLocationModel).where(
        InventoryLocationModel.project_id == project_id,
        _combo_filter(pairs, InventoryLocationModel.hardware_category, InventoryLocationModel.product_code),
    )
    if lock:
        inv_stmt = inv_stmt.order_by(InventoryLocationModel.id).with_for_update()
    on_hand: dict[tuple[str, str], int] = {}
    for il in session.scalars(inv_stmt).all():
        key = (il.hardware_category, il.product_code)
        on_hand[key] = on_hand.get(key, 0) + il.quantity - (il.deficient_quantity or 0)

    reserved = get_reserved_quantities(session, project_id, pairs)
    return {key: max(0, on_hand.get(key, 0) - reserved.get(key, 0)) for key in pairs}


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
        row = _new_reservation(project_id, source, request_id, cat, code, qty)
        session.add(row)
        created.append(row)
    if created:
        session.flush()
    return created


def _new_reservation(
    project_id: uuid.UUID,
    source: ReservationSource,
    holder_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    quantity: int,
) -> InventoryReservationModel:
    """One reservation row, with the holder written to the single FK its `source` requires.

    The check constraint (`ck_inventory_reservations_source_matches_request`) refuses any other
    combination, so this is the only place that has to know which column goes with which
    discriminator.
    """
    return InventoryReservationModel(
        id=uuid.uuid4(),
        project_id=project_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=quantity,
        source=source,
        shop_assembly_request_id=(holder_id if source is ReservationSource.SHOP_ASSEMBLY_REQUEST else None),
        shipping_out_request_id=(holder_id if source is ReservationSource.SHIPPING_OUT_REQUEST else None),
        pull_request_id=(holder_id if source is ReservationSource.REPLACEMENT_PULL else None),
    )


def release_reservations(session: Session, source: ReservationSource, request_id: uuid.UUID) -> int:
    """Drop every reservation a request holds and return how many rows went. Idempotent.

    This is the single exit from the reservation table, and every path a request can leave the
    in-flight state on goes through it:

    | Path                                     | Effect                                            |
    | ---------------------------------------- | ------------------------------------------------- |
    | Reject (either request type)             | release - the request is dead, the claim dies too |
    | Reject after a reopen                    | release - same call, same result                  |
    | Reopen an accepted request (#325)        | **no release** - see below                        |
    | Pick confirmation (the reserved path)    | consume - per combo, for what was picked (#367)    |
    | Pick confirmed short                     | **partial consume** - the remainder stays claimed  |
    | Cancelling a pull                        | release, then re-create what it will need again    |
    | Re-upload drops the request's openings    | release, by rebuilding from what survived         |
    | Re-upload leaves the request empty       | auto-reject, which releases                       |
    | Discard a PENDING replacement pull       | release - the pull is hard-deleted, so is its claim |

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


def consume_reservations(
    session: Session,
    source: ReservationSource,
    holder_id: uuid.UUID,
    consumed: Mapping[tuple[str, str], int],
) -> int:
    """Spend part of a holder's claim: the units named here have just become a real deduction (#367).

    `release_reservations` drops a holder's claim whole, which is the right shape for every way a
    request can *die*. Picking is different: a pick can be confirmed short, and the remainder of the
    claim has to survive it. Dropping the whole row on a partial pick would hand the un-picked
    remainder to whoever asked next - the exact hole reservations were introduced to close, opened at
    the one moment the request is provably still owed the hardware.

    So this decrements per combo and deletes only rows that reach zero. Returns the total units
    actually taken off the book.

    **Overshoot is ignored, not an error.** A claim can legitimately be smaller than the pick: a
    replacement pull reserves `min(free stock, condemned)` at flag time, the #342 backfill left the
    pre-existing in-flight population unreserved, and a cancel that could not re-reserve leaves a
    live request holding nothing. In all of those the units are genuinely being taken and the claim
    simply does not cover them; refusing the pick over a bookkeeping row the picker cannot see would
    be the wrong end of the problem.
    """
    wanted = {combo: qty for combo, qty in consumed.items() if qty and qty > 0}
    if not wanted:
        return 0

    rows = session.scalars(
        select(InventoryReservationModel).where(
            InventoryReservationModel.source == source,
            _SOURCE_COLUMN[source] == holder_id,
            _combo_filter(
                wanted.keys(),
                InventoryReservationModel.hardware_category,
                InventoryReservationModel.product_code,
            ),
        )
    ).all()

    taken = 0
    for row in rows:
        want = wanted.get((row.hardware_category, row.product_code), 0)
        if want <= 0:
            continue
        take = min(row.quantity, want)
        wanted[(row.hardware_category, row.product_code)] = want - take
        taken += take
        if take >= row.quantity:
            session.delete(row)
        else:
            row.quantity -= take
    if taken:
        session.flush()
    return taken


def reserve_for_replacement_pull(
    session: Session,
    pull_request_id: uuid.UUID,
    project_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    wanted: int,
) -> int:
    """Claim up to `wanted` more units of one combo for a PR-REPL pull. Returns what it claimed.

    Called the moment a unit is flagged deficient at the bench. Before this existed, the replacement
    pull was the only pull holding nothing: any request created *after* the defect was found could
    take the very stock the replacement was waiting on, so the pull sat blocked while the hardware
    walked. Reserving at the flag puts the replacement into the queue at the moment its demand
    becomes real, which is the only defensible position for it.

    **Claiming less than was condemned is the normal case, not a failure.** The whole reason a
    replacement is needed is often that there is no spare on the shelf; the pull holds whatever it
    could get and `top_up_replacement_reservations` closes the gap as stock arrives or is repaired.

    It only ever claims *free* stock - `get_available_quantities` is already net of everyone else's
    claims - so a replacement can never take hardware another request has reserved. And because every
    term in the chain is keyed by `project_id`, a claim on another project's stock is not expressible.
    """
    if wanted <= 0:
        return 0
    combo = (hardware_category, product_code)
    available = get_available_quantities(session, project_id, [combo], lock=True).get(combo, 0)
    claim = min(available, wanted)
    if claim <= 0:
        return 0

    existing = session.scalars(
        select(InventoryReservationModel).where(
            InventoryReservationModel.source == ReservationSource.REPLACEMENT_PULL,
            InventoryReservationModel.pull_request_id == pull_request_id,
            InventoryReservationModel.hardware_category == hardware_category,
            InventoryReservationModel.product_code == product_code,
        )
    ).first()
    if existing is not None:
        # One row per combo per holder, same as `create_reservations` - every availability sum is an
        # aggregate, and a stack of one-unit rows would only make it add them back up.
        existing.quantity += claim
    else:
        session.add(
            _new_reservation(
                project_id,
                ReservationSource.REPLACEMENT_PULL,
                pull_request_id,
                hardware_category,
                product_code,
                claim,
            )
        )
    session.flush()
    return claim


def top_up_replacement_reservations(
    session: Session,
    project_id: uuid.UUID,
    combos: Iterable[tuple[str, str]],
) -> dict[uuid.UUID, int]:
    """Raise every PENDING replacement pull's claim towards what it actually needs, oldest first.

    A replacement reserves what it can at flag time, which is often less than it was owed. This is
    the other half: whenever availability *rises* - stock is received, a condemned unit is repaired
    back into service - the replacements already waiting get first refusal on it, in the order the
    defects were found. Without it a receive intended to unblock a replacement could be claimed by
    a request created in between, and the replacement would go round the blocked/backfill loop again.

    Oldest pull first is the queue the warehouse already works, and it is what makes the outcome
    deterministic when two replacements want the same scarce combo.

    **Fixed query count, whatever the fan-out.** This runs inside the PO receive transaction, which
    already holds inventory row locks, so it must not turn one receive into a round trip per (pull,
    combo) against Railway's managed Postgres (CLAUDE.md perf rules). Availability for every wanted
    combo is read once under lock, every candidate pull's existing claims are read in one query, the
    allocation is decided in memory oldest-first, and only the rows that actually change are written.

    Returns {pull_request_id: units claimed}, for callers and tests to assert on.
    """
    from .pull_requests import outstanding_loose_needs
    from .receiving import find_open_replacement_pulls

    wanted = set(combos)
    if not wanted:
        return {}

    pulls = sorted(find_open_replacement_pulls(session, project_id, wanted), key=lambda p: p.created_at)
    if not pulls:
        return {}

    # One locked availability read for every combo in play, and one pass over the existing claims of
    # every candidate pull.
    pool = get_available_quantities(session, project_id, sorted(wanted), lock=True)
    held_rows = session.scalars(
        select(InventoryReservationModel).where(
            InventoryReservationModel.source == ReservationSource.REPLACEMENT_PULL,
            InventoryReservationModel.pull_request_id.in_([p.id for p in pulls]),
        )
    ).all()
    held: dict[tuple[uuid.UUID, str, str], InventoryReservationModel] = {
        (row.pull_request_id, row.hardware_category, row.product_code): row for row in held_rows
    }

    claimed: dict[uuid.UUID, int] = {}
    for pr in pulls:
        # What this pull still has to pick of the combos that just became available, net of what it
        # already holds. Outstanding rather than originally-requested (#367): a short-picked pull has
        # part of its hardware on a cart already, and topping its claim back up to the original
        # number would re-claim units it is no longer waiting for.
        needs = {combo: qty for combo, qty in outstanding_loose_needs(session, pr).items() if combo in wanted}

        for combo, need in sorted(needs.items()):
            existing = held.get((pr.id, *combo))
            gap = need - (existing.quantity if existing is not None else 0)
            take = min(gap, pool.get(combo, 0))
            if take <= 0:
                continue
            pool[combo] -= take
            if existing is not None:
                # One row per combo per holder, same as `create_reservations` - every availability sum
                # is an aggregate, and a stack of one-unit rows would only make it add them back up.
                existing.quantity += take
            else:
                row = _new_reservation(project_id, ReservationSource.REPLACEMENT_PULL, pr.id, combo[0], combo[1], take)
                session.add(row)
                held[(pr.id, *combo)] = row
            claimed[pr.id] = claimed.get(pr.id, 0) + take

    if claimed:
        session.flush()
    return claimed
