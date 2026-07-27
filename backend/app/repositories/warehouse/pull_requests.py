"""Pull requests: reads, the shared inventory-sufficiency gate, approve/complete flows."""

import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError
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
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.shop_assembly import ShopAssemblyOpening
from app.services import notification_service
from app.services.locking import lock_rows

from .audit import _log_audit_event


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
    available (quantity - deficient_quantity), and the gap. Emitted by the shared sufficiency gate
    and surfaced verbatim to the creator/approver and to the PO backfill notification."""

    hardware_category: str
    product_code: str
    requested: int
    available: int
    short: int


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
) -> SufficiencyResult:
    """Shared hard inventory-sufficiency gate (#224). Aggregates `needs` (an iterable of
    (hardware_category, product_code, quantity)) by combo, compares each against available
    inventory in the project, and returns a Shortfall per combo that can't be fully covered - no
    partial fulfilment. available = quantity - deficient_quantity, the same rule
    approve_pull_request deducts under. With lock=True the inventory rows are SELECT ... FOR UPDATE
    and returned grouped by combo so the caller can pull FIFO against exactly what was checked."""
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

    shortfalls: list[Shortfall] = []
    for (cat, code), requested in needed_combos.items():
        available = sum(il.quantity - (il.deficient_quantity or 0) for il in inv_by_combo.get((cat, code), []))
        if available < requested:
            shortfalls.append(Shortfall(cat, code, requested, available, requested - available))
    shortfalls.sort(key=lambda s: (s.hardware_category, s.product_code))

    return SufficiencyResult(shortfalls=shortfalls, inventory_by_combo=dict(inv_by_combo))


def approve_pull_request(session: Session, pr_id: uuid.UUID, approved_by: str) -> tuple:
    """
    Approve a pull request with pessimistic locking and FIFO inventory deduction.

    Returns tuple: (pr, outcome_string, notification_or_none, shortfalls)
    where outcome_string is "APPROVED" or "INSUFFICIENT". On INSUFFICIENT the PR is left PENDING
    (the pull is blocked, not cancelled - #224), `notification_or_none` is the PO backfill signal,
    and `shortfalls` lists the shorted combos. On APPROVED `shortfalls` is empty.
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

    # 3. Re-run the shared sufficiency gate, locking the rows we'd pull from.
    result = check_inventory_sufficiency(session, pr.project_id, needs, lock=True)

    # 4. If short: leave the PR PENDING (blocked, not cancelled) and notify the PO for backfill.
    if not result.sufficient:
        notif = notification_service.notify_po_shortfall(
            session,
            project_id=pr.project_id,
            request_number=pr.request_number,
            shortfalls=result.shortfalls,
        )
        return (pr, "INSUFFICIENT", notif, result.shortfalls)

    # 5. If sufficient: approve and deduct FIFO
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
        if leaf_completed:
            item.replacement_pending_quantity += restored
            opening_item = shop_assembly_repository.find_assembled_leaf(
                session, pr.project_id, opening.opening_id, opening.leaf
            )
            if opening_item is not None and opening_item.state == OpeningItemState.SHIPPED_OUT:
                leaf_label = f"Opening {opening.opening_number}"
                if opening.leaf is not None:
                    leaf_label += f" Leaf {opening.leaf}"
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


def complete_pull_request(session: Session, pr_id: uuid.UUID) -> PullRequestModel:
    """
    Complete a pull request:
    1. Validate status == In_Progress
    2. Set status=Completed, completed_at=now()
    3. Create notification
    4. Restore any leaf expectations the pull's replacement lines are owed to (#341)
    5. If Shipping_Out source: set Opening_Item states to Ship_Ready
    6. If Shop_Assembly source: update SAR openings pull_status to Pulled
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
        for opening in openings:
            opening.pull_status = PullStatus.PULLED

    return pr


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
