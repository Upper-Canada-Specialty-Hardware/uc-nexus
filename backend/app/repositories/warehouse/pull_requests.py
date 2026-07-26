"""Pull requests: reads, the shared inventory-sufficiency gate, approve/complete flows."""

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
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.shipping_out_request import ShippingOutRequest as ShippingOutRequestModel
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.shop_assembly import ShopAssemblyRequest as ShopAssemblyRequestModel
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

    - Base availability is `quantity - deficient_quantity`, the same rule approve_pull_request
      deducts under. A deficiency reported at the bench bumps the inventory row's `quantity` and
      `deficient_quantity` together, so it nets to zero here - a condemned unit is back in the
      building but is not available, and it is not double-counted against anything.
    - `reservation_aware=True` also subtracts active reservations, giving
      `available = on-hand - deficient - reservations`. This is what request creation gates on and
      what pull approval re-checks: stock another request has already claimed is not free.
    - `exclude_reservations_of=(source, request_id)` is **self-coverage**. Approving request R's
      pull spends R's own reservations, so R's claim must not be counted against R - otherwise a
      request that reserved exactly what it needs could never be approved. Everyone else's claims
      still count, which is what stops a PR-REPL replacement pull (which holds no reservations of
      its own, because a deficiency cannot be foreseen) from eating stock somebody reserved.

    With lock=True the inventory rows are SELECT ... FOR UPDATE and returned grouped by combo so the
    caller can pull FIFO against exactly what was checked. Creation locks too: two creators racing
    for the last hinge serialise on those rows, so the second one sees the first one's reservation.
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


