"""Pull requests: reads, the shared inventory-sufficiency gate, the pick flow, complete/cancel."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    ConflictError,
    InvalidStateTransitionError,
    InventoryShortfallError,
    NotFoundError,
    ValidationError,
)
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    NotificationType,
    PullPickLineState,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.pull_pick_line import PullPickLine as PullPickLineModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.shipping_out_request import ShippingOutRequest as ShippingOutRequestModel
from app.models.shop_assembly import ShopAssemblyRequest as ShopAssemblyRequestModel
from app.models.warehouse import Warehouse as WarehouseModel
from app.services import notification_service
from app.services.locking import lock_rows

from . import reservations
from .audit import _log_audit_event

MAX_CANCELLATION_REASON_LENGTH = 500


def get_pull_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    source=None,
    status=None,
    statuses=None,
    *,
    company: str | None = None,
) -> list[PullRequestModel]:
    """
    Query PullRequest WHERE deleted_at IS NULL, optionally filtered by project_id.
    Optional source filter, optional status filter.
    Order by created_at ASC (FIFO — oldest first).
    Eagerly load items (PullRequestItem).

    `status` filters to one status; `statuses` filters to any of a set - the active queue passes
    [PENDING, IN_PROGRESS] so completed and cancelled pulls leave it the moment they land, and the
    history page passes [COMPLETED, CANCELLED]. The two are additive when both are given.
    """
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(PullRequestModel.deleted_at.is_(None))
    )
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
    if source is not None:
        stmt = stmt.where(PullRequestModel.source == source)
    if status is not None:
        stmt = stmt.where(PullRequestModel.status == status)
    if statuses:
        stmt = stmt.where(PullRequestModel.status.in_(statuses))
    if company is not None:
        from app.repositories import tenancy

        stmt = stmt.where(PullRequestModel.project_id.in_(tenancy.project_ids_for(company)))
    stmt = stmt.order_by(PullRequestModel.created_at.asc())
    return list(session.scalars(stmt).unique().all())


def get_pull_request_details(session: Session, pr_id: uuid.UUID) -> PullRequestModel:
    """
    Single PullRequest by ID, deleted_at IS NULL.
    Eagerly load items.
    Raise NotFoundError if not found.
    """
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(
            PullRequestModel.id == pr_id,
            PullRequestModel.deleted_at.is_(None),
        )
    )
    pr = session.scalars(stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Pull request {pr_id} not found")
    return pr


@dataclass(frozen=True)
class Shortfall:
    """One shorted (hardware_category, product_code) combo: how much was requested, how much is
    available, and the gap. Emitted by the shared sufficiency gate and surfaced verbatim to the
    creator/approver and to the PO backfill notification.

    Since #342 `available` is net of other requests' reservations as well as deficient units, so
    "available: 0" can mean "the stock is here but spoken for". `reserved` carries that number
    separately, which is the difference between "order more" and "release or refine a request"."""

    hardware_category: str
    product_code: str
    requested: int
    available: int
    short: int
    reserved: int = 0


@dataclass
class SufficiencyResult:
    """Result of check_inventory_sufficiency. `shortfalls` is empty iff every combo is fully
    covered. `inventory_by_combo` holds the rows the check read (SELECT ... FOR UPDATE when
    lock=True) grouped by combo, so the caller can deduct FIFO against the very rows it checked."""

    shortfalls: list[Shortfall]
    inventory_by_combo: dict[tuple[str, str], list] = field(default_factory=dict)

    @property
    def sufficient(self) -> bool:
        return not self.shortfalls


def check_inventory_sufficiency(
    session: Session,
    project_id: uuid.UUID,
    needs: Iterable[tuple[str, str, int]],
    *,
    lock: bool = False,
    reservation_aware: bool = False,
    exclude_reservations_of: tuple[ReservationSource, uuid.UUID] | None = None,
) -> SufficiencyResult:
    """Shared hard inventory-sufficiency gate (#224, reservation-aware since #342).

    Aggregates `needs` (an iterable of (hardware_category, product_code, quantity)) by combo,
    compares each against available inventory in the project, and returns a Shortfall per combo
    that can't be fully covered - no partial fulfilment.

    - Base availability is `quantity - deficient_quantity`, the same rule `confirm_pick` deducts
      under. A deficiency reported at the bench bumps the inventory row's `quantity` and
      `deficient_quantity` together, so it nets to zero here - a condemned unit is back in the
      building but is not available, and it is not double-counted against anything.
    - `reservation_aware=True` also subtracts active reservations, giving
      `available = on-hand - deficient - reservations`. This is what request creation gates on:
      stock another request has already claimed is not free.
    - `exclude_reservations_of=(source, request_id)` is **self-coverage**. Spending request R's claim
      is what backs R's own pull, so R's claim must not be counted against R - otherwise a request
      that reserved exactly what it needs could never be satisfied. Everyone else's claims still
      count, which is what stops a PR-REPL replacement pull from eating stock somebody reserved.

    With lock=True the inventory rows are SELECT ... FOR UPDATE and returned grouped by combo, so a
    caller can act against exactly what was checked. Creation locks too: two creators racing for the
    last hinge serialise on those rows, so the second one sees the first one's reservation.

    Since #367 the *warehouse* call site moved rather than disappearing. A pull is no longer refused
    up front, when nobody has looked at a rack; the same arithmetic now runs inside `confirm_pick`,
    against what the picker actually entered, as the third of its three ceilings. Callers are
    therefore the creation gate, the pick confirmation, and the cancel-time re-check.
    """
    needed_combos: dict[tuple[str, str], int] = defaultdict(int)
    for cat, code, qty in needs:
        needed_combos[(cat, code)] += qty

    inv_by_combo: dict[tuple[str, str], list] = defaultdict(list)
    if needed_combos:
        conditions = [
            and_(
                InventoryLocationModel.hardware_category == cat,
                InventoryLocationModel.product_code == code,
            )
            for (cat, code) in needed_combos
        ]
        stmt = (
            select(InventoryLocationModel)
            .where(
                InventoryLocationModel.project_id == project_id,
                or_(*conditions),
            )
            .order_by(InventoryLocationModel.id)
        )
        if lock:
            stmt = stmt.with_for_update()
        for il in session.scalars(stmt).all():
            inv_by_combo[(il.hardware_category, il.product_code)].append(il)

    reserved_by_combo: dict[tuple[str, str], int] = {}
    if reservation_aware and needed_combos:
        exclude_source, exclude_request_id = exclude_reservations_of or (None, None)
        reserved_by_combo = reservations.get_reserved_quantities(
            session,
            project_id,
            needed_combos.keys(),
            exclude_source=exclude_source,
            exclude_request_id=exclude_request_id,
        )

    shortfalls: list[Shortfall] = []
    for (cat, code), requested in needed_combos.items():
        on_hand = sum(il.quantity - (il.deficient_quantity or 0) for il in inv_by_combo.get((cat, code), []))
        reserved = reserved_by_combo.get((cat, code), 0)
        available = max(0, on_hand - reserved)
        if available < requested:
            shortfalls.append(Shortfall(cat, code, requested, available, requested - available, reserved))
    shortfalls.sort(key=lambda s: (s.hardware_category, s.product_code))

    return SufficiencyResult(shortfalls=shortfalls, inventory_by_combo=dict(inv_by_combo))


def gate_on_available_inventory(
    session: Session,
    project_id: uuid.UUID,
    needs: list[tuple[str, str, int]],
    *,
    label: str,
    request_number: str | None,
) -> None:
    """The creation-time inventory gate (#342): refuse the whole request unless every line fits.

    Whole-request, never partial. The creator is being asked to make one decision about one
    selection, so they get the entire list of what does not fit and refine it once - this is what
    replaced the shortfall that used to surface at accept, where nobody could do anything about it.

    The rows are locked for the rest of the transaction, so two creators racing for the last hinge
    serialise: the second sees the first one's reservation rather than both passing on the same
    stock. It lives here, beside the arithmetic it applies, because both request types and both
    screens that raise them gate identically - only the noun in the message differs.
    """
    from app.services import notification_service

    result = check_inventory_sufficiency(session, project_id, needs, lock=True, reservation_aware=True)
    if not result.sufficient:
        raise InventoryShortfallError(
            f"Cannot create this {label} - the hardware it needs is not available. "
            + notification_service.format_shortfall_lines(result.shortfalls)
            + ". Reduce the selection, or wait for stock to be received or another request to be released.",
            shortfalls=result.shortfalls,
            project_id=project_id,
            request_number=request_number,
        )


def find_reservation_holder(session: Session, pr: PullRequestModel) -> tuple[ReservationSource, uuid.UUID] | None:
    """Whose reservations this pull is going to spend, or None if it has none (#342).

    Both request types stamp `pull_request_id` on themselves at accept, so each hop is a single
    indexed lookup.

    None is the honest answer for two cases, and they behave identically downstream (the pull is
    checked against on-hand minus *everyone's* reservations, and consumes nothing):

    - a pull whose source request was **rejected/reopened** after the accept - the claim is gone by
      design.
    - a **legacy pull** minted before this table existed, or one created directly by a non-UI caller.
    """
    if pr.source == PullRequestSource.SHOP_ASSEMBLY:
        sar_id = session.scalar(
            select(ShopAssemblyRequestModel.id).where(ShopAssemblyRequestModel.pull_request_id == pr.id)
        )
        if sar_id is not None:
            return (ReservationSource.SHOP_ASSEMBLY_REQUEST, sar_id)
    elif pr.source == PullRequestSource.SHIPPING_OUT:
        sor_id = session.scalar(
            select(ShippingOutRequestModel.id).where(ShippingOutRequestModel.pull_request_id == pr.id)
        )
        if sor_id is not None:
            return (ReservationSource.SHIPPING_OUT_REQUEST, sor_id)
    return None


# ---------------------------------------------------------------------------
# The pick (#367): start, sheet, draft, confirm
# ---------------------------------------------------------------------------
#
# Before this, approving a pull deducted inventory FIFO by `received_at` in the same call, and
# nobody recorded where the hardware physically came from. The warehouse user - the only person
# actually standing in front of the racks - never chose. Picking splits that single moment in two:
#
#   start_pull_request_pick   the pull is claimed and opened for picking. Nothing moves.
#   confirm_pick              the picker dictates a quantity per location, and *that* deducts.
#
# The #342 invariant is preserved, just relocated: the source request's claim is consumed at the
# exact moment of the deduction, atomically, under the same row locks - which is now confirm rather
# than approve. What changes is that the consumption can be partial, because a pick can be
# confirmed short and the un-picked remainder is still owed.


def start_pull_request_pick(session: Session, pr_id: uuid.UUID, started_by: str) -> PullRequestModel:
    """Claim a PENDING pull and open it for picking (#367). **Nothing moves in inventory.**

    This is what `approve_pull_request` used to be, minus everything that touched stock: no
    sufficiency gate, no FIFO deduction, no reservation consumption. Those all belong to
    `confirm_pick` now, because until somebody has walked the racks and written numbers down, the
    system has no idea what was actually picked or from where.

    Dropping the sufficiency gate *here* is deliberate and is not a hole. It never protected the
    hardware - it protected the *approver* from starting a pull that could not be filled - and it did
    so by refusing before the picker had looked. The check itself did not go away: `confirm_pick`
    runs it against what was actually entered, so scarcity and contention are both discovered where
    they are visible rather than asserted from an aggregate up front. A pull that genuinely cannot be
    filled comes back as a short confirm, which raises the same PO backfill signal it always did.

    `approved_at` keeps its old name and its weaker meaning: the warehouse started on this pull. The
    moment stock left is `picked_at`, and that is what staging and completion gate on.
    """
    locked_prs = lock_rows(session, PullRequestModel, [pr_id])
    if not locked_prs:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked_prs[0]

    # `lock_rows` does not filter soft-deletes, and every read path does. Without this check the
    # status flip below commits and *then* the resolver's re-read raises NotFoundError, leaving the
    # pull IN_PROGRESS with no way back: `_pickable_pull` refuses it, so does starting it again.
    if pr.deleted_at is not None:
        raise NotFoundError(f"Pull request {pr_id} not found")
    if pr.status != PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Pull request must be Pending to start picking, got {pr.status.value}")

    pr.status = PullRequestStatus.IN_PROGRESS
    pr.assigned_to = started_by
    pr.approved_at = datetime.utcnow()
    session.flush()
    return pr


@dataclass(frozen=True)
class PickSheetOpening:
    """One opening a section's units are owed to. Every opening is listed, never summarised: the
    picker is building carts per door, and "and 6 more" is exactly the information they need."""

    opening_number: str | None
    quantity: int


@dataclass(frozen=True)
class PickSheetLocation:
    """One inventory row a section's product could be picked from, as the sheet shows it.

    `received_at` is here so the picker can rotate stock themselves. There is deliberately **no
    suggested quantity**: the system proposing a split and the human overriding it is how a
    suggestion quietly becomes the default, and the whole point of #367 is that the person at the
    rack decides."""

    inventory_location_id: uuid.UUID
    warehouse_id: uuid.UUID | None
    warehouse_code: str | None
    aisle: str | None
    row: str | None
    bay: str | None
    available: int
    received_at: datetime
    draft_quantity: int
    applied_quantity: int
    # #496: what the vendor called this part, and the PO it arrived on. Per location rather than per
    # section: one product can sit in inventory from several POs with different Order As values, so
    # a section-level value would be wrong for every row but one. Null on a stock-origin row, which
    # has no PO line behind it.
    order_as: str | None = None
    po_number: str | None = None


@dataclass(frozen=True)
class PickSheetSection:
    """One product code to pick, with everywhere it can come from and every opening it is owed to."""

    hardware_category: str
    product_code: str
    required_quantity: int
    applied_quantity: int
    openings: list[PickSheetOpening]
    locations: list[PickSheetLocation]
    # What this pull may actually take: on-hand minus condemned minus *other* requests' claims. It is
    # the third ceiling `confirm_pick` enforces, surfaced here so a picker learns about contention on
    # the screen and the printed sheet rather than by being refused after walking the racks. Equal to
    # the sum of the locations' `available` whenever nothing else has claimed the product, which is
    # the ordinary case.
    claimable_quantity: int = 0

    @property
    def remaining_quantity(self) -> int:
        return max(0, self.required_quantity - self.applied_quantity)

    @property
    def claimable_shortfall(self) -> int:
        """How far short of what is still needed this pull's claimable stock falls. 0 when covered."""
        return max(0, self.remaining_quantity - self.claimable_quantity)


@dataclass(frozen=True)
class PickSheet:
    pull_request: PullRequestModel
    sections: list[PickSheetSection]


def _line_requirements(pr: PullRequestModel) -> dict[tuple[str, str], int]:
    """What the pull's lines add up to, per combo. The pick's denominator."""
    required: dict[tuple[str, str], int] = defaultdict(int)
    for item in pr.items:
        if item.requested_quantity <= 0:
            continue
        required[(item.hardware_category, item.product_code)] += item.requested_quantity
    return dict(required)


def _claimable_by_combo(
    session: Session,
    pr: PullRequestModel,
    combos: Iterable[tuple[str, str]],
) -> dict[tuple[str, str], int]:
    """What this pull may actually take of each combo: on-hand minus condemned minus *other*
    requests' reservations, floored at 0 (#367).

    Two grouped aggregates whatever the pull covers. This is the number `confirm_pick`'s third
    ceiling enforces and `get_pick_sheet` puts on the screen, so both read it the same way - the
    screen must never promise a quantity the confirm will refuse.
    """
    wanted = list(combos)
    if not wanted:
        return {}

    on_hand = {
        (cat, code): int(total or 0)
        for cat, code, total in session.execute(
            select(
                InventoryLocationModel.hardware_category,
                InventoryLocationModel.product_code,
                func.coalesce(
                    func.sum(
                        InventoryLocationModel.quantity - func.coalesce(InventoryLocationModel.deficient_quantity, 0)
                    ),
                    0,
                ),
            )
            .where(
                InventoryLocationModel.project_id == pr.project_id,
                or_(
                    *[
                        and_(
                            InventoryLocationModel.hardware_category == cat,
                            InventoryLocationModel.product_code == code,
                        )
                        for (cat, code) in wanted
                    ]
                ),
            )
            .group_by(InventoryLocationModel.hardware_category, InventoryLocationModel.product_code)
        ).all()
    }

    holder = find_reservation_holder(session, pr)
    exclude_source, exclude_request_id = holder or (None, None)
    reserved = reservations.get_reserved_quantities(
        session,
        pr.project_id,
        wanted,
        exclude_source=exclude_source,
        exclude_request_id=exclude_request_id,
    )
    return {combo: max(0, on_hand.get(combo, 0) - reserved.get(combo, 0)) for combo in wanted}


def outstanding_needs(session: Session, pr: PullRequestModel) -> dict[tuple[str, str], int]:
    """What a pull still has to pick, per combo: what it asked for minus what it has already picked.

    Identical to `_line_requirements` for any pull that has picked nothing, which is every pull that
    has not been started. It differs only for a **short-picked** one (#367).

    Combos that are fully picked drop out entirely rather than appearing as zero.
    """
    already = _applied_by_combo(session, pr.id)
    outstanding = {}
    for combo, total in _line_requirements(pr).items():
        remaining = total - already.get(combo, 0)
        if remaining > 0:
            outstanding[combo] = remaining
    return outstanding


def _pick_lines(session: Session, pr_id: uuid.UUID, state: PullPickLineState | None = None) -> list[PullPickLineModel]:
    stmt = select(PullPickLineModel).where(PullPickLineModel.pull_request_id == pr_id)
    if state is not None:
        stmt = stmt.where(PullPickLineModel.state == state)
    return list(session.scalars(stmt).all())


def _applied_by_combo(session: Session, pr_id: uuid.UUID) -> dict[tuple[str, str], int]:
    """How much of each combo this pull has already picked. One grouped aggregate, no rows loaded."""
    rows = session.execute(
        select(
            PullPickLineModel.hardware_category,
            PullPickLineModel.product_code,
            func.coalesce(func.sum(PullPickLineModel.quantity), 0),
        )
        .where(
            PullPickLineModel.pull_request_id == pr_id,
            PullPickLineModel.state == PullPickLineState.APPLIED,
        )
        .group_by(PullPickLineModel.hardware_category, PullPickLineModel.product_code)
    ).all()
    return {(cat, code): int(total or 0) for cat, code, total in rows}


def get_pick_sheet(session: Session, pr_id: uuid.UUID) -> PickSheet:
    """Everything the pick screen and the printed sheet need, in a fixed number of queries (#367).

    A fixed handful of reads regardless of how many product codes the pull covers, because a
    per-section query over Railway's network hop is the N+1 that turns "fast on dev" into a frozen
    page (CLAUDE.md perf rules): the pull with its items, every candidate inventory row for every
    combo at once, and two more for the claimable-quantity arithmetic (the holder lookup and one
    grouped aggregate over reservations).

    A location is a candidate when it still has available units **or** when this pull has already
    named it. The second half matters: a row picked down to zero must stay on the sheet, or the row
    the picker took twelve units off vanishes the moment they confirm and the sheet stops matching
    the paper in their hand.
    """
    pr = get_pull_request_details(session, pr_id)

    required = _line_requirements(pr)
    applied_lines = _pick_lines(session, pr.id)
    applied_by_combo: dict[tuple[str, str], int] = defaultdict(int)
    by_location: dict[tuple[str, str, uuid.UUID], dict[str, int]] = defaultdict(lambda: {"draft": 0, "applied": 0})
    referenced_location_ids: set[uuid.UUID] = set()
    for line in applied_lines:
        if line.inventory_location_id is not None:
            referenced_location_ids.add(line.inventory_location_id)
            key = (line.hardware_category, line.product_code, line.inventory_location_id)
            bucket = "applied" if line.state == PullPickLineState.APPLIED else "draft"
            by_location[key][bucket] += line.quantity
        if line.state == PullPickLineState.APPLIED:
            applied_by_combo[(line.hardware_category, line.product_code)] += line.quantity

    # Openings per combo, in the order the carts are laid out.
    openings_by_combo: dict[tuple[str, str], list[PickSheetOpening]] = defaultdict(list)
    for item in pr.items:
        if item.requested_quantity <= 0:
            continue
        openings_by_combo[(item.hardware_category, item.product_code)].append(
            PickSheetOpening(opening_number=item.opening_number, quantity=item.requested_quantity)
        )

    locations_by_combo: dict[tuple[str, str], list[PickSheetLocation]] = defaultdict(list)
    if required:
        combo_clause = or_(
            *[
                and_(
                    InventoryLocationModel.hardware_category == cat,
                    InventoryLocationModel.product_code == code,
                )
                for (cat, code) in required
            ]
        )
        visibility = InventoryLocationModel.quantity - func.coalesce(InventoryLocationModel.deficient_quantity, 0) > 0
        if referenced_location_ids:
            visibility = or_(visibility, InventoryLocationModel.id.in_(referenced_location_ids))
        rows = session.execute(
            select(InventoryLocationModel, WarehouseModel.code, POLineItemModel.order_as, POModel.po_number)
            .outerjoin(WarehouseModel, WarehouseModel.id == InventoryLocationModel.warehouse_id)
            # #496: one joined read for the whole sheet, no per-row lazy loads.
            .outerjoin(POLineItemModel, POLineItemModel.id == InventoryLocationModel.po_line_item_id)
            .outerjoin(POModel, POModel.id == POLineItemModel.po_id)
            .where(
                InventoryLocationModel.project_id == pr.project_id,
                combo_clause,
                visibility,
            )
            .order_by(InventoryLocationModel.received_at.asc(), InventoryLocationModel.id.asc())
        ).all()
        for il, warehouse_code, order_as, po_number in rows:
            combo = (il.hardware_category, il.product_code)
            counts = by_location.get((*combo, il.id), {"draft": 0, "applied": 0})
            locations_by_combo[combo].append(
                PickSheetLocation(
                    inventory_location_id=il.id,
                    warehouse_id=il.warehouse_id,
                    warehouse_code=warehouse_code,
                    aisle=il.aisle,
                    row=il.row,
                    bay=il.bay,
                    available=max(0, il.quantity - (il.deficient_quantity or 0)),
                    received_at=il.received_at,
                    draft_quantity=counts["draft"],
                    applied_quantity=counts["applied"],
                    order_as=order_as,
                    po_number=po_number,
                )
            )

    # What this pull may actually claim per combo, net of everyone else's reservations and with its
    # own holder excluded (self-coverage). Two queries for the whole sheet: the holder lookup and one
    # grouped aggregate over the reservation table. On-hand comes free - it is the sum of the
    # locations already read above, since a row with nothing available contributes nothing.
    holder = find_reservation_holder(session, pr) if required else None
    exclude_source, exclude_request_id = holder or (None, None)
    reserved_by_others = (
        reservations.get_reserved_quantities(
            session,
            pr.project_id,
            list(required),
            exclude_source=exclude_source,
            exclude_request_id=exclude_request_id,
        )
        if required
        else {}
    )

    sections = [
        PickSheetSection(
            hardware_category=cat,
            product_code=code,
            required_quantity=total,
            applied_quantity=applied_by_combo.get((cat, code), 0),
            openings=sorted(
                openings_by_combo.get((cat, code), []),
                key=lambda opening: opening.opening_number or "",
            ),
            locations=locations_by_combo.get((cat, code), []),
            claimable_quantity=max(
                0,
                sum(loc.available for loc in locations_by_combo.get((cat, code), []))
                - reserved_by_others.get((cat, code), 0),
            ),
        )
        for (cat, code), total in sorted(required.items())
    ]

    return PickSheet(pull_request=pr, sections=sections)


@dataclass(frozen=True)
class PickLine:
    """One line the picker dictated: this many units of this combo off this inventory row."""

    hardware_category: str
    product_code: str
    inventory_location_id: uuid.UUID
    quantity: int


def _normalise_pick_lines(
    lines: Iterable[PickLine],
    required: dict[tuple[str, str], int],
) -> dict[tuple[str, str, uuid.UUID], int]:
    """Aggregate the submitted lines by (combo, location), dropping zeros and refusing nonsense.

    Two lines naming the same row is a legitimate thing for a client to send (two leaves picked off
    the same bin), so they are summed rather than rejected - the row-level availability check runs
    against the total, which is what actually leaves the shelf.
    """
    entered: dict[tuple[str, str, uuid.UUID], int] = defaultdict(int)
    for line in lines:
        if line.quantity is None or line.quantity == 0:
            continue
        if line.quantity < 0:
            raise ValidationError(
                f"Picked quantity for {line.hardware_category} {line.product_code} cannot be negative",
                field="quantity",
            )
        combo = (line.hardware_category, line.product_code)
        if combo not in required:
            raise ValidationError(
                f"{line.hardware_category} {line.product_code} is not on this pull request",
                field="lines",
            )
        if line.inventory_location_id is None:
            raise ValidationError(
                f"A location is required for every picked line ({line.hardware_category} {line.product_code})",
                field="inventoryLocationId",
            )
        entered[(*combo, line.inventory_location_id)] += line.quantity
    return {key: qty for key, qty in entered.items() if qty > 0}


def _pickable_pull(session: Session, pr_id: uuid.UUID) -> PullRequestModel:
    """Lock the pull and refuse anything that is not an open, un-picked, in-progress pull."""
    locked = lock_rows(session, PullRequestModel, [pr_id])
    if not locked:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked[0]
    if pr.deleted_at is not None:
        raise NotFoundError(f"Pull request {pr_id} not found")
    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(
            f"Pull request must be In_Progress to pick, got {pr.status.value}. Start the pick first."
        )
    if pr.picked_at is not None:
        raise InvalidStateTransitionError(
            f"Pull request {pr.request_number} has already been picked - its hardware is off the shelf."
        )
    return pr


def save_pick_draft(
    session: Session,
    pr_id: uuid.UUID,
    lines: Iterable[PickLine],
    entered_by: str,
) -> PickSheet:
    """Save the half-keyed sheet without moving anything (#367).

    **Replace-all, not merge.** The picker is transcribing a piece of paper, and the paper is the
    authority: a save says "this is the sheet now", so the pull's whole DRAFT set is discarded and
    rewritten. Merging would silently keep a row the picker had crossed out, which is the one
    outcome a transcription must not produce.

    Shape is validated - the combo is on this pull, the location belongs to this project, the
    quantity is positive - but **availability is not**. A draft is a note, not a claim; blocking a
    picker from writing down what is on their sheet because the numbers do not balance yet would
    make the save button useless exactly when it is needed. `confirm_pick` is the gate.
    """
    pr = _pickable_pull(session, pr_id)
    required = _line_requirements(pr)
    entered = _normalise_pick_lines(lines, required)

    location_ids = sorted({loc_id for (_cat, _code, loc_id) in entered})
    rows = _load_pick_locations(session, pr, location_ids, entered)

    session.execute(
        delete(PullPickLineModel).where(
            PullPickLineModel.pull_request_id == pr.id,
            PullPickLineModel.state == PullPickLineState.DRAFT,
        )
    )
    now = datetime.utcnow()
    for (cat, code, loc_id), qty in sorted(entered.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        session.add(
            PullPickLineModel(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                hardware_category=cat,
                product_code=code,
                inventory_location_id=rows[loc_id].id,
                quantity=qty,
                state=PullPickLineState.DRAFT,
                entered_by=entered_by,
                entered_at=now,
            )
        )
    session.flush()
    return get_pick_sheet(session, pr.id)


def _load_pick_locations(
    session: Session,
    pr: PullRequestModel,
    location_ids: list[uuid.UUID],
    entered: dict[tuple[str, str, uuid.UUID], int],
    *,
    lock: bool = False,
) -> dict[uuid.UUID, InventoryLocationModel]:
    """Resolve the named inventory rows and check they are the rows the picker says they are.

    `lock=True` takes the row locks in id order, the same order every other inventory writer takes
    them in, so a concurrent confirm on a shared bin serialises here rather than lost-updating.
    """
    if not location_ids:
        return {}
    if lock:
        rows = lock_rows(session, InventoryLocationModel, location_ids)
    else:
        rows = list(
            session.scalars(select(InventoryLocationModel).where(InventoryLocationModel.id.in_(location_ids))).all()
        )
    by_id = {row.id: row for row in rows}
    missing = [str(loc_id) for loc_id in location_ids if loc_id not in by_id]
    if missing:
        raise NotFoundError(f"Inventory locations not found: {', '.join(missing)}")

    for cat, code, loc_id in entered:
        row = by_id[loc_id]
        if row.project_id != pr.project_id:
            raise ValidationError(
                "That location holds another project's inventory - a pull can only take its own project's stock.",
                field="inventoryLocationId",
            )
        if (row.hardware_category, row.product_code) != (cat, code):
            raise ValidationError(
                f"Location {loc_id} holds {row.hardware_category} {row.product_code}, not {cat} {code}",
                field="inventoryLocationId",
            )
    return by_id


@dataclass
class ConfirmPickResult:
    """What one pick confirmation did (#367).

    `outcome` is PICKED when every combo is now fully covered (the pull is stamped picked and can be
    staged) or SHORT when it is not. SHORT is a real, resumable state, not a failure: the units
    entered are deducted and recorded, the pull stays In Progress and un-picked, purchasing is
    notified, and a later confirmation enters the remainder."""

    pull_request: PullRequestModel
    outcome: str
    shortfalls: list[Shortfall]
    notification: object | None = None
    applied_quantity: int = 0


def confirm_pick(
    session: Session,
    pr_id: uuid.UUID,
    lines: Iterable[PickLine],
    picked_by: str,
) -> ConfirmPickResult:
    """Deduct exactly the rows the picker dictated, and consume the claim behind them (#367).

    This is the atomic swap the old `approve_pull_request` performed, moved to the moment somebody
    has actually been to the racks. In one transaction, under the pull's lock and the locks of every
    named inventory row:

    1. the source request's reservation is consumed for what is being picked (partially - see
       `reservations.consume_reservations`), and
    2. those units come off the exact rows named.

    Consumption happens before the deduction so the two can never be observed apart: a reader
    between them would otherwise see the units both reserved and already gone.

    **Never over-pull.** Three independent ceilings, all hard and none negotiable from the client:

    1. **The row.** No `InventoryLocation` may give up more than its own `quantity -
       deficient_quantity`, so condemned stock stays put.
    2. **The request.** No combo may exceed what the pull asked for, counting what is already picked.
    3. **Everyone else's claims.** No combo may exceed what is genuinely free for *this* pull -
       `on-hand - deficient - other requests' reservations` - with this pull's own holder excluded
       (self-coverage), because its claim is exactly what backs the deduction. This one raises
       `ConflictError`, and only when reservations are genuinely the cause: a plain shortage is left
       to ceiling 1, which names the bin instead of blaming a request that does not exist.

    The third ceiling is what keeps #342 intact. Without it a pull holding no claim of its own (a
    replacement that could only partly reserve, a request from the #342 backfill population) could
    walk off with stock another request had already been promised, and that request would discover it
    as a short pick on its own pull. The reservation table exists precisely so that cannot happen, and
    a claim that only holds until somebody physically reaches the shelf first is not a claim.

    It is a genuine cost: a picker can be refused with hardware in their hand. Two things make that
    the right trade. The refusal names the combo and how much is claimable, so it is actionable
    rather than mysterious; and `get_pick_sheet` surfaces the same number as
    `PickSheetSection.claimable_quantity`, so the constraint is visible on the screen and the printed
    sheet *before* the walk rather than after it.

    **Short is a first-class outcome.** Deduct what was entered, leave the pull In Progress and
    un-picked, notify purchasing, and let a second confirmation cover the remainder. The alternative
    - refusing the whole confirmation - would mean a picker who found nine of twelve hinges has to
    put the nine back on the shelf, which nobody does; they would go and mark the pull complete
    anyway and the system would be lying.

    A pull with no LOOSE lines at all (a pure fetch pull: shipping out assembled leaves) is picked
    the moment it is confirmed with nothing, because there is nothing to deduct.
    """
    pr = _pickable_pull(session, pr_id)
    required = _line_requirements(pr)
    entered = _normalise_pick_lines(lines, required)
    already = _applied_by_combo(session, pr.id)
    now = datetime.utcnow()

    # A confirmation with nothing entered has two very different meanings, and only one of them is a
    # mistake.
    #
    # "I walked the racks and there was nothing there" is a **real outcome** and the honest way to
    # record it: the pull is confirmed short of everything, and purchasing is told. That is the
    # direct analogue of the old approve-time INSUFFICIENT, and refusing it would leave a picker who
    # found an empty bin with no way to say so.
    #
    # "I submitted an empty sheet while the stock was sitting there" is a no-op that deducts nothing,
    # reports the whole requirement as short, and raises a PO backfill signal for a walk nobody took
    # - which `has_unread_notification_for_pull` would then let suppress the *real* signal from the
    # pick that follows.
    #
    # The two are separated by whether there was anything to pick, so that is what is checked. One
    # extra pair of aggregates, only on the empty-submission path.
    if required and not entered and any(qty > 0 for qty in _claimable_by_combo(session, pr, required).values()):
        raise ValidationError(
            "Nothing was entered, but there is stock available for this pull. Record what came off "
            "each location before confirming.",
            field="lines",
        )

    # No combo may be pushed past what the pull asked for, counting what is already picked.
    entered_by_combo: dict[tuple[str, str], int] = defaultdict(int)
    for (cat, code, _loc_id), qty in entered.items():
        entered_by_combo[(cat, code)] += qty
    for combo, qty in sorted(entered_by_combo.items()):
        ceiling = required[combo] - already.get(combo, 0)
        if qty > ceiling:
            raise ValidationError(
                f"{combo[0]} {combo[1]}: entering {qty} would pull more than the {required[combo]} this "
                f"request asked for ({already.get(combo, 0)} already picked, {max(0, ceiling)} left to pick)",
                field="quantity",
            )

    # Nor past what is free once everyone else's claims are counted. Deliberately run *before* the
    # named rows are locked: this locks every row of every combo in play, a superset of them, in the
    # same id order `lock_rows` uses - so the narrower lock below is already held and no two
    # concurrent confirms can take the two sets in opposite orders.
    holder = find_reservation_holder(session, pr)
    if entered_by_combo:
        contention = check_inventory_sufficiency(
            session,
            pr.project_id,
            [(cat, code, qty) for (cat, code), qty in entered_by_combo.items()],
            lock=True,
            reservation_aware=True,
            exclude_reservations_of=holder,
        )
        # Only speak of contention when reservations are the *whole* reason. A combo can also come up
        # short because the project simply does not hold that much, and telling a picker "the units
        # are on the shelf but they are spoken for" when half of them do not exist sends them
        # hunting for a competing request that cannot explain the gap. The test is whether the entry
        # would have fitted with the reservations removed: if on-hand alone covers it, the claim is
        # the only obstacle and this is genuine contention. Otherwise it is (also) plain scarcity,
        # and the per-row check below gives the better answer by naming the bin and the number.
        #
        # Falling through is safe rather than a hole: entered exceeding on-hand means the rows named
        # were collectively asked for more than they hold, so at least one was entered past its own
        # available units, which is precisely what that check catches.
        on_hand = {
            combo: sum(row.quantity - (row.deficient_quantity or 0) for row in rows_for_combo)
            for combo, rows_for_combo in contention.inventory_by_combo.items()
        }
        contested = [
            s
            for s in contention.shortfalls
            if s.reserved > 0 and s.requested <= on_hand.get((s.hardware_category, s.product_code), 0)
        ]
        if contested:
            blocked = "; ".join(
                f"{s.hardware_category} {s.product_code}: {s.requested} entered but only {s.available} "
                f"free for this pull ({s.reserved} claimed by other requests)"
                for s in contested
            )
            raise ConflictError(
                f"Another request has already claimed this stock - {blocked}. The units are on the "
                "shelf but they are spoken for, so this pull cannot take them. Confirm what is "
                "genuinely free and purchasing will be told about the rest.",
                field="quantity",
            )

    location_ids = sorted({loc_id for (_cat, _code, loc_id) in entered})
    rows = _load_pick_locations(session, pr, location_ids, entered, lock=True)

    # No row may give up more than it has available. Aggregated per row first: two lines naming the
    # same bin are one withdrawal as far as the shelf is concerned.
    per_row: dict[uuid.UUID, int] = defaultdict(int)
    for (_cat, _code, loc_id), qty in entered.items():
        per_row[loc_id] += qty
    for loc_id, qty in sorted(per_row.items(), key=lambda kv: str(kv[0])):
        row = rows[loc_id]
        row_available = row.quantity - (row.deficient_quantity or 0)
        if qty > row_available:
            raise ValidationError(
                f"{row.hardware_category} {row.product_code} at "
                f"{_location_label(row)}: {qty} entered but only {row_available} available",
                field="quantity",
            )

    # 1. Consume the claim for what is about to leave. Partial by design: a short confirm keeps the
    #    remainder claimed, so the un-picked units are not quietly handed to whoever asks next.
    if holder is not None and entered_by_combo:
        reservations.consume_reservations(session, holder[0], holder[1], entered_by_combo)

    # 2. Deduct the dictated rows, one audit and one APPLIED pick line each.
    warehouse_codes = _warehouse_codes(session, [row.warehouse_id for row in rows.values()])
    applied_total = 0
    for (cat, code, loc_id), qty in sorted(entered.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        row = rows[loc_id]
        old_qty = row.quantity
        row.quantity -= qty
        applied_total += qty
        session.add(
            PullPickLineModel(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                hardware_category=cat,
                product_code=code,
                inventory_location_id=row.id,
                quantity=qty,
                state=PullPickLineState.APPLIED,
                entered_by=picked_by,
                entered_at=now,
                applied_at=now,
            )
        )
        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=row.id,
            action=AuditAction.PULL_DEDUCTION,
            performed_by=picked_by,
            detail={
                "oldQuantity": old_qty,
                "newQuantity": row.quantity,
                "deducted": qty,
                "pullRequestId": str(pr.id),
                "pullRequestNumber": pr.request_number,
                "hardwareCategory": cat,
                "productCode": code,
                "warehouseId": str(row.warehouse_id) if row.warehouse_id else None,
                "warehouseCode": warehouse_codes.get(row.warehouse_id),
                "aisle": row.aisle,
                "row": row.row,
                "bay": row.bay,
            },
        )

    # The draft was the transcription in progress; the confirmation supersedes it whole, including
    # on a short confirm - what was entered is now APPLIED, and the remainder is keyed fresh.
    session.execute(
        delete(PullPickLineModel).where(
            PullPickLineModel.pull_request_id == pr.id,
            PullPickLineModel.state == PullPickLineState.DRAFT,
        )
    )
    session.flush()

    covered = {combo: already.get(combo, 0) + entered_by_combo.get(combo, 0) for combo in required}
    short_combos = {combo: required[combo] - picked for combo, picked in covered.items() if picked < required[combo]}

    if not short_combos:
        pr.picked_at = now
        pr.picked_by = picked_by
        session.flush()
        return ConfirmPickResult(
            pull_request=pr, outcome="PICKED", shortfalls=[], notification=None, applied_quantity=applied_total
        )

    shortfalls = _pick_shortfalls(session, pr, required, covered, short_combos, holder)
    notif = None
    # One open signal per pull, not one per confirmation: a picker keying a big sheet in three
    # sittings would otherwise raise three identical backfill notifications for the same gap.
    if not notification_service.has_unread_notification_for_pull(session, pr.id, NotificationType.INVENTORY_SHORTFALL):
        notif = notification_service.notify_po_shortfall(
            session,
            project_id=pr.project_id,
            request_number=pr.request_number,
            shortfalls=shortfalls,
            pull_request_id=pr.id,
            # These shortfalls carry the pick frame (short = still owed, available = free now), not
            # the gate frame (short = need - available); the gate template misreads them.
            pick_frame=True,
        )

    # An *integrity* signal, so it must fire only for a pull that genuinely held a claim for
    # everything it is asking for. Having a source request is not the same as holding reservations:
    # the #342 backfill deliberately left the whole pre-existing in-flight population unreserved and
    # flagged rather than inventing claims for it, and a cancel that could not re-reserve leaves a
    # live request in the same state. Those are the *expected* shortfall population - flagging every
    # one of them is exactly how a real discrepancy gets missed.
    if holder is not None and reservations.get_reserved_total(session, holder[0], holder[1]) > 0:
        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.PULL_REQUEST,
            entity_id=pr.id,
            action=AuditAction.PULL_DEDUCTION,
            performed_by=picked_by,
            detail={
                "integrityError": "RESERVED_PULL_SHORT",
                "pullRequestNumber": pr.request_number,
                "reservationSource": holder[0].value,
                "reservationRequestId": str(holder[1]),
                "shortfalls": [
                    {
                        "hardwareCategory": s.hardware_category,
                        "productCode": s.product_code,
                        "requested": s.requested,
                        "available": s.available,
                        "short": s.short,
                    }
                    for s in shortfalls
                ],
            },
        )

    return ConfirmPickResult(
        pull_request=pr,
        outcome="SHORT",
        shortfalls=shortfalls,
        notification=notif,
        applied_quantity=applied_total,
    )


def _location_label(row: InventoryLocationModel) -> str:
    parts = [p for p in (row.aisle, row.row, row.bay) if p]
    return "-".join(parts) if parts else "Unlocated"


def _warehouse_codes(session: Session, warehouse_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    """Codes for the warehouses the picked rows sit in. One query for the whole confirmation."""
    ids = sorted({wid for wid in warehouse_ids if wid is not None})
    if not ids:
        return {}
    return {
        wid: code
        for wid, code in session.execute(
            select(WarehouseModel.id, WarehouseModel.code).where(WarehouseModel.id.in_(ids))
        ).all()
    }


def _pick_shortfalls(
    session: Session,
    pr: PullRequestModel,
    required: dict[tuple[str, str], int],
    covered: dict[tuple[str, str], int],
    short_combos: dict[tuple[str, str], int],
    holder: tuple[ReservationSource, uuid.UUID] | None,
) -> list[Shortfall]:
    """The gap, reported the way the approve-time gate always reported it.

    `available` is read *after* the deduction, so it answers the question purchasing actually has -
    what is left in the project for this product right now - rather than restating what the picker
    already knows they could not find. Two grouped aggregates for the whole confirmation."""
    combos = sorted(short_combos)
    on_hand: dict[tuple[str, str], int] = {}
    rows = session.execute(
        select(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.coalesce(
                func.sum(InventoryLocationModel.quantity - func.coalesce(InventoryLocationModel.deficient_quantity, 0)),
                0,
            ),
        )
        .where(
            InventoryLocationModel.project_id == pr.project_id,
            or_(
                *[
                    and_(
                        InventoryLocationModel.hardware_category == cat,
                        InventoryLocationModel.product_code == code,
                    )
                    for (cat, code) in combos
                ]
            ),
        )
        .group_by(InventoryLocationModel.hardware_category, InventoryLocationModel.product_code)
    ).all()
    for cat, code, total in rows:
        on_hand[(cat, code)] = int(total or 0)

    exclude_source, exclude_request_id = holder or (None, None)
    reserved = reservations.get_reserved_quantities(
        session,
        pr.project_id,
        combos,
        exclude_source=exclude_source,
        exclude_request_id=exclude_request_id,
    )

    return [
        Shortfall(
            hardware_category=cat,
            product_code=code,
            requested=required[(cat, code)],
            available=max(0, on_hand.get((cat, code), 0) - reserved.get((cat, code), 0)),
            short=required[(cat, code)] - covered[(cat, code)],
            reserved=reserved.get((cat, code), 0),
        )
        for (cat, code) in combos
    ]


def _require_picked(pr: PullRequestModel, action: str) -> None:
    """Refuse anything downstream of the pick until the pick has actually been confirmed (#367).

    Staging says a cart is built and completion hands the pull over; both are claims about physical
    hardware. Before per-location picking they were safe by construction, because approval had
    already deducted. Now approval only opens the pull, so without this gate a pull could be staged -
    making its openings assignable on the shop floor - while its stock was still on the shelf and
    still claimable by the next request."""
    if pr.picked_at is None:
        raise InvalidStateTransitionError(
            f"Pull request {pr.request_number} has not been picked yet - confirm the pick before you {action} it."
        )


def complete_pull_request(session: Session, pr_id: uuid.UUID, completed_by: str | None = None) -> PullRequestModel:
    """Hand a picked pull over: status Completed, and the requester told.

    **This is a terminal exit.** Completion is the last thing the system records about this
    hardware - the shop takes its cart to the bench, or the shipping desk cuts a slip against what
    the pull fulfilled. Nothing downstream is tracked in v1, which is why there are no
    source-specific side effects left here: there is no assembled unit to materialize and no leaf
    state to advance.

    The `completed_by` argument is kept because callers pass it and the audit trail around
    completion reads better with an actor, even though nothing on the pull row records it - the
    notification and the pick's own stamps carry the provenance.
    """
    # Take the pull's row lock before reading its status, so two callers arriving at an IN_PROGRESS
    # pull at once cannot both pass the status check and both raise a completion notification.
    if not lock_rows(session, PullRequestModel, [pr_id]):
        raise NotFoundError(f"Pull request {pr_id} not found")
    stmt = select(PullRequestModel).options(selectinload(PullRequestModel.items)).where(PullRequestModel.id == pr_id)
    pr = session.scalars(stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Pull request {pr_id} not found")

    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(f"Pull request must be In_Progress to complete, got {pr.status.value}")
    _require_picked(pr, "complete")

    now = datetime.utcnow()
    pr.status = PullRequestStatus.COMPLETED
    pr.completed_at = now

    # Create notification
    notification_service.create_notification(
        session,
        project_id=pr.project_id,
        recipient_role=pr.requested_by,
        notification_type=NotificationType.PULL_REQUEST_COMPLETED,
        message=f"Pull Request {pr.request_number} has been fulfilled.",
        pull_request_id=pr.id,
    )

    return pr


def get_partially_picked_pull_ids(session: Session, pr_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Which of these pulls have picked *something* without being finished (#367).

    The queue draws a phase per row - Pending / Picking / Short / Staging n of m / Completed - and
    "Short" is exactly "un-picked, but stock has already come off the shelf for it". That is one
    grouped EXISTS over `pull_pick_lines` for the whole page, never a lookup per row (CLAUDE.md perf
    rules): the pull-request queue is the screen that made the resolver N+1 a production incident.

    Callers pass only the un-picked pulls; a pull with `picked_at` set is finished picking by
    definition and its answer would be meaningless.
    """
    ids = [pid for pid in pr_ids if pid is not None]
    if not ids:
        return set()
    rows = session.execute(
        select(PullPickLineModel.pull_request_id)
        .where(
            PullPickLineModel.pull_request_id.in_(ids),
            PullPickLineModel.state == PullPickLineState.APPLIED,
        )
        .group_by(PullPickLineModel.pull_request_id)
    ).all()
    return {row[0] for row in rows}


# ---------------------------------------------------------------------------
# Cancel / restock (#343)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RestockedLine:
    hardware_category: str
    product_code: str
    quantity: int


@dataclass
class CancelResult:
    pull_request: PullRequestModel
    restocked: list[RestockedLine]
    source_request_returned_to_pending: bool
    reservations_recreated: bool
    integrity_note: str | None


def _return_units_to_project_inventory(
    session: Session,
    project_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    quantity: int,
) -> InventoryLocationModel:
    """Put `quantity` units of one combo back into project inventory as available stock.

    This is the inverse of the FIFO deduction, and it deliberately does **not** try to reverse it row
    by row. The deduction spread across whichever `InventoryLocation` rows were oldest; which row a
    hinge sits on carries no identity (docs/HARDWARE_IDENTITY_LIFECYCLE.md - inventory is fungible),
    so reconstructing the original split from the audit log would be fragile bookkeeping in service
    of a distinction the domain does not make. The units land on the project's most recently received
    row for the combo, and a row is re-materialized if a schedule re-upload deleted the last one.
    Landing on the *newest*
    row is also the conservative choice for future FIFO: older stock still goes out first.
    """
    from app.repositories import warehouse_admin_repository
    from app.repositories.stock.common import _find_or_create_stock_row

    il = session.scalars(
        select(InventoryLocationModel)
        .where(
            InventoryLocationModel.project_id == project_id,
            InventoryLocationModel.hardware_category == hardware_category,
            InventoryLocationModel.product_code == product_code,
        )
        .order_by(InventoryLocationModel.received_at.desc())
    ).first()
    if il is None:
        from .inventory import resolve_project_combo_cost

        now = datetime.utcnow()
        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
        stock_row = _find_or_create_stock_row(
            session,
            warehouse_id=warehouse_id,
            hardware_category=hardware_category,
            product_code=product_code,
            aisle=None,
            row=None,
            bay=None,
            received_at=now,
        )
        il = InventoryLocationModel(
            project_id=project_id,
            stock_item_id=stock_row.id,
            warehouse_id=warehouse_id,
            hardware_category=hardware_category,
            product_code=product_code,
            quantity=0,
            deficient_quantity=0,
            # Every prior row for the combo is gone (that is why this one exists), so the cost is
            # re-resolved from the schedule, else the anchor stock row - the same rule allocate
            # applies. Leaving it null valued the restored units at zero.
            unit_cost=resolve_project_combo_cost(session, project_id, hardware_category, product_code)
            or stock_row.unit_cost,
            received_at=now,
        )
        session.add(il)
        session.flush()
    il.quantity += quantity
    return il


def _restock_cancelled_pull(
    session: Session,
    pr: PullRequestModel,
    needs_by_combo: dict[tuple[str, str], int],
    cancelled_by: str,
    reason: str | None,
) -> list[RestockedLine]:
    """Put a cancelled pull's hardware back, on the rows it actually came off where that is known.

    Three shapes, and which one applies is decided by evidence rather than by the pull's age:

    - **Picked under #367** (APPLIED pick lines exist): every unit goes back on the exact
      `InventoryLocation` it was taken from, one PULL_RESTOCK audit per row. The picker recorded
      where each handful came from, so there is no reason to guess - and a bin that gave up twelve
      hinges gets twelve hinges back, which is what makes a physical recount agree with the system.
    - **Picked under the old model** (`picked_at` stamped, no pick lines - the migration's backfill
      population): the per-combo return, exactly as before. The old FIFO deduction spread across
      whichever rows were oldest and kept no record, so the units land on the project's newest row
      for the combo. That is defensible because inventory is fungible
      (docs/HARDWARE_IDENTITY_LIFECYCLE.md) and conservative for future FIFO: older stock still goes
      out first.
    - **Never picked** (no `picked_at`, no applied lines): nothing is restocked, because nothing ever
      left. Cancelling here is just closing a pull the warehouse opened and did not work; any DRAFT
      lines are discarded with it, since a draft is a note about hardware, not a hold on it.
    """
    applied = [line for line in _pick_lines(session, pr.id, PullPickLineState.APPLIED) if line.quantity > 0]

    if not applied:
        if pr.picked_at is None:
            return []
        # Legacy: deducted before pick lines existed, so there is nothing to reverse row by row.
        restocked: list[RestockedLine] = []
        for (cat, code), qty in sorted(needs_by_combo.items()):
            il = _return_units_to_project_inventory(session, pr.project_id, cat, code, qty)
            restocked.append(RestockedLine(hardware_category=cat, product_code=code, quantity=qty))
            _log_audit_event(
                session,
                project_id=pr.project_id,
                entity_type=AuditEntityType.INVENTORY_LOCATION,
                entity_id=il.id,
                action=AuditAction.PULL_RESTOCK,
                performed_by=cancelled_by,
                detail={
                    "pullRequestId": str(pr.id),
                    "pullRequestNumber": pr.request_number,
                    "restockedQuantity": qty,
                    "newQuantity": il.quantity,
                    "hardwareCategory": cat,
                    "productCode": code,
                    "reasonText": reason,
                },
            )
        return restocked

    by_row: dict[tuple[str, str, uuid.UUID], int] = defaultdict(int)
    orphaned: dict[tuple[str, str], int] = defaultdict(int)
    for line in applied:
        if line.inventory_location_id is None:
            orphaned[(line.hardware_category, line.product_code)] += line.quantity
        else:
            by_row[(line.hardware_category, line.product_code, line.inventory_location_id)] += line.quantity

    totals: dict[tuple[str, str], int] = defaultdict(int)
    rows = {
        row.id: row
        for row in lock_rows(
            session,
            InventoryLocationModel,
            sorted({loc_id for (_cat, _code, loc_id) in by_row}),
        )
    }
    for (cat, code, loc_id), qty in sorted(by_row.items(), key=lambda kv: (kv[0][0], kv[0][1], str(kv[0][2]))):
        row = rows.get(loc_id)
        if row is None:
            # The FK is ON DELETE SET NULL, so this should be unreachable - but a row that has gone
            # missing another way must not swallow the units.
            orphaned[(cat, code)] += qty
            continue
        row.quantity += qty
        totals[(cat, code)] += qty
        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=row.id,
            action=AuditAction.PULL_RESTOCK,
            performed_by=cancelled_by,
            detail={
                "pullRequestId": str(pr.id),
                "pullRequestNumber": pr.request_number,
                "restockedQuantity": qty,
                "newQuantity": row.quantity,
                "hardwareCategory": cat,
                "productCode": code,
                "aisle": row.aisle,
                "row": row.row,
                "bay": row.bay,
                "returnedToSourceRow": True,
                "reasonText": reason,
            },
        )

    for (cat, code), qty in sorted(orphaned.items()):
        il = _return_units_to_project_inventory(session, pr.project_id, cat, code, qty)
        totals[(cat, code)] += qty
        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=il.id,
            action=AuditAction.PULL_RESTOCK,
            performed_by=cancelled_by,
            detail={
                "pullRequestId": str(pr.id),
                "pullRequestNumber": pr.request_number,
                "restockedQuantity": qty,
                "newQuantity": il.quantity,
                "hardwareCategory": cat,
                "productCode": code,
                "returnedToSourceRow": False,
                "reasonText": reason,
            },
        )

    session.flush()
    return [
        RestockedLine(hardware_category=cat, product_code=code, quantity=qty)
        for (cat, code), qty in sorted(totals.items())
    ]


def cancel_pull_request(
    session: Session,
    pr_id: uuid.UUID,
    cancelled_by: str,
    reason: str | None = None,
) -> CancelResult:
    """Cancel a started pull, put its hardware back on the shelf, and hand the source request back
    for re-acceptance (#343).

    Before this there was no way out of a started pull: inventory had been deducted and
    `PullRequestStatus.CANCELLED` was an enum value nothing ever set, so a pull raised against the
    wrong project or superseded by a schedule revision could only be walked forward.

    **Which statuses can be cancelled**: IN_PROGRESS only. A COMPLETED pull has handed its hardware
    over - to the bench or to a shipping desk - and v1 does not follow it past that point, so there
    is nothing left here to reverse.

    **How much comes back depends on how much went out** (#367). A fully picked pull returns
    everything, to the exact rows it was taken from; a short-picked one returns only what was picked;
    a pull cancelled before its pick returns nothing, because nothing left. See
    `_restock_cancelled_pull`.

    **The source request goes back to PENDING**, with its reservation re-created from what it will
    need on re-acceptance - its full requirement, not what happened to come back - and re-checked
    against availability first. Any claim the pull still holds is released before that, because since
    #367 a cancellable pull may still be holding one. If stock was written off or condemned in the
    meantime the re-check comes up short, and rather than write a partial claim that reads as
    covered, the request is left unreserved and flagged via `integrity_note` - the same
    honest-and-flagged shape the #342 backfill uses.
    """
    if not cancelled_by:
        raise ValidationError("cancelled_by is required", field="cancelled_by")
    reason = (reason or "").strip() or None
    if reason is not None and len(reason) > MAX_CANCELLATION_REASON_LENGTH:
        raise ValidationError(
            f"Cancellation reason must be {MAX_CANCELLATION_REASON_LENGTH} characters or fewer",
            field="reason",
        )

    locked_prs = lock_rows(session, PullRequestModel, [pr_id])
    if not locked_prs:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked_prs[0]
    if pr.deleted_at is not None:
        raise NotFoundError(f"Pull request {pr_id} not found")

    items = list(
        session.scalars(select(PullRequestItemModel).where(PullRequestItemModel.pull_request_id == pr.id)).all()
    )

    if pr.status == PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            "This pull has not been started yet, so nothing has left inventory. Reopen or reject "
            "the source request instead."
        )
    if pr.status == PullRequestStatus.CANCELLED:
        raise InvalidStateTransitionError("Pull request is already cancelled")
    if pr.status == PullRequestStatus.COMPLETED:
        raise InvalidStateTransitionError(
            "This pull is already complete and its hardware has been handed over - it can no longer be cancelled."
        )

    now = datetime.utcnow()

    # 1. Inverse inventory write.
    needs_by_combo: dict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        if item.requested_quantity <= 0:
            continue
        needs_by_combo[(item.hardware_category, item.product_code)] += item.requested_quantity

    restocked = _restock_cancelled_pull(session, pr, needs_by_combo, cancelled_by, reason)

    # 2. The pull itself.
    pr.status = PullRequestStatus.CANCELLED
    pr.cancelled_at = now
    pr.cancelled_by = cancelled_by
    pr.cancellation_reason = reason
    session.flush()

    # 3. Drop whatever claim the pull still holds, so the re-creation below cannot stack on top of it.
    #    Before #367 this was structurally impossible: approval consumed the claim whole, so a
    #    cancellable pull held nothing. Now the claim is consumed *as the pick is confirmed*, so a
    #    pull cancelled before its pick still holds all of it and one cancelled after a short pick
    #    holds the un-picked remainder. Re-creating the request's full need on top of either would
    #    double-claim the same units. Released via `find_reservation_holder` rather than the source
    #    request, because that is the one lookup that also covers a PR-REPL pull holding its own.
    holder = find_reservation_holder(session, pr)
    if holder is not None:
        reservations.release_reservations(session, holder[0], holder[1])
    # A draft is a transcription in progress, not a hold on anything - it dies with the pull.
    session.execute(
        delete(PullPickLineModel).where(
            PullPickLineModel.pull_request_id == pr.id,
            PullPickLineModel.state == PullPickLineState.DRAFT,
        )
    )

    # 4. Hand the source request back, and re-claim the hardware for it if it is still free.
    #    The availability check runs *after* the restock, so the units just returned count towards it,
    #    and `needs_by_combo` is what the request will need again on re-acceptance - not what came
    #    back, which on a short-picked pull is less.
    source_request, source_reservation = _find_source_request(session, pr)
    returned_to_pending = False
    reservations_recreated = False
    integrity_note: str | None = None
    if source_request is not None:
        returned_to_pending = _return_source_request_to_pending(session, pr, source_request)
        if needs_by_combo:
            result = check_inventory_sufficiency(
                session,
                pr.project_id,
                [(cat, code, qty) for (cat, code), qty in needs_by_combo.items()],
                lock=True,
                reservation_aware=True,
            )
            if result.sufficient:
                reservations.create_reservations(
                    session,
                    pr.project_id,
                    source_reservation,
                    source_request.id,
                    [(cat, code, qty) for (cat, code), qty in needs_by_combo.items()],
                )
                reservations_recreated = True
            else:
                short = ", ".join(
                    f"{s.hardware_category} {s.product_code} (short {s.short})" for s in result.shortfalls
                )
                integrity_note = (
                    f"Pull {pr.request_number} was cancelled and this request returned to Pending, but its "
                    f"hardware could not be re-reserved - {short}. It holds no claim on inventory, so the "
                    "pull can come up short."
                )[:500]
                source_request.integrity_note = integrity_note

    _log_audit_event(
        session,
        project_id=pr.project_id,
        entity_type=AuditEntityType.PULL_REQUEST,
        entity_id=pr.id,
        action=AuditAction.PULL_CANCELLED,
        performed_by=cancelled_by,
        detail={
            "pullRequestNumber": pr.request_number,
            "source": pr.source.value,
            "reasonText": reason,
            "restocked": [
                {"hardwareCategory": r.hardware_category, "productCode": r.product_code, "quantity": r.quantity}
                for r in restocked
            ],
            "sourceRequestId": str(source_request.id) if source_request is not None else None,
            "sourceRequestReturnedToPending": returned_to_pending,
            "reservationsRecreated": reservations_recreated,
            "integrityNote": integrity_note,
            "cancelledAt": now.isoformat(),
        },
    )

    notification_service.create_notification(
        session,
        project_id=pr.project_id,
        recipient_role=pr.requested_by,
        notification_type=NotificationType.PULL_REQUEST_CANCELLED,
        message=(
            f"Pull Request {pr.request_number} was cancelled by {cancelled_by}"
            + (f": {reason}" if reason else ".")
            + (" The hardware has been returned to inventory." if restocked else "")
        ),
        pull_request_id=pr.id,
    )

    return CancelResult(
        pull_request=pr,
        restocked=restocked,
        source_request_returned_to_pending=returned_to_pending,
        reservations_recreated=reservations_recreated,
        integrity_note=integrity_note,
    )


def _find_source_request(session: Session, pr: PullRequestModel):
    """The request this pull was minted from, and the reservation discriminator it claims under.

    The same hop `find_reservation_holder` uses, returning the row rather than its id because
    cancellation has to write to it. `(None, None)` for a legacy pull, or one whose request was
    already rejected.
    """
    if pr.source == PullRequestSource.SHOP_ASSEMBLY:
        sar = session.scalar(select(ShopAssemblyRequestModel).where(ShopAssemblyRequestModel.pull_request_id == pr.id))
        if sar is not None:
            return (sar, ReservationSource.SHOP_ASSEMBLY_REQUEST)
    elif pr.source == PullRequestSource.SHIPPING_OUT:
        sor = session.scalar(select(ShippingOutRequestModel).where(ShippingOutRequestModel.pull_request_id == pr.id))
        if sor is not None:
            return (sor, ReservationSource.SHIPPING_OUT_REQUEST)
    return (None, None)


def _return_source_request_to_pending(session: Session, pr: PullRequestModel, source_request) -> bool:
    """Undo the accept on the cancelled pull's source request so it can be re-accepted or rejected.

    Deliberately PENDING and not REJECTED: cancelling a pull says the *pull* was wrong, not that the
    hardware is no longer wanted, and the request is the record of a decision somebody made. Sending
    it back to the queue is also what gives the re-created reservation something to hang off. A
    request that is not APPROVED (already rejected, or reopened by hand while the pull was live) is
    left exactly as it is.
    """
    if isinstance(source_request, ShopAssemblyRequestModel):
        if source_request.status != ShopAssemblyRequestStatus.APPROVED:
            return False
        source_request.status = ShopAssemblyRequestStatus.PENDING
    else:
        if source_request.status != ShippingOutRequestStatus.APPROVED:
            return False
        source_request.status = ShippingOutRequestStatus.PENDING
    source_request.approved_by = None
    source_request.approved_at = None
    # Deliberately kept pointing at the now-CANCELLED pull, not nulled. That pointer is the only
    # durable record that this PENDING request reappeared on the accept board because a cancel put it
    # there (#613) - the accept queue reads it to draw the "returned to Pending" note that tells the
    # acceptor where the request came from. It is not a false "live pull": every liveness query that
    # inspects the pull's status keys off PullRequestStatus, which is CANCELLED here, and a PENDING
    # request is "live" on its own status regardless. A re-accept overwrites this column with the
    # fresh pull it mints (clearing the note); reopen is only reachable from APPROVED and nulls it.
    return True


def discard_pending_pull_request(session: Session, pr_id: uuid.UUID | None) -> None:
    """Hard-delete a still-PENDING PullRequest (and its items) that an accept minted, for the request
    reopen path (#325). Locks the PR to close the race with a concurrent approve, and refuses if it has
    advanced past PENDING - by then inventory has been deducted (or the pull completed) and reopening
    the request would leave the warehouse out of sync, so the caller is told to resolve it in the
    warehouse first. A hard delete (not the soft deleted_at) is required because request_number is
    unique: a later re-accept re-mints a PR with the same number. A null/missing PR id is a no-op (the
    accept is already effectively undone).

    The request keeps its reservations throughout - the claim belongs to the request, not to the
    pull, and reopening does not give the hardware up."""
    if pr_id is None:
        return
    locked = lock_rows(session, PullRequestModel, [pr_id])
    if not locked:
        return
    pr = locked[0]
    if pr.status != PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Cannot reopen - the warehouse has already started this pull request ({pr.status.value}). "
            "Resolve it in the warehouse first."
        )
    # Bulk-delete the items in one statement (rather than a load + per-row DELETE), then the PR itself.
    session.execute(delete(PullRequestItemModel).where(PullRequestItemModel.pull_request_id == pr.id))
    # A PENDING pull cannot have pick lines - `save_pick_draft` and `confirm_pick` both require
    # IN_PROGRESS - so this is belt and braces against a future path that lets one exist, not a live
    # case. The FK cascades on delete anyway; stating it keeps the session's identity map honest.
    session.execute(delete(PullPickLineModel).where(PullPickLineModel.pull_request_id == pr.id))
    session.delete(pr)
    session.flush()
