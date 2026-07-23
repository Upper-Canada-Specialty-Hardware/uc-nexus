"""Repository for shop assembly data access."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    ConflictError,
    InvalidStateTransitionError,
    InventoryShortfallError,
    NotFoundError,
    ValidationError,
)
from app.models.enums import (
    AssemblyStatus,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ShopAssemblyRequestStatus,
)
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OIHModel
from app.models.pull_request import (
    PullRequest as PullRequestModel,
)
from app.models.pull_request import (
    PullRequestItem as PullRequestItemModel,
)
from app.models.shop_assembly import (
    ShopAssemblyOpening,
    ShopAssemblyRequest,
)
from app.services.locking import lock_rows


@dataclass
class OpeningItemResult:
    """One line of the completion-time deficiency checklist (#225)."""

    shop_assembly_opening_item_id: uuid.UUID
    installed: bool = True
    deficient_reason: str | None = None


def get_assemble_list(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> list[ShopAssemblyOpening]:
    """Query ShopAssemblyOpenings whose shop-assembly PullRequest has been pulled (#222)."""
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            PullRequestModel,
            ShopAssemblyOpening.pull_request_id == PullRequestModel.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
        )
    )
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def get_my_work(
    session: Session,
    assigned_to_user_id: str,
) -> list[ShopAssemblyOpening]:
    """Query ShopAssemblyOpenings claimed by a user (by stable Clerk user id, #324) with Pending
    assembly_status."""
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            PullRequestModel,
            ShopAssemblyOpening.pull_request_id == PullRequestModel.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            ShopAssemblyOpening.assigned_to_user_id == assigned_to_user_id,
            ShopAssemblyOpening.assembly_status == AssemblyStatus.PENDING,
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
        )
        .order_by(ShopAssemblyOpening.opening_number.asc())
    )
    return list(session.scalars(stmt).unique().all())


def assign_openings(
    session: Session,
    opening_ids: list[uuid.UUID],
    assigned_to_user_id: str,
    assigned_to_name: str,
) -> list[ShopAssemblyOpening]:
    """Assign ShopAssemblyOpenings to a user with pessimistic locking. Keyed on the stable Clerk
    user id (#324); assigned_to_name is the display name stored alongside for the UI."""
    if not opening_ids:
        raise ValidationError("opening_ids must not be empty", field="opening_ids")
    if not assigned_to_user_id:
        raise ValidationError("assigned_to_user_id must not be empty", field="assigned_to_user_id")

    locked = lock_rows(session, ShopAssemblyOpening, opening_ids)
    if len(locked) != len(opening_ids):
        found_ids = {o.id for o in locked}
        missing = [str(oid) for oid in opening_ids if oid not in found_ids]
        raise NotFoundError(f"ShopAssemblyOpenings not found: {missing}")

    for opening in locked:
        if opening.pull_status != PullStatus.PULLED:
            raise InvalidStateTransitionError("Opening is not ready for assignment - hardware has not been pulled")
        if opening.assembly_status != AssemblyStatus.PENDING:
            raise InvalidStateTransitionError("Opening assembly is already completed")
        if opening.assigned_to_user_id is not None:
            raise ConflictError(f"Opening already assigned to {opening.assigned_to}")
        opening.assigned_to_user_id = assigned_to_user_id
        opening.assigned_to = assigned_to_name

    return locked


def remove_opening_from_user(
    session: Session,
    opening_id: uuid.UUID,
) -> ShopAssemblyOpening:
    """Unassign a ShopAssemblyOpening."""
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id == opening_id)
    )
    opening = session.scalars(stmt).unique().first()
    if opening is None:
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} not found")

    if opening.assembly_status != AssemblyStatus.PENDING:
        raise InvalidStateTransitionError("Cannot unassign a completed opening")
    if opening.assigned_to_user_id is None:
        raise ValidationError("Opening is not assigned to anyone", field="assigned_to")

    opening.assigned_to_user_id = None
    opening.assigned_to = None
    return opening