def find_reservation_holder(session: Session, pr: PullRequestModel) -> tuple[ReservationSource, uuid.UUID] | None:
    """The request whose reservations this pull is going to spend, or None if it has none (#342).

    A shop-assembly accept stamps the minted PR with the request's own `request_number` (unique on
    both tables), and a shipping-out accept stamps `pull_request_id` on the request - so each hop
    is a single indexed lookup, no string parsing.

    None is the honest answer for three real cases, and they all behave identically downstream (the
    pull is checked against on-hand minus *everyone's* reservations, and consumes nothing):

    - a **PR-REPL replacement pull**. Nobody can reserve for a deficiency that has not happened yet,
      so a replacement genuinely holds no claim; it keeps the reactive check and the PO-backfill
      loop, and it must not be able to eat stock other requests have reserved.
    - a pull whose source request was **rejected/reopened** after the accept - the claim is gone by
      design.
    - a **legacy pull** minted before this table existed, or one created directly by a non-UI caller.
    """
    if pr.source == PullRequestSource.SHOP_ASSEMBLY:
        sar_id = session.scalar(
            select(ShopAssemblyRequestModel.id).where(ShopAssemblyRequestModel.request_number == pr.request_number)
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


def approve_pull_request(session: Session, pr_id: uuid.UUID, approved_by: str) -> tuple:
    """
    Approve a pull request with pessimistic locking and FIFO inventory deduction.

    Returns tuple: (pr, outcome_string, notification_or_none, shortfalls)
    where outcome_string is "APPROVED" or "INSUFFICIENT". On INSUFFICIENT the PR is left PENDING
    (the pull is blocked, not cancelled - #224), `notification_or_none` is the PO backfill signal,
    and `shortfalls` lists the shorted combos. On APPROVED `shortfalls` is empty.

    Since #342 this is where a request's reservation is **consumed**: the claim it has held since
    creation turns into the actual FIFO deduction, atomically, under the same row locks. Two rules
    make that safe:

    - **Self-coverage.** The availability check excludes this request's own reservations. They are
      what backs the deduction; counting them as competing demand would make a correctly-reserved
      request permanently unapprovable.
    - **Consume only on success.** A pull that comes up short keeps its claim and stays PENDING, so
      the blocked request does not quietly hand its hardware to whoever asks next.

    A shortfall on a pull that *did* hold reservations is not normal flow - it means stock vanished
    under a live claim (an admin write-off or quantity override). It is reported the same way so the
    approver and the PO see it, but it is additionally recorded as an integrity event, because the
    reserved path is supposed to be un-shortfallable.
    """
    # 1. Lock PR
    locked_prs = lock_rows(session, PullRequestModel, [pr_id])
    if not locked_prs:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked_prs[0]

    if pr.status != PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Pull request must be Pending to approve, got {pr.status.value}")

    # 2. Gather inventory needs from Loose items
    needs: list[tuple[str, str, int]] = []
    opening_item_ids: list[uuid.UUID] = []

    for item in pr.items:
        if item.item_type == PullRequestItemType.LOOSE:
            needs.append((item.hardware_category, item.product_code, item.requested_quantity))
        elif item.item_type == PullRequestItemType.OPENING_ITEM:
            if item.opening_item_id is not None:
                opening_item_ids.append(item.opening_item_id)

    now = datetime.utcnow()

    # 3. Re-run the shared sufficiency gate, locking the rows we'd pull from. Reservation-aware, with
    #    this request's own claim excluded (self-coverage) - so it pulls from
    #    on-hand - deficient - *other* requests' reservations, plus whatever it reserved itself.
    holder = find_reservation_holder(session, pr)
    result = check_inventory_sufficiency(
        session,
        pr.project_id,
        needs,
        lock=True,
        reservation_aware=True,
        exclude_reservations_of=holder,
    )

    # 4. If short: leave the PR PENDING (blocked, not cancelled), keep the reservations (the claim
    #    outlives the blocked attempt), and notify the PO for backfill.
    if not result.sufficient:
        notif = notification_service.notify_po_shortfall(
            session,
            project_id=pr.project_id,
            request_number=pr.request_number,
            shortfalls=result.shortfalls,
        )
        if holder is not None:
            # The reserved path is not supposed to be able to come up short. Record it against the
            # pull so the discrepancy is investigable rather than indistinguishable from the normal
            # PR-REPL / legacy shortfall the approver sees.
            _log_audit_event(
                session,
                project_id=pr.project_id,
                entity_type=AuditEntityType.INVENTORY_LOCATION,
                entity_id=pr.id,
                action=AuditAction.PULL_DEDUCTION,
                performed_by=approved_by,
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
                        for s in result.shortfalls
                    ],
                },
            )
        return (pr, "INSUFFICIENT", notif, result.shortfalls)

    # 5. If sufficient: consume the source request's claim and deduct FIFO, in this transaction.
    #    Consumption happens before the deduction so the two can never be observed apart: a reader
    #    between them would otherwise see the units both reserved and already gone.
    if holder is not None:
        reservations.release_reservations(session, holder[0], holder[1])

    pr.status = PullRequestStatus.IN_PROGRESS
    pr.assigned_to = approved_by
    pr.approved_at = now

    if needs:
        inv_by_combo = result.inventory_by_combo
        needed_combos: dict[tuple[str, str], int] = defaultdict(int)
        for cat, code, qty in needs:
            needed_combos[(cat, code)] += qty

        for (cat, code), requested in needed_combos.items():
            # Sort by received_at ASC (oldest first) for FIFO
            rows = sorted(inv_by_combo.get((cat, code), []), key=lambda r: r.received_at)
            remaining = requested
            for row in rows:
                if remaining <= 0:
                    break
                # Deficient units must stay on the row — only available units can be pulled
                row_available = row.quantity - (row.deficient_quantity or 0)
                if row_available <= 0:
                    continue
                deduct = min(remaining, row_available)
                old_qty = row.quantity
                row.quantity -= deduct
                remaining -= deduct
                _log_audit_event(
                    session,
                    project_id=pr.project_id,
                    entity_type=AuditEntityType.INVENTORY_LOCATION,
                    entity_id=row.id,
                    action=AuditAction.PULL_DEDUCTION,
                    performed_by=approved_by,
                    detail={
                        "oldQuantity": old_qty,
                        "newQuantity": row.quantity,
                        "deducted": deduct,
                        "pullRequestNumber": pr.request_number,
                        "hardwareCategory": cat,
                        "productCode": code,
                    },
                )

    # 6. Lock Opening_Item rows if any
    if opening_item_ids:
        lock_rows(session, OpeningItemModel, opening_item_ids)

    return (pr, "APPROVED", None, [])


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

    items = list(session.scalars(select(SAOpeningItemModel).where(SAOpeningItemModel.id.in_(by_item.keys()))).all())
    if not items:
        return
    openings = {
        o.id: o
        for o in session.scalars(
            select(ShopAssemblyOpening).where(
                ShopAssemblyOpening.id.in_({item.shop_assembly_opening_id for item in items})
            )
        ).all()
    }

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


