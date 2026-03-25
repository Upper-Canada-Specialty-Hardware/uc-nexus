"""Repository for shop assembly data access."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AssemblyStatus,
    NotificationType,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ShopAssemblyRequestStatus,
)
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.opening_item import OpeningItemHardware as OIHModel
from app.models.project import Opening as OpeningModel
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
from app.services import notification_service
from app.services.locking import lock_rows


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShopAssemblyRequestStatus | None = None,
) -> list[ShopAssemblyRequest]:
    """Query ShopAssemblyRequests, optionally filtered by project and/or status."""
    stmt = select(ShopAssemblyRequest).options(
        selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items)
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ShopAssemblyRequest.status == status)
    stmt = stmt.order_by(ShopAssemblyRequest.created_at.desc())
    return list(session.scalars(stmt).unique().all())


def get_assemble_list(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> list[tuple[ShopAssemblyOpening, OpeningModel]]:
    """Query ShopAssemblyOpenings from Approved SARs, optionally filtered by project, with Opening data."""
    stmt = (
        select(ShopAssemblyOpening, OpeningModel)
        .join(
            ShopAssemblyRequest,
            ShopAssemblyOpening.shop_assembly_request_id == ShopAssemblyRequest.id,
        )
        .join(OpeningModel, ShopAssemblyOpening.opening_id == OpeningModel.id)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.status == ShopAssemblyRequestStatus.APPROVED)
    )
    if project_id is not None:
        stmt = stmt.where(ShopAssemblyRequest.project_id == project_id)
    return list(session.execute(stmt).unique().all())


def get_my_work(
    session: Session,
    assigned_to: str,
) -> list[tuple[ShopAssemblyOpening, OpeningModel]]:
    """Query ShopAssemblyOpenings assigned to a user with Pending assembly_status.
    Returns list of (ShopAssemblyOpening, Opening) tuples for resolving opening fields."""
    stmt = (
        select(ShopAssemblyOpening, OpeningModel)
        .join(
            ShopAssemblyRequest,
            ShopAssemblyOpening.shop_assembly_request_id == ShopAssemblyRequest.id,
        )
        .join(OpeningModel, ShopAssemblyOpening.opening_id == OpeningModel.id)
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            ShopAssemblyOpening.assigned_to == assigned_to,
            ShopAssemblyOpening.assembly_status == AssemblyStatus.PENDING,
            ShopAssemblyRequest.status == ShopAssemblyRequestStatus.APPROVED,
        )
        .order_by(OpeningModel.opening_number.asc())
    )
    return list(session.execute(stmt).unique().all())


def approve_shop_assembly_request(
    session: Session,
    sar_id: uuid.UUID,
) -> tuple[ShopAssemblyRequest, PullRequestModel]:
    """Approve a SAR, update openings, and create a corresponding PullRequest."""
    # Load SAR with openings -> items
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == sar_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"ShopAssemblyRequest {sar_id} not found")

    # Validate status is Pending
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Cannot approve SAR in status {sar.status.value}; must be Pending")

    # Update SAR
    sar.status = ShopAssemblyRequestStatus.APPROVED
    sar.approved_by = "Shop Assembly Manager"
    sar.approved_at = datetime.utcnow()

    # Update all openings to Not_Pulled
    for opening in sar.openings:
        opening.pull_status = PullStatus.NOT_PULLED

    # Generate PR number
    pr_number = f"PR-{sar.request_number}"

    # Check PR uniqueness
    existing_pr_stmt = select(PullRequestModel).where(PullRequestModel.request_number == pr_number)
    existing_pr = session.scalars(existing_pr_stmt).first()
    if existing_pr is not None:
        raise ConflictError(f"PullRequest with request_number {pr_number} already exists")

    # Create PullRequest
    pr = PullRequestModel(
        id=uuid.uuid4(),
        request_number=pr_number,
        project_id=sar.project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by=sar.created_by,
    )
    session.add(pr)
    session.flush()  # Get pr.id for PullRequestItems

    # Create PullRequestItems for each opening's items
    for sa_opening in sar.openings:
        # Look up the Opening model to get opening_number
        opening_stmt = select(OpeningModel).where(OpeningModel.id == sa_opening.opening_id)
        opening = session.scalars(opening_stmt).first()
        if opening is None:
            raise NotFoundError(f"Opening {sa_opening.opening_id} not found")

        for item in sa_opening.items:
            pr_item = PullRequestItemModel(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                item_type=PullRequestItemType.LOOSE,
                opening_number=opening.opening_number,
                hardware_category=item.hardware_category,
                product_code=item.product_code,
                requested_quantity=item.quantity,
            )
            session.add(pr_item)

    return (sar, pr)


def reject_shop_assembly_request(
    session: Session,
    sar_id: uuid.UUID,
    reason: str,
) -> ShopAssemblyRequest:
    """Reject a SAR with a reason, and create a notification."""
    # Load SAR
    stmt = (
        select(ShopAssemblyRequest)
        .options(selectinload(ShopAssemblyRequest.openings).selectinload(ShopAssemblyOpening.items))
        .where(ShopAssemblyRequest.id == sar_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"ShopAssemblyRequest {sar_id} not found")

    # Validate status is Pending
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Cannot reject SAR in status {sar.status.value}; must be Pending")

    # Validate reason length
    if not reason or len(reason) < 1 or len(reason) > 500:
        raise ValidationError(
            "Rejection reason must be between 1 and 500 characters",
            field="reason",
        )

    # Update SAR
    sar.status = ShopAssemblyRequestStatus.REJECTED
    sar.rejected_by = "Shop Assembly Manager"
    sar.rejection_reason = reason
    sar.rejected_at = datetime.utcnow()

    # Create notification
    notification_service.create_notification(
        session,
        sar.project_id,
        sar.created_by,
        NotificationType.SHOP_ASSEMBLY_REQUEST_REJECTED,
        f"Shop Assembly Request {sar.request_number} was rejected: {reason}.",
    )

    return sar


def assign_openings(
    session: Session,
    opening_ids: list[uuid.UUID],
    assigned_to: str,
) -> list[ShopAssemblyOpening]:
    """Assign ShopAssemblyOpenings to a user with pessimistic locking."""
    if not opening_ids:
        raise ValidationError("opening_ids must not be empty", field="opening_ids")
    if not assigned_to:
        raise ValidationError("assigned_to must not be empty", field="assigned_to")

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
        if opening.assigned_to is not None:
            raise ConflictError(f"Opening already assigned to {opening.assigned_to}")
        opening.assigned_to = assigned_to

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
    if opening.assigned_to is None:
        raise ValidationError("Opening is not assigned to anyone", field="assigned_to")

    opening.assigned_to = None
    return opening


def complete_opening(
    session: Session,
    opening_id: uuid.UUID,
    aisle: str | None,
    bay: str | None,
    bin: str | None,
) -> OpeningItemModel:
    """Mark an opening's assembly as complete. Creates OpeningItem + OpeningItemHardware records."""
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

    # 2. Load the Opening for opening_number, building, floor, location
    opening = session.get(OpeningModel, sa_opening.opening_id)
    if opening is None:
        raise NotFoundError(f"Opening {sa_opening.opening_id} not found")

    # 3. Load the SAR for project_id and request_number
    sar = session.get(ShopAssemblyRequest, sa_opening.shop_assembly_request_id)
    if sar is None:
        raise NotFoundError(f"ShopAssemblyRequest {sa_opening.shop_assembly_request_id} not found")

    # 4. Derive the auto-generated PR number and find the completed PR
    pr_number = f"PR-{sar.request_number}"
    pr_stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(
            PullRequestModel.request_number == pr_number,
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
        )
    )
    pr = session.scalars(pr_stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Completed PullRequest {pr_number} not found")

    # 5. Filter PR items for this opening's opening_number
    opening_pr_items = [item for item in pr.items if item.opening_number == opening.opening_number]

    # 6. Create OpeningItem
    now = datetime.utcnow()
    opening_item = OpeningItemModel(
        id=uuid.uuid4(),
        project_id=sar.project_id,
        opening_id=sa_opening.opening_id,
        opening_number=opening.opening_number,
        building=opening.building,
        floor=opening.floor,
        location=opening.location,
        quantity=1,
        assembly_completed_at=now,
        state=OpeningItemState.IN_INVENTORY,
        aisle=aisle,
        bay=bay,
        bin=bin,
    )
    session.add(opening_item)
    session.flush()  # Get opening_item.id for OpeningItemHardware FK

    # 7. Create OpeningItemHardware for each PR item
    for pr_item in opening_pr_items:
        oih = OIHModel(
            id=uuid.uuid4(),
            opening_item_id=opening_item.id,
            product_code=pr_item.product_code,
            hardware_category=pr_item.hardware_category,
            quantity=pr_item.requested_quantity,
        )
        session.add(oih)

    # 8. Mark ShopAssemblyOpening as Completed
    sa_opening.assembly_status = AssemblyStatus.COMPLETED
    sa_opening.completed_at = now

    return opening_item