def complete_opening(
    session: Session,
    opening_id: uuid.UUID,
    aisle: str | None,
    row: str | None,
    bay: str | None,
    item_results: list[OpeningItemResult] | None = None,
    completed_by: str | None = None,
) -> OpeningItemModel:
    """Mark an opening's assembly as complete. Creates OpeningItem + OpeningItemHardware records.

    Completion-time deficiency checklist (#225): only items marked installed are snapshotted as
    OpeningItemHardware. Items marked not-installed are flagged deficient - the unit is returned to
    inventory flagged deficient and a PR-REPL replacement pull is appended (via
    stock_repository.report_deficiency_at_assembly). An empty/omitted item_results treats every
    item as installed, preserving pre-checklist behaviour.
    """
    # 1. Load and validate ShopAssemblyOpening (with pessimistic lock)
    locked = lock_rows(session, ShopAssemblyOpening, [opening_id])
    if not locked:
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} not found")
    sa_opening = locked[0]
    # Eager-load items
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id == opening_id)
    )
    sa_opening = session.scalars(stmt).unique().first()

    if sa_opening.assembly_status != AssemblyStatus.PENDING:
        raise InvalidStateTransitionError("Opening assembly is already completed")
    if sa_opening.assigned_to is None:
        raise ValidationError(
            "Opening must be assigned before it can be completed",
            field="assigned_to",
        )

    # 2. Load the shop-assembly PR this opening hangs off (#222). The FK gives it to us
    #    directly - no PR-number string parsing, no SAR lookup. It carries project_id and
    #    the LOOSE items that were pulled.
    if sa_opening.pull_request_id is None:
        raise NotFoundError(f"ShopAssemblyOpening {opening_id} is not linked to a pull request")
    # Only pr.project_id is read below (step 6 snapshots from sa_opening.items, not pr.items),
    # so don't eager-load pr.items - it would be a wasted query.
    pr_stmt = select(PullRequestModel).where(
        PullRequestModel.id == sa_opening.pull_request_id,
        PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
        PullRequestModel.status == PullRequestStatus.COMPLETED,
    )
    pr = session.scalars(pr_stmt).first()
    if pr is None:
        raise NotFoundError(f"Completed shop-assembly pull request for opening {opening_id} not found")

    # 4. Resolve the per-item installed/deficient checklist (#225). The checklist is keyed on
    #    ShopAssemblyOpeningItem ids (what the assembler sees in the modal). Any item without a
    #    result row defaults to installed, so an empty checklist preserves the old snapshot-all path.
    item_by_id = {item.id: item for item in sa_opening.items}
    deficient_reason_by_id: dict[uuid.UUID, str | None] = {}
    for res in item_results or []:
        if res.shop_assembly_opening_item_id not in item_by_id:
            raise ValidationError(
                f"Checklist item {res.shop_assembly_opening_item_id} does not belong to opening {opening_id}",
                field="item_results",
            )
        if not res.installed:
            reason = (res.deficient_reason or "").strip()
            if not reason:
                raise ValidationError(
                    "A deficiency reason is required for items not installed",
                    field="deficient_reason",
                )
            if len(reason) > 500:
                raise ValidationError(
                    "Deficiency reason must be 500 characters or fewer",
                    field="deficient_reason",
                )
            deficient_reason_by_id[res.shop_assembly_opening_item_id] = reason

    # 5. Create OpeningItem (snapshot opening identity from the ShopAssemblyOpening row)
    now = datetime.utcnow()
    from app.repositories import warehouse_admin_repository

    opening_item = OpeningItemModel(
        id=uuid.uuid4(),
        project_id=pr.project_id,
        opening_id=sa_opening.opening_id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=sa_opening.opening_number,
        # Assembled unit is a single door leaf (#311): one OpeningItem per leaf, stamped from the
        # ShopAssemblyOpening. A pair yields two independently-located, independently-shippable units.
        leaf=sa_opening.leaf,
        building=sa_opening.building,
        floor=sa_opening.floor,
        location=sa_opening.location,
        quantity=1,
        assembly_completed_at=now,
        state=OpeningItemState.IN_INVENTORY,
        aisle=aisle,
        row=row,
        bay=bay,
    )
    session.add(opening_item)
    session.flush()  # Get opening_item.id for OpeningItemHardware FK

    # 6. Snapshot only INSTALLED items as OpeningItemHardware; flag the rest deficient.
    from app.repositories import stock as stock_repository

    performed_by = completed_by or "Assembler"
    for item in sa_opening.items:
        if item.id in deficient_reason_by_id:
            # Not installed -> return the unit to inventory flagged deficient + append PR-REPL pull.
            stock_repository.report_deficiency_at_assembly(
                session,
                sa_opening_item_id=item.id,
                quantity=item.quantity,
                reason_text=deficient_reason_by_id[item.id],
                performed_by=performed_by,
            )
            continue
        oih = OIHModel(
            id=uuid.uuid4(),
            opening_item_id=opening_item.id,
            product_code=item.product_code,
            hardware_category=item.hardware_category,
            quantity=item.quantity,
        )
        session.add(oih)

    # 7. Mark ShopAssemblyOpening as Completed
    sa_opening.assembly_status = AssemblyStatus.COMPLETED
    sa_opening.completed_at = now

    return opening_item


def get_openings_with_items(session: Session, opening_ids: list[uuid.UUID]) -> list[ShopAssemblyOpening]:
    """Shop-assembly openings by id with items eagerly loaded (mutation response reload)."""
    stmt = (
        select(ShopAssemblyOpening)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyOpening.id.in_(opening_ids))
    )
    return list(session.scalars(stmt).unique().all())


