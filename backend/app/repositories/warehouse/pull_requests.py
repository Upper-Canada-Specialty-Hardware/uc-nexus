"""Pull requests: reads, the shared inventory-sufficiency gate, the pick flow, complete/cancel."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    NotificationType,
    OpeningItemState,
    PullPickLineState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_pick_line import PullPickLine as PullPickLineModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.shipping_out_request import ShippingOutRequest as ShippingOutRequestModel
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.shop_assembly import ShopAssemblyRequest as ShopAssemblyRequestModel
from app.models.warehouse import Warehouse as WarehouseModel
from app.services import notification_service
from app.services.locking import lock_rows

from . import reservations
from .audit import _log_audit_event

MAX_CANCELLATION_REASON_LENGTH = 500

# How many openings a "work is available" notification names before it starts counting instead
# (#344). A staging confirmation can cover a whole pull, and a bell entry listing forty openings is
# not a notification, it is a report.
_MAX_NAMED_OPENINGS_IN_MESSAGE = 5


def get_pull_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    source=None,
    status=None,
) -> list[PullRequestModel]:
    """
    Query PullRequest WHERE deleted_at IS NULL, optionally filtered by project_id.
    Optional source filter, optional status filter.
    Order by created_at ASC (FIFO — oldest first).
    Eagerly load items (PullRequestItem).
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


def _is_replacement_pull(session: Session, pr: PullRequestModel) -> bool:
    """Structural test for a PR-REPL pull: at least one line carries `sa_opening_item_id` (#339).

    Same test as `find_open_replacement_pulls`, and deliberately not the `PR-REPL-` number prefix
    - the prefix is a display convention, the FK is what makes the pull a replacement, and a
    structural test cannot be broken by renaming a request.
    """
    return bool(
        session.scalar(
            select(PullRequestItemModel.id)
            .where(
                PullRequestItemModel.pull_request_id == pr.id,
                PullRequestItemModel.sa_opening_item_id.is_not(None),
            )
            .limit(1)
        )
    )


def find_reservation_holder(session: Session, pr: PullRequestModel) -> tuple[ReservationSource, uuid.UUID] | None:
    """Whose reservations this pull is going to spend, or None if it has none (#342).

    A shop-assembly accept stamps the minted PR with the request's own `request_number` (unique on
    both tables), and a shipping-out accept stamps `pull_request_id` on the request - so each hop
    is a single indexed lookup, no string parsing. A **replacement pull holds its own claim**: there
    is no request behind a deficiency, so the pull is the holder, found structurally by its
    `sa_opening_item_id` lines rather than by its number.

    None is the honest answer for two remaining cases, and they behave identically downstream (the
    pull is checked against on-hand minus *everyone's* reservations, and consumes nothing):

    - a pull whose source request was **rejected/reopened** after the accept - the claim is gone by
      design.
    - a **legacy pull** minted before this table existed, or one created directly by a non-UI caller.

    The replacement case used to be on that list. It no longer is: a replacement reserves at the
    moment the defect is flagged (`report_deficiency_at_assembly`), so by pick time it has a
    claim to spend like anything else. The guarantee that made the old behaviour safe still holds -
    a replacement only ever reserves *free* stock, so it can no more eat another request's claim
    than it could before.
    """
    if pr.source == PullRequestSource.SHOP_ASSEMBLY:
        sar_id = session.scalar(
            select(ShopAssemblyRequestModel.id).where(ShopAssemblyRequestModel.request_number == pr.request_number)
        )
        if sar_id is not None:
            return (ReservationSource.SHOP_ASSEMBLY_REQUEST, sar_id)
        if _is_replacement_pull(session, pr):
            return (ReservationSource.REPLACEMENT_PULL, pr.id)
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
class PickSheetLeaf:
    """One door leaf a section's units are owed to. Every leaf is listed, never summarised: the
    picker is building carts per leaf, and "and 6 more" is exactly the information they need."""

    opening_number: str
    leaf: int | None
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


@dataclass(frozen=True)
class PickSheetSection:
    """One product code to pick, with everywhere it can come from and every leaf it is owed to."""

    hardware_category: str
    product_code: str
    required_quantity: int
    applied_quantity: int
    leaves: list[PickSheetLeaf]
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
class PickSheetFetchItem:
    """One assembled leaf to fetch off the rack (#367).

    An OPENING_ITEM line moves a leaf that was already tagged at shop assembly, so its hardware left
    fungible inventory then and there is nothing here to deduct - only to walk over and collect. The
    check-off is persisted so it survives a reload or a shift change."""

    pull_request_item_id: uuid.UUID
    opening_item_id: uuid.UUID | None
    opening_number: str
    leaf: int | None
    aisle: str | None
    row: str | None
    bay: str | None
    state: OpeningItemState | None
    fetched_at: datetime | None
    fetched_by: str | None


@dataclass(frozen=True)
class PickSheet:
    pull_request: PullRequestModel
    sections: list[PickSheetSection]
    fetch_items: list[PickSheetFetchItem]


