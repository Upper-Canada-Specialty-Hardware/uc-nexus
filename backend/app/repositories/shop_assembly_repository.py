"""Repository for shop assembly data access."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.shop_assembly import (
    ShopAssemblyRequest,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
)
from app.models.pull_request import (
    PullRequest as PullRequestModel,
    PullRequestItem as PullRequestItemModel,
)
from app.models.project import Opening as OpeningModel
from app.models.enums import (
    ShopAssemblyRequestStatus,
    PullStatus,
    PullRequestSource,
    PullRequestStatus,
    PullRequestItemType,
    NotificationType,
)
from app.services import notification_service
from app.errors import NotFoundError, ValidationError, InvalidStateTransitionError, ConflictError


def get_shop_assembly_requests(
    session: Session,
    project_id: uuid.UUID,
    status: ShopAssemblyRequestStatus | None = None,
) -> list[ShopAssemblyRequest]:
    """Query ShopAssemblyRequests for a project, optionally filtered by status."""
    stmt = (
        select(ShopAssemblyRequest)
        .options(
            selectinload(ShopAssemblyRequest.openings).selectinload(
                ShopAssemblyOpening.items
            )
        )
        .where(ShopAssemblyRequest.project_id == project_id)
    )
    if status is not None:
        stmt = stmt.where(ShopAssemblyRequest.status == status)
    stmt = stmt.order_by(ShopAssemblyRequest.created_at.desc())
    return list(session.scalars(stmt).unique().all())


def get_assemble_list(
    session: Session,
    project_id: uuid.UUID,
) -> list[ShopAssemblyOpening]:
    """Query ShopAssemblyOpenings from Approved SARs for the project."""
    stmt = (
        select(ShopAssemblyOpening)
        .join(
            ShopAssemblyRequest,
            ShopAssemblyOpening.shop_assembly_request_id == ShopAssemblyRequest.id,
        )
        .options(selectinload(ShopAssemblyOpening.items))
        .where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyRequest.status == ShopAssemblyRequestStatus.APPROVED,
        )
    )
    return list(session.scalars(stmt).unique().all())


def approve_shop_assembly_request(
    session: Session,
    sar_id: uuid.UUID,
) -> tuple[ShopAssemblyRequest, PullRequestModel]:
    """Approve a SAR, update openings, and create a corresponding PullRequest."""
    # Load SAR with openings -> items
    stmt = (
        select(ShopAssemblyRequest)
        .options(
            selectinload(ShopAssemblyRequest.openings).selectinload(
                ShopAssemblyOpening.items
            )
        )
        .where(ShopAssemblyRequest.id == sar_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"ShopAssemblyRequest {sar_id} not found")

    # Validate status is Pending
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Cannot approve SAR in status {sar.status.value}; must be Pending"
        )

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
    existing_pr_stmt = select(PullRequestModel).where(
        PullRequestModel.request_number == pr_number
    )
    existing_pr = session.scalars(existing_pr_stmt).first()
    if existing_pr is not None:
        raise ConflictError(
            f"PullRequest with request_number {pr_number} already exists"
        )

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
        opening_stmt = select(OpeningModel).where(
            OpeningModel.id == sa_opening.opening_id
        )
        opening = session.scalars(opening_stmt).first()
        if opening is None:
            raise NotFoundError(
                f"Opening {sa_opening.opening_id} not found"
            )

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
        .options(
            selectinload(ShopAssemblyRequest.openings).selectinload(
                ShopAssemblyOpening.items
            )
        )
        .where(ShopAssemblyRequest.id == sar_id)
    )
    sar = session.scalars(stmt).unique().first()
    if sar is None:
        raise NotFoundError(f"ShopAssemblyRequest {sar_id} not found")

    # Validate status is Pending
    if sar.status != ShopAssemblyRequestStatus.PENDING:
        raise InvalidStateTransitionError(
            f"Cannot reject SAR in status {sar.status.value}; must be Pending"
        )

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