def get_request_with_openings(session: Session, request_id: uuid.UUID):
    """Shop-assembly request with openings + their items eagerly loaded (finalize-import reload)."""
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    return session.scalars(stmt).unique().first()


def find_already_assembled_openings(
    session: Session,
    project_id: uuid.UUID,
    opening_leaf_specs: list[tuple[str, uuid.UUID, int | None]],
) -> list[tuple[str, int | None]]:
    """REQ-5 guard (#293), per door leaf (#311): given (opening_number, opening_id, leaf) specs,
    return the (opening_number, leaf) pairs whose (opening_id, leaf) already has an assembled
    OpeningItem in this project (any state except SHIPPED_OUT). Keying on leaf means assembling
    Leaf 1 does NOT block sending Leaf 2 to shop assembly. Legacy null-leaf assembled units only
    match a null-leaf spec."""
    if not opening_leaf_specs:
        return []
    opening_ids = [oid for _, oid, _ in opening_leaf_specs]
    rows = session.execute(
        select(OpeningItemModel.opening_id, OpeningItemModel.leaf).where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.opening_id.in_(opening_ids),
            OpeningItemModel.state != OpeningItemState.SHIPPED_OUT,
        )
    ).all()
    assembled = {(r.opening_id, r.leaf) for r in rows}
    return [(num, leaf) for num, oid, leaf in opening_leaf_specs if (oid, leaf) in assembled]


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
) -> list[ShopAssemblyRequest]:
    """List shop-assembly requests for the accept UI (#293). Defaults to PENDING when no status is
    given. Openings + their items are eagerly loaded (shop_assembly_request_to_type walks both)."""
    effective_status = status if status is not None else ShopAssemblyRequestStatus.PENDING
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.status == effective_status)
        .order_by(ShopAssemblyRequest.created_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def accept_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    accepted_by: str,
) -> ShopAssemblyRequest:
    """Accept a PENDING shop-assembly request (#293).

    Re-runs the shared inventory-sufficiency gate over the request's openings' items. If short,
    raises InventoryShortfallError WITHOUT minting anything - the resolver rolls back, notifies the
    PO in a fresh session, and re-raises so the shortfall reaches the caller inline. If covered,
    flips the request to APPROVED and mints the warehouse PullRequest (SHOP_ASSEMBLY, PENDING) with
    one LOOSE item per opening item, then repoints the request's ShopAssemblyOpenings at that PR
    (pull_request_id) so the unchanged warehouse pull/complete flow works exactly as before.
    """
    from app.repositories import warehouse as warehouse_repository
    from app.services import notification_service

    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Pending to accept, got {sar.status.value}")

    needs = [
        (item.hardware_category, item.product_code, item.quantity) for opening in sar.openings for item in opening.items
    ]
    sufficiency = warehouse_repository.check_inventory_sufficiency(session, sar.project_id, needs)
    if not sufficiency.sufficient:
        raise InventoryShortfallError(
            "Cannot accept shop-assembly request - insufficient inventory. "
            + notification_service.format_shortfall_lines(sufficiency.shortfalls),
            shortfalls=sufficiency.shortfalls,
            project_id=sar.project_id,
            request_number=sar.request_number,
        )

    now = datetime.utcnow()
    sar.status = ShopAssemblyRequestStatus.APPROVED
    sar.approved_by = accepted_by
    sar.approved_at = now

    pr = PullRequestModel(
        id=uuid.uuid4(),
        request_number=sar.request_number,
        project_id=sar.project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by=accepted_by,
    )
    session.add(pr)
    session.flush()

    for opening in sar.openings:
        opening.pull_request_id = pr.id
        for item in opening.items:
            session.add(
                PullRequestItemModel(
                    id=uuid.uuid4(),
                    pull_request_id=pr.id,
                    item_type=PullRequestItemType.LOOSE,
                    opening_number=opening.opening_number,
                    # Snapshot the door leaf (#311) so a leaf-1 pull reads distinct from a leaf-2 pull.
                    leaf=opening.leaf,
                    hardware_category=item.hardware_category,
                    product_code=item.product_code,
                    requested_quantity=item.quantity,
                )
            )

    return sar


def reject_shop_assembly_request(
    session: Session,
    request_id: uuid.UUID,
    rejected_by: str,
    reason: str | None,
) -> ShopAssemblyRequest:
    """Reject a PENDING shop-assembly request (#293). Mints no PullRequest."""
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == request_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"Shop-assembly request {request_id} not found")
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shop-assembly request must be Pending to reject, got {sar.status.value}")

    sar.status = ShopAssemblyRequestStatus.REJECTED
    sar.rejected_by = rejected_by
    sar.rejection_reason = (reason or "").strip() or None
    sar.rejected_at = datetime.utcnow()
    return sar