def _loose_requirements(pr: PullRequestModel) -> dict[tuple[str, str], int]:
    """What the pull's LOOSE lines add up to, per combo. The pick's denominator."""
    required: dict[tuple[str, str], int] = defaultdict(int)
    for item in pr.items:
        if item.item_type != PullRequestItemType.LOOSE:
            continue
        if not item.hardware_category or not item.product_code or item.requested_quantity <= 0:
            continue
        required[(item.hardware_category, item.product_code)] += item.requested_quantity
    return dict(required)


def outstanding_loose_needs(session: Session, pr: PullRequestModel) -> dict[tuple[str, str], int]:
    """What a pull still has to pick, per combo: what it asked for minus what it has already picked.

    Identical to `_loose_requirements` for any pull that has picked nothing, which is every pull that
    has not been started. It differs only for a **short-picked** one (#367), and that difference is
    what keeps the replacement loop honest: topping a part-filled pull's claim back up to its
    original requirement would re-claim units it already has on a cart, and asking whether the
    original requirement is now coverable would keep answering no long after the gap had closed.

    Combos that are fully picked drop out entirely rather than appearing as zero.
    """
    already = _applied_by_combo(session, pr.id)
    outstanding = {}
    for combo, total in _loose_requirements(pr).items():
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
    combo at once, the assembled leaves behind the OPENING_ITEM lines, and two more for the
    claimable-quantity arithmetic (the holder lookup and one grouped aggregate over reservations).

    A location is a candidate when it still has available units **or** when this pull has already
    named it. The second half matters: a row picked down to zero must stay on the sheet, or the row
    the picker took twelve units off vanishes the moment they confirm and the sheet stops matching
    the paper in their hand.
    """
    pr = get_pull_request_details(session, pr_id)

    required = _loose_requirements(pr)
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

    # Leaves per combo, in the order the carts are laid out.
    leaves_by_combo: dict[tuple[str, str], list[PickSheetLeaf]] = defaultdict(list)
    for item in pr.items:
        if item.item_type != PullRequestItemType.LOOSE:
            continue
        if not item.hardware_category or not item.product_code or item.requested_quantity <= 0:
            continue
        leaves_by_combo[(item.hardware_category, item.product_code)].append(
            PickSheetLeaf(
                opening_number=item.opening_number,
                leaf=item.leaf,
                quantity=item.requested_quantity,
            )
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
            select(InventoryLocationModel, WarehouseModel.code)
            .outerjoin(WarehouseModel, WarehouseModel.id == InventoryLocationModel.warehouse_id)
            .where(
                InventoryLocationModel.project_id == pr.project_id,
                combo_clause,
                visibility,
            )
            .order_by(InventoryLocationModel.received_at.asc(), InventoryLocationModel.id.asc())
        ).all()
        for il, warehouse_code in rows:
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
            leaves=sorted(
                leaves_by_combo.get((cat, code), []),
                key=lambda leaf: (leaf.opening_number or "", leaf.leaf if leaf.leaf is not None else -1),
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

    fetch_lines = [
        item
        for item in pr.items
        if item.item_type == PullRequestItemType.OPENING_ITEM and item.opening_item_id is not None
    ]
    opening_items: dict[uuid.UUID, OpeningItemModel] = {}
    if fetch_lines:
        opening_items = {
            oi.id: oi
            for oi in session.scalars(
                select(OpeningItemModel).where(OpeningItemModel.id.in_([item.opening_item_id for item in fetch_lines]))
            ).all()
        }
    fetch_items = [
        PickSheetFetchItem(
            pull_request_item_id=item.id,
            opening_item_id=item.opening_item_id,
            opening_number=item.opening_number,
            leaf=item.leaf,
            aisle=oi.aisle if (oi := opening_items.get(item.opening_item_id)) is not None else None,
            row=oi.row if oi is not None else None,
            bay=oi.bay if oi is not None else None,
            state=oi.state if oi is not None else None,
            fetched_at=item.fetched_at,
            fetched_by=item.fetched_by,
        )
        for item in fetch_lines
    ]
    fetch_items.sort(key=lambda f: (f.opening_number or "", f.leaf if f.leaf is not None else -1))

    return PickSheet(pull_request=pr, sections=sections, fetch_items=fetch_items)


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
    required = _loose_requirements(pr)
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
    required = _loose_requirements(pr)
    entered = _normalise_pick_lines(lines, required)
    already = _applied_by_combo(session, pr.id)
    now = datetime.utcnow()

    # A confirmation with nothing entered is only meaningful on a pure fetch pull, where there is
    # genuinely nothing to deduct. On a pull with loose lines it would deduct nothing, report the
    # whole requirement as short, and raise a PO backfill signal for a walk nobody took - and then
    # `has_unread_notification_for_pull` would suppress the *real* signal from the pick that
    # follows. Refused rather than treated as a short pick.
    if required and not entered:
        raise ValidationError(
            "Nothing was entered. Record what came off each location before confirming, or cancel "
            "the pull if none of it can be picked.",
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
        )

    # An *integrity* signal, so it must fire only for a pull that genuinely held a claim for
    # everything it is asking for. Having a source request is not the same as holding reservations:
    # the #342 backfill deliberately left the whole pre-existing in-flight population unreserved and
    # flagged rather than inventing claims for it, and a cancel that could not re-reserve leaves a
    # live request in the same state. Those are the *expected* shortfall population - flagging every
    # one of them is exactly how a real discrepancy gets missed.
    #
    # A replacement pull is expected-shortfall by design and is excluded outright: it reserves
    # `min(free stock, condemned)` at flag time, so being partly covered is its normal resting state.
    reserved_path = holder is not None and holder[0] is not ReservationSource.REPLACEMENT_PULL
    if reserved_path and reservations.get_reserved_total(session, holder[0], holder[1]) > 0:
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


def set_pull_item_fetched(
    session: Session,
    item_id: uuid.UUID,
    fetched: bool,
    fetched_by: str,
) -> PullRequestItemModel:
    """Tick (or untick) one assembled leaf off the fetch list (#367).

    Only on an OPENING_ITEM line of a pull that is being picked. A LOOSE line has a quantity, not a
    check-off, and a pull that is finished or cancelled is not being fetched from any more - both
    are refused rather than silently ignored, because a client offering the control on either is a
    bug worth surfacing.

    Unticking is supported deliberately: a picker who ticked the wrong leaf must be able to say so,
    and nothing about a check-off is irreversible - no stock moves here.
    """
    item = session.get(PullRequestItemModel, item_id)
    if item is None:
        raise NotFoundError(f"Pull request item {item_id} not found")
    if item.item_type != PullRequestItemType.OPENING_ITEM:
        raise ValidationError(
            "Only assembled-leaf lines are fetched; loose hardware is picked by quantity.",
            field="itemId",
        )
    locked = lock_rows(session, PullRequestModel, [item.pull_request_id])
    if not locked:
        raise NotFoundError(f"Pull request {item.pull_request_id} not found")
    pr = locked[0]
    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(f"Pull request must be In_Progress to record fetches, got {pr.status.value}")

    if fetched:
        item.fetched_at = datetime.utcnow()
        item.fetched_by = fetched_by
    else:
        item.fetched_at = None
        item.fetched_by = None
    session.flush()
    return item


def _apply_replacement_arrivals(session: Session, pr: PullRequestModel) -> None:
    """Give a door leaf its expectation back when the replacement hardware for a deficient unit
    actually arrives (#341).

    A PR-REPL pull line carries `sa_opening_item_id` (#339), so completing the pull can find the
    exact checklist line the unit is owed to. Until now nothing did: the PR-REPL pull is a
    SHOP_ASSEMBLY pull with no ShopAssemblyOpenings hanging off it, so its completion flipped nothing
    and the replacement dead-ended in inventory.

    Per line, the arrived quantity is floored at what is genuinely still outstanding
    (`deficient_quantity`), so an over-delivery - a warehouse operator pulling 3 against a 2-unit
    line, or a duplicate line - cannot drive the counter negative or breach the progress constraint.
    Where the freed unit lands depends on whether the leaf is still on the bench:

    - PENDING / IN_PROGRESS: nowhere. `deficient_quantity` simply drops, so
      `remaining = quantity - installed - deficient` goes back up and the unit reappears as work in
      My Work. Completion stays blocked until the assembler actually fits it, which is the point.
    - COMPLETED: the unit moves into `replacement_pending_quantity`. Lowering `deficient_quantity`
      alone would make a finished leaf read as un-dispositioned (installed + deficient < quantity)
      and corrupt the completion invariant; moving it keeps the sum at `quantity` while recording
      that a known unit of work is outstanding on an otherwise-complete leaf.

    If that completed leaf has already SHIPPED_OUT, the replacement cannot be fitted to it at all.
    The pending state is still recorded (so the unit stays queryable rather than silently stranded)
    and a notification is raised for the reallocation / site-shipment world to pick up.
    """
    # Local import: shop_assembly_repository imports this package's aggregate at call time, so a
    # module-level import here would close the cycle.
    from app.models.shop_assembly import ShopAssemblyOpeningItem as SAOpeningItemModel
    from app.repositories import shop_assembly_repository

    by_item: dict[uuid.UUID, int] = defaultdict(int)
    for line in pr.items:
        if line.sa_opening_item_id is not None:
            by_item[line.sa_opening_item_id] += line.requested_quantity
    if not by_item:
        return

    # Lock the owning work units before touching their checklist lines. `deficient_quantity` /
    # `replacement_pending_quantity` are guarded by the ShopAssemblyOpening lock everywhere else -
    # `record_assembly_progress`, `complete_opening` and `install_replacement` all take it - and
    # writing them from here without it is a lost update against a concurrent install, or a breach of
    # the `installed + deficient + replacement_pending <= quantity` constraint. The opening ids come
    # from an id-only pass so the lock is taken *before* the rows it protects are read.
    opening_ids = set(
        session.scalars(
            select(SAOpeningItemModel.shop_assembly_opening_id).where(SAOpeningItemModel.id.in_(by_item.keys()))
        ).all()
    )
    if not opening_ids:
        return
    openings = {o.id: o for o in lock_rows(session, ShopAssemblyOpening, sorted(opening_ids))}

    items = list(
        session.scalars(
            select(SAOpeningItemModel)
            .where(SAOpeningItemModel.id.in_(by_item.keys()))
            .execution_options(populate_existing=True)
        ).all()
    )
    if not items:
        return

    for item in items:
        arrived = by_item[item.id]
        # Floor at what is actually outstanding: over-delivery restores nothing extra.
        restored = min(arrived, item.deficient_quantity)
        if restored <= 0:
            continue
        opening = openings.get(item.shop_assembly_opening_id)
        if opening is None:
            continue

        item.deficient_quantity -= restored
        leaf_completed = opening.assembly_status == AssemblyStatus.COMPLETED
        opening_item = None
        leaf_label = f"Opening {opening.opening_number}"
        if opening.leaf is not None:
            leaf_label += f" Leaf {opening.leaf}"
        shipped = False
        if leaf_completed:
            item.replacement_pending_quantity += restored
            opening_item = shop_assembly_repository.find_assembled_leaf(
                session, pr.project_id, opening.opening_id, opening.leaf
            )
            shipped = opening_item is not None and opening_item.state == OpeningItemState.SHIPPED_OUT
            if shipped:
                notification_service.create_notification(
                    session,
                    project_id=pr.project_id,
                    recipient_role=notification_service.SHIPPING_RECIPIENT_ROLE,
                    notification_type=NotificationType.REPLACEMENT_AFTER_SHIPMENT,
                    message=(
                        f"{restored} x {item.product_code} replacement arrived on {pr.request_number} for "
                        f"{leaf_label}, which has already shipped. Route it through reallocation or a "
                        f"site shipment."
                    ),
                    pull_request_id=pr.id,
                )

        # The ordinary case, which #341 left silent (#344). The shipped branch above told *shipping*
        # that a leaf that had left the building was owed something; nothing told the person actually
        # holding the leaf that the hardware they were waiting for had turned up. Addressed to the
        # assembler's stable Clerk user id - the ShopAssemblyOpening keeps the assignment it was
        # completed under, so on a finished leaf this is exactly who owns the replacement install.
        #
        # Skipped when nobody is holding the opening: an unassigned leaf's replacement is picked up
        # by whoever claims it, and a notification with no addressee is noise. It is also skipped for
        # the shipped case, which is not this person's problem any more.
        if not shipped and opening.assigned_to_user_id:
            where_it_lands = (
                "It is waiting as a replacement install on the finished leaf."
                if leaf_completed
                else "It is back on the leaf's checklist as remaining work."
            )
            notification_service.create_notification(
                session,
                project_id=pr.project_id,
                recipient_role=opening.assigned_to_user_id,
                notification_type=NotificationType.REPLACEMENT_ARRIVED,
                message=(
                    f"{restored} x {item.product_code} replacement arrived on {pr.request_number} for "
                    f"{leaf_label}. {where_it_lands}"
                ),
                pull_request_id=pr.id,
            )

        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.SHOP_ASSEMBLY_OPENING,
            entity_id=opening.id,
            action=AuditAction.REPLACEMENT_RECEIVED,
            performed_by=pr.assigned_to or pr.requested_by or "Warehouse",
            detail={
                "pullRequestNumber": pr.request_number,
                "shopAssemblyOpeningItemId": str(item.id),
                "hardwareCategory": item.hardware_category,
                "productCode": item.product_code,
                "arrivedQuantity": arrived,
                "restoredQuantity": restored,
                "deficientQuantity": item.deficient_quantity,
                "replacementPendingQuantity": item.replacement_pending_quantity,
                "openingNumber": opening.opening_number,
                "leaf": opening.leaf,
                "assemblyStatus": opening.assembly_status.value,
                "openingItemId": str(opening_item.id) if opening_item is not None else None,
                "openingItemState": opening_item.state.value if opening_item is not None else None,
            },
        )


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
    """
    Complete a pull request:
    1. Validate status == In_Progress and the pick has been confirmed (#367)
    2. Set status=Completed, completed_at=now()
    3. Create notification
    4. Restore any leaf expectations the pull's replacement lines are owed to (#341)
    5. If Shipping_Out source: set Opening_Item states to Ship_Ready
    6. If Shop_Assembly source: update SAR openings pull_status to Pulled

    Since #343 a shop-assembly pull is normally *completed by its last staging* - `stage_pull_openings`
    calls straight into here once every opening is staged, so the notification and the replacement
    arrivals still fire exactly once, from one place. Calling it directly stays supported and means
    "stage whatever is left and close the pull": step 6 flips any remaining opening to PULLED and
    stamps its staging, which is a no-op for openings already staged individually.
    """
    # Take the pull's row lock before reading its status. Completion has two entry points since
    # #343 - the explicit "mark pulled" action and the last staging confirmation - so two callers can
    # arrive at an IN_PROGRESS pull at once, both pass the status check, and both run the completion
    # side effects: two PULL_REQUEST_COMPLETED notifications, and `_apply_replacement_arrivals`
    # applied twice. Re-locking inside `stage_pull_openings`' transaction (which already holds this
    # row) is a no-op.
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

    # Replacement lines (#341) are keyed on the checklist line they are owed to, not on the PR's
    # source, so this runs before the source dispatch below. A PR-REPL pull is a SHOP_ASSEMBLY pull
    # with nothing hanging off it, which is why the SHOP_ASSEMBLY branch alone left it a no-op.
    _apply_replacement_arrivals(session, pr)

    # Source-specific side effects
    if pr.source == PullRequestSource.SHIPPING_OUT:
        # For each Opening_Item item, set the OpeningItem state to Ship_Ready.
        # Only from IN_INVENTORY (#335): a leaf that already shipped must not be walked back to
        # SHIP_READY by a duplicate or stale line, because get_ship_ready_items would list it again
        # and confirm_shipment's SHIP_READY check would pass, shipping one physical leaf twice.
        for item in pr.items:
            if item.item_type == PullRequestItemType.OPENING_ITEM and item.opening_item_id is not None:
                oi = session.get(OpeningItemModel, item.opening_item_id)
                if oi is not None and oi.state == OpeningItemState.IN_INVENTORY:
                    oi.state = OpeningItemState.SHIP_READY

    elif pr.source == PullRequestSource.SHOP_ASSEMBLY:
        # Openings hang off this PR directly (#222) - no PR-number string parsing.
        openings = session.scalars(
            select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id)
        ).all()
        flipped: list[ShopAssemblyOpening] = []
        for opening in openings:
            # Idempotent for an opening already staged individually (#343): its own staged_at/by
            # stamp is the truth about when that cart was built and must not be overwritten by the
            # moment the *last* cart happened to be finished.
            if opening.pull_status == PullStatus.PULLED:
                continue
            opening.pull_status = PullStatus.PULLED
            opening.staged_at = now
            opening.staged_by = completed_by or pr.assigned_to or pr.requested_by
            flipped.append(opening)
        # Only the openings this call actually made workable (#344). That set is empty when staging
        # completed the pull - `stage_pull_openings` has already flipped every one of them and raised
        # its own notification - so the manager audience gets exactly one signal per real event, with
        # no dedupe logic needed anywhere: the fact that governs is "did anything become workable
        # here", and it is already computed.
        notify_assembly_work_available(session, pr, flipped, completed_pull=True)

    return pr


def notify_assembly_work_available(
    session: Session,
    pr: PullRequestModel,
    openings: list[ShopAssemblyOpening],
    *,
    completed_pull: bool,
) -> None:
    """Tell the shop-assembly manager audience that openings just became workable (#344).

    Before this, a cart staged at 9am (#343) made its opening assignable immediately and nothing said
    so - the assignment board found out when somebody happened to reload it, which is the same
    problem per-opening staging was meant to solve one layer down.

    One notification per *confirmation*, not per opening: the warehouse stages a batch of carts in
    one action, and N rows in the bell for one trip to the shelf is how a bell stops being read. The
    openings are named up to a limit and then counted, so the message stays a message.

    A no-op when nothing became workable, which is what keeps `complete_pull_request` from
    double-announcing a pull that `stage_pull_openings` has already finished.
    """
    if not openings:
        return
    labels = sorted(f"{o.opening_number}" + (f" leaf {o.leaf}" if o.leaf is not None else "") for o in openings)
    shown = ", ".join(labels[:_MAX_NAMED_OPENINGS_IN_MESSAGE])
    if len(labels) > _MAX_NAMED_OPENINGS_IN_MESSAGE:
        shown += f" and {len(labels) - _MAX_NAMED_OPENINGS_IN_MESSAGE} more"
    tail = " That was the last of the pull." if completed_pull else " The rest of the pull is still being picked."
    notification_service.create_notification(
        session,
        project_id=pr.project_id,
        recipient_role=notification_service.SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE,
        notification_type=NotificationType.ASSEMBLY_WORK_AVAILABLE,
        message=(
            f"{len(labels)} opening(s) on Pull Request {pr.request_number} are staged and ready to "
            f"assemble: {shown}.{tail}"
        ),
        pull_request_id=pr.id,
    )


# ---------------------------------------------------------------------------
# Per-opening staging (#343)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StagingSummary:
    """How far along a shop-assembly pull's staging is, derived - never stored.

    `status` is a `PullStatus` read over the *set* of openings: NOT_PULLED when none is staged,
    PARTIAL when some are, PULLED when all are. That is the reading the dead `PullStatus.PARTIAL`
    value was always for, and deriving it is what keeps the persisted state machine honest: the
    opening column stays a two-valued fact about one cart, and `PullRequestStatus` stays
    PENDING -> IN_PROGRESS -> COMPLETED/CANCELLED with no half-state wedged into it. A pull whose
    every opening is staged *is* COMPLETED, so PULLED here is never observed without it.
    """

    staged_opening_count: int
    total_opening_count: int

    @property
    def status(self) -> PullStatus:
        if self.staged_opening_count == 0:
            return PullStatus.NOT_PULLED
        if self.staged_opening_count >= self.total_opening_count:
            return PullStatus.PULLED
        return PullStatus.PARTIAL


def get_pull_staging_summaries(session: Session, pr_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, StagingSummary]:
    """Staged/total opening counts per pull, for every pull id given, in **one grouped aggregate**.

    The pull-request list resolver renders a staging chip per row, so this must never become a
    per-row query (CLAUDE.md perf rules) - it is `count(*)` and a filtered `count(*)`, grouped by
    pull, not a `len()` over loaded openings. Pulls with no openings at all (shipping-out, PR-REPL,
    legacy) are simply absent from the result: staging does not apply to them, and a caller must
    render nothing rather than "0 of 0 staged".
    """
    ids = [pid for pid in pr_ids if pid is not None]
    if not ids:
        return {}
    staged = func.count(1).filter(ShopAssemblyOpening.pull_status == PullStatus.PULLED)
    rows = session.execute(
        select(
            ShopAssemblyOpening.pull_request_id,
            func.count(1).label("total"),
            staged.label("staged"),
        )
        .where(ShopAssemblyOpening.pull_request_id.in_(ids))
        .group_by(ShopAssemblyOpening.pull_request_id)
    ).all()
    return {
        row.pull_request_id: StagingSummary(staged_opening_count=int(row.staged), total_opening_count=int(row.total))
        for row in rows
    }


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


def get_pull_request_openings(session: Session, pr_id: uuid.UUID) -> list[ShopAssemblyOpening]:
    """The shop-assembly openings a pull covers, items eager-loaded, for the staging checklist (#343).

    Ordered by opening number then leaf so the checklist reads the way the carts are laid out.
    Empty for a shipping-out pull, a PR-REPL replacement pull, or a legacy pull.
    """
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.pull_request_id == pr_id)
        .order_by(ShopAssemblyOpening.opening_number.asc(), ShopAssemblyOpening.leaf.asc())
    )
    return list(session.scalars(stmt).unique().all())


@dataclass
class StageResult:
    """Outcome of one staging confirmation."""

    pull_request: PullRequestModel
    openings: list[ShopAssemblyOpening]
    newly_staged_ids: list[uuid.UUID]
    summary: StagingSummary
    completed: bool


def stage_pull_openings(
    session: Session,
    pr_id: uuid.UUID,
    opening_ids: Iterable[uuid.UUID],
    staged_by: str,
) -> StageResult:
    """Confirm that the cart(s) for these openings of a picked shop-assembly pull are built (#343).

    The warehouse stages a pull opening by opening; before this, `pull_status` was flipped for every
    opening at once when the whole pull was marked pulled, so an opening picked first thing in the
    morning was not assignable until the last one was picked. Each confirmed opening flips to PULLED
    on its own and becomes assignable and workable immediately - `assign_openings`,
    `record_assembly_progress` and `complete_opening` all gate on the opening's own `pull_status`,
    so nothing else has to change for the assembly floor to see it.

    **Nothing moves in inventory here.** The deduction and the consumption of the source request's
    reservation both happen at the pick confirmation and stay there (see `confirm_pick`). That is the
    moment the pull is committed: the reservation the request has held since creation becomes the
    deduction, atomically, under one set of row locks. Deducting per opening instead would mean a
    picked-but-unstaged opening held neither a reservation nor a deduction - its hardware would read
    as free and could be claimed by the next request, which is the exact hole #342 closed - and it
    would reintroduce a shortfall at staging time, where the only recovery is a half-deducted pull.
    Staging is progress tracking; `cancel_pull_request` is what reverses stock.

    Which is also why staging is gated on `picked_at` (#367). Approval no longer moves anything, so
    without that gate a cart could be declared built - and its opening handed to the assembly floor -
    off hardware still sitting on the shelf.

    Staging the last opening completes the pull, by calling `complete_pull_request` rather than
    reimplementing it, so the completion notification and the replacement-arrival application fire
    exactly once and from one place. Already-staged openings are skipped rather than refused, so a
    double-click or a stale checklist is a no-op instead of an error.
    """
    ids = list(dict.fromkeys(opening_ids))
    if not ids:
        raise ValidationError("opening_ids must not be empty", field="opening_ids")

    locked_prs = lock_rows(session, PullRequestModel, [pr_id])
    if not locked_prs:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked_prs[0]

    if pr.source != PullRequestSource.SHOP_ASSEMBLY:
        raise InvalidStateTransitionError(
            "Per-opening staging applies to shop-assembly pulls only - a shipping-out pull is completed as a whole."
        )
    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(f"Pull request must be In_Progress to stage openings, got {pr.status.value}")
    _require_picked(pr, "stage")

    openings = lock_rows(session, ShopAssemblyOpening, ids)
    by_id = {o.id: o for o in openings}
    missing = [str(oid) for oid in ids if oid not in by_id]
    if missing:
        raise NotFoundError(f"ShopAssemblyOpenings not found: {missing}")
    foreign = [str(o.id) for o in openings if o.pull_request_id != pr.id]
    if foreign:
        raise ValidationError(
            f"Openings do not belong to pull request {pr.request_number}: {foreign}",
            field="opening_ids",
        )

    now = datetime.utcnow()
    newly_staged: list[uuid.UUID] = []
    for opening in openings:
        if opening.pull_status == PullStatus.PULLED:
            continue
        opening.pull_status = PullStatus.PULLED
        opening.staged_at = now
        opening.staged_by = staged_by
        newly_staged.append(opening.id)
        _log_audit_event(
            session,
            project_id=pr.project_id,
            entity_type=AuditEntityType.SHOP_ASSEMBLY_OPENING,
            entity_id=opening.id,
            action=AuditAction.PULL_STAGED,
            performed_by=staged_by,
            detail={
                "pullRequestId": str(pr.id),
                "pullRequestNumber": pr.request_number,
                "openingNumber": opening.opening_number,
                "leaf": opening.leaf,
                "stagedAt": now.isoformat(),
            },
        )
    session.flush()

    summary = get_pull_staging_summaries(session, [pr.id]).get(
        pr.id, StagingSummary(staged_opening_count=0, total_opening_count=0)
    )
    completed = summary.total_opening_count > 0 and summary.staged_opening_count >= summary.total_opening_count
    if completed:
        complete_pull_request(session, pr.id, completed_by=staged_by)

    # Raised here rather than inside the loop so a batch confirmation is one signal (#344), and after
    # the completion call so `completed_pull` is a fact and not a prediction. `complete_pull_request`
    # finds nothing left to flip in this path, so it stays silent and there is no double-announce.
    notify_assembly_work_available(
        session,
        pr,
        [o for o in openings if o.id in set(newly_staged)],
        completed_pull=completed,
    )

    return StageResult(
        pull_request=pr,
        openings=openings,
        newly_staged_ids=newly_staged,
        summary=summary,
        completed=completed,
    )


# ---------------------------------------------------------------------------
# Cancel / restock (#343)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CancelBlocker:
    """One opening that stops a pull being cancelled: work has already started on its leaf."""

    opening_id: uuid.UUID
    opening_number: str
    leaf: int | None
    assembly_status: str
    assigned_to: str | None

    @property
    def label(self) -> str:
        leaf_suffix = f" leaf {self.leaf}" if self.leaf is not None else ""
        holder = f", {self.assigned_to}" if self.assigned_to else ""
        return f"{self.opening_number}{leaf_suffix} ({self.assembly_status.lower().replace('_', ' ')}{holder})"


@dataclass(frozen=True)
class RestockedLine:
    hardware_category: str
    product_code: str
    quantity: int


@dataclass
class CancelResult:
    pull_request: PullRequestModel
    restocked: list[RestockedLine]
    released_opening_ids: list[uuid.UUID]
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
    row for the combo, exactly the way `report_deficiency_at_assembly` returns a condemned unit, and
    a row is re-materialized if a schedule re-upload deleted the last one. Landing on the *newest*
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

    **All-or-nothing, per pull.** Partial cancellation - keeping the worked openings and releasing
    the rest - is deliberately not supported, because there is nowhere honest to put the released
    ones: `PullStatus` has no cancelled value, and `complete_pull_request` flips *every* opening of a
    pull to PULLED, so a half-cancelled pull would resurrect its released openings the moment the
    rest was staged. Expressing it properly needs an opening-level cancelled state, which is a
    different change; until then the refusal names the blockers so the warehouse knows exactly what
    to finish first.

    **What blocks it**: any opening whose assembly has started (IN_PROGRESS) or finished (COMPLETED).
    That is where the hardware stops being retrievable - it is on a leaf, and some of it may already
    have been condemned and replaced. Everything short of that is cancellable, *including openings
    already staged*: their hardware is on a cart in the shop, which is exactly as retrievable as
    hardware still on the shelf, and restocking only the un-staged part would leave the staged part
    deducted with no leaf to show for it. Assignments on released openings are cleared, because there
    is no longer any work to hold.

    **Which statuses can be cancelled**: IN_PROGRESS always. A COMPLETED pull additionally, but only
    when it is a shop-assembly pull with openings - since staging is per opening, "completed" there
    now means no more than "every cart is built", which is not a point of no return. A completed
    shipping-out pull has already flipped its leaves to SHIP_READY and a completed PR-REPL pull has
    already given leaves their expectation back; unwinding those is not this function's job.

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

    **A PR-REPL replacement pull has no source request**, so cancelling one restocks and re-creates
    nothing. It does hold a claim of its own (minted when the defect was flagged); that claim is
    released here, whether it was consumed by a pick or never spent at all. The leaf's
    `deficient_quantity` is untouched and the expectation stays on the checklist line; the
    replacement simply has to be requested again. A **PENDING** replacement pull is not cancelled but
    discarded, and that path releases too.
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
    # Lock the openings, do not merely read them. The blocker check below is what makes cancellation
    # all-or-nothing, and every other mutator of these rows (`stage_pull_openings`, `assign_openings`,
    # `record_assembly_progress`, `complete_opening`) takes this lock first. Reading them unlocked let
    # a concurrent `complete_opening` slip between the check and the release: its hardware would end
    # up both on a finished leaf and back on the shelf, and the opening would be left COMPLETED with
    # `pull_request_id` NULL. Lock order is pull-then-openings, the same order `stage_pull_openings`
    # takes them in, so this introduces no new cycle.
    opening_ids = list(
        session.scalars(select(ShopAssemblyOpening.id).where(ShopAssemblyOpening.pull_request_id == pr.id)).all()
    )
    openings = sorted(
        lock_rows(session, ShopAssemblyOpening, opening_ids),
        key=lambda o: (o.opening_number or "", o.leaf if o.leaf is not None else -1),
    )

    cancellable_from_completed = pr.source == PullRequestSource.SHOP_ASSEMBLY and bool(openings)
    if pr.status == PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            "This pull has not been started yet, so nothing has left inventory. Reopen or reject "
            "the source request instead."
        )
    if pr.status == PullRequestStatus.CANCELLED:
        raise InvalidStateTransitionError("Pull request is already cancelled")
    if pr.status == PullRequestStatus.COMPLETED and not cancellable_from_completed:
        raise InvalidStateTransitionError(
            "This pull is already complete and its hardware has been handed over - it can no longer be cancelled."
        )

    blockers = [
        CancelBlocker(
            opening_id=o.id,
            opening_number=o.opening_number,
            leaf=o.leaf,
            assembly_status=o.assembly_status.value,
            assigned_to=o.assigned_to,
        )
        for o in openings
        if o.assembly_status != AssemblyStatus.PENDING
    ]
    if blockers:
        raise ConflictError(
            "Cannot cancel this pull - assembly has already started on "
            f"{len(blockers)} of its openings: {', '.join(b.label for b in blockers)}. "
            "Finish or unwind that work first; cancelling is all-or-nothing.",
            field="opening_ids",
        )

    now = datetime.utcnow()

    # 1. Inverse inventory write. Only LOOSE lines ever left inventory; an OPENING_ITEM line moves an
    #    assembled leaf, which the pick only fetches.
    needs_by_combo: dict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        if item.item_type != PullRequestItemType.LOOSE:
            continue
        if not item.hardware_category or not item.product_code or item.requested_quantity <= 0:
            continue
        needs_by_combo[(item.hardware_category, item.product_code)] += item.requested_quantity

    restocked = _restock_cancelled_pull(session, pr, needs_by_combo, cancelled_by, reason)

    # 2. Release the openings: back to NOT_PULLED, unstaged, unassigned, and off the cancelled pull so
    #    a re-accept re-links them the way the accept path already does.
    released_ids: list[uuid.UUID] = []
    for opening in openings:
        opening.pull_status = PullStatus.NOT_PULLED
        opening.staged_at = None
        opening.staged_by = None
        opening.assigned_to = None
        opening.assigned_to_user_id = None
        opening.pull_request_id = None
        released_ids.append(opening.id)

    # 3. The pull itself.
    pr.status = PullRequestStatus.CANCELLED
    pr.cancelled_at = now
    pr.cancelled_by = cancelled_by
    pr.cancellation_reason = reason
    session.flush()

    # 4. Drop whatever claim the pull still holds, so the re-creation below cannot stack on top of it.
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

    # 5. Hand the source request back, and re-claim the hardware for it if it is still free.
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
            "releasedOpeningIds": [str(oid) for oid in released_ids],
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
        released_opening_ids=released_ids,
        source_request_returned_to_pending=returned_to_pending,
        reservations_recreated=reservations_recreated,
        integrity_note=integrity_note,
    )


def _find_source_request(session: Session, pr: PullRequestModel):
    """The request this pull was minted from, and the reservation discriminator it claims under.

    The same two hops `find_reservation_holder` uses, returning the row rather than its id because
    cancellation has to write to it. `(None, None)` for a PR-REPL replacement pull (its
    `PR-REPL-...` number matches no request), a legacy pull, or one whose request was already
    rejected.
    """
    if pr.source == PullRequestSource.SHOP_ASSEMBLY:
        sar = session.scalar(
            select(ShopAssemblyRequestModel).where(ShopAssemblyRequestModel.request_number == pr.request_number)
        )
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
    if pr.source == PullRequestSource.SHIPPING_OUT:
        # A shipping-out request's only link to its pull is this column, and the pull it points at is
        # dead. Clearing it is what lets a re-accept mint a fresh one (and keeps `reopenable_only`
        # and the re-upload liveness queries from resolving through a cancelled pull).
        source_request.pull_request_id = None
    return True


def discard_pending_pull_request(session: Session, pr_id: uuid.UUID | None) -> None:
    """Hard-delete a still-PENDING PullRequest (and its items) that an accept minted, for the request
    reopen path (#325). Locks the PR to close the race with a concurrent approve, and refuses if it has
    advanced past PENDING - by then inventory has been deducted (or the pull completed) and reopening
    the request would leave the warehouse out of sync, so the caller is told to resolve it in the
    warehouse first. A hard delete (not the soft deleted_at) is required because request_number is
    unique: a later re-accept re-mints a PR with the same number. A null/missing PR id is a no-op (the
    accept is already effectively undone).

    The REPLACEMENT_PULL release below is **defence, not a live path**. Both callers reopen a
    shop-assembly or shipping-out request, so the pull they hand over always has a source request and
    is never a PR-REPL; a replacement pull holding a claim has no discard route today, and holding it
    until approval is the intended behaviour - the replacement is genuinely owed that stock. It is
    written anyway because the alternative, should a discard path ever be added, is a claim stranded
    with nothing left that could spend or release it. (The FK cascade would take the rows on delete;
    releasing explicitly keeps the session's identity map honest and states the intent.)"""
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
    reservations.release_reservations(session, ReservationSource.REPLACEMENT_PULL, pr.id)
    # Bulk-delete the items in one statement (rather than a load + per-row DELETE), then the PR itself.
    session.execute(delete(PullRequestItemModel).where(PullRequestItemModel.pull_request_id == pr.id))
    # A PENDING pull cannot have pick lines - `save_pick_draft` and `confirm_pick` both require
    # IN_PROGRESS - so this is belt and braces against a future path that lets one exist, not a live
    # case. The FK cascades on delete anyway; stating it keeps the session's identity map honest.
    session.execute(delete(PullPickLineModel).where(PullPickLineModel.pull_request_id == pr.id))
    session.delete(pr)
    session.flush()