def complete_pull_request(session: Session, pr_id: uuid.UUID, completed_by: str | None = None) -> PullRequestModel:
    """
    Complete a pull request:
    1. Validate status == In_Progress
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
    stmt = select(PullRequestModel).options(selectinload(PullRequestModel.items)).where(PullRequestModel.id == pr_id)
    pr = session.scalars(stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Pull request {pr_id} not found")

    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(f"Pull request must be In_Progress to complete, got {pr.status.value}")

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
    """Confirm that the cart(s) for these openings of an approved shop-assembly pull are built (#343).

    The warehouse stages a pull opening by opening; before this, `pull_status` was flipped for every
    opening at once when the whole pull was marked pulled, so an opening picked first thing in the
    morning was not assignable until the last one was picked. Each confirmed opening flips to PULLED
    on its own and becomes assignable and workable immediately - `assign_openings`,
    `record_assembly_progress` and `complete_opening` all gate on the opening's own `pull_status`,
    so nothing else has to change for the assembly floor to see it.

    **Nothing moves in inventory here.** The FIFO deduction and the consumption of the source
    request's reservation both happen at approval and stay there (see `approve_pull_request`).
    Approval is the moment the pull is committed: the reservation the request has held since creation
    becomes the deduction, atomically, under one set of row locks. Deducting per opening instead
    would mean an approved-but-unstaged opening held neither a reservation nor a deduction - its
    hardware would read as free and could be claimed by the next request, which is the exact hole
    #342 closed - and it would reintroduce a shortfall at staging time, where the only recovery is a
    half-deducted pull. Staging is progress tracking; `cancel_pull_request` is what reverses stock.

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


def cancel_pull_request(
    session: Session,
    pr_id: uuid.UUID,
    cancelled_by: str,
    reason: str | None = None,
) -> CancelResult:
    """Cancel an approved pull, put its hardware back on the shelf, and hand the source request back
    for re-acceptance (#343).

    Before this there was no way out of an approved pull: inventory had been deducted and
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

    **The source request goes back to PENDING**, with its reservation re-created from the returned
    quantities and re-checked against availability first. The claim was consumed at approval, so
    re-creating it is a new claim competing with everyone else's: if stock was written off or
    condemned under it in the meantime the re-check comes up short, and rather than write a partial
    claim that reads as covered, the request is left unreserved and flagged via `integrity_note` -
    the same honest-and-flagged shape the #342 backfill uses.

    **A PR-REPL replacement pull has no source request**, so cancelling one restocks and re-creates
    nothing: it never held a reservation (a deficiency cannot be foreseen, so nobody could have
    claimed for it). The leaf's `deficient_quantity` is untouched and the expectation stays on the
    checklist line - the replacement simply has to be requested again.
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
    openings = list(
        session.scalars(
            select(ShopAssemblyOpening)
            .where(ShopAssemblyOpening.pull_request_id == pr.id)
            .order_by(ShopAssemblyOpening.opening_number.asc())
        ).all()
    )

    cancellable_from_completed = pr.source == PullRequestSource.SHOP_ASSEMBLY and bool(openings)
    if pr.status == PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            "This pull has not been approved yet, so nothing has left inventory. Reopen or reject "
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
    #    assembled leaf, which approval only locked.
    needs_by_combo: dict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        if item.item_type != PullRequestItemType.LOOSE:
            continue
        if not item.hardware_category or not item.product_code or item.requested_quantity <= 0:
            continue
        needs_by_combo[(item.hardware_category, item.product_code)] += item.requested_quantity

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

    # 4. Hand the source request back, and re-claim the returned hardware for it if it is still free.
    #    The availability check runs *after* the restock, so the units just returned count towards it.
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
    accept is already effectively undone)."""
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
    session.delete(pr)
    session.flush()
