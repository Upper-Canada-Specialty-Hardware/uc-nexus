import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Index, ForeignKey, Enum, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestSource, PullRequestStatus, PullRequestItemType


class PullRequest(Base):
    __tablename__ = "pull_requests"
    __table_args__ = (
        Index(
            "ix_pull_requests_project_source_status",
            "project_id",
            "source",
            "status",
        ),
        Index("ix_pull_requests_assigned_to", "assigned_to"),
        Index("ix_pull_requests_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    source: Mapped[PullRequestSource] = mapped_column(
        Enum(PullRequestSource, name="pull_request_source", create_constraint=True),
        nullable=False,
    )
    status: Mapped[PullRequestStatus] = mapped_column(
        Enum(PullRequestStatus, name="pull_request_status", create_constraint=True),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    items: Mapped[list["PullRequestItem"]] = relationship(
        back_populates="pull_request"
    )


class PullRequestItem(Base):
    __tablename__ = "pull_request_items"
    __table_args__ = (
        Index("ix_pull_request_items_pull_request", "pull_request_id"),
        Index("ix_pull_request_items_opening_item", "opening_item_id"),
        CheckConstraint("requested_quantity >= 1", name="ck_pull_request_items_requested_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id"), nullable=False
    )
    item_type: Mapped[PullRequestItemType] = mapped_column(
        Enum(
            PullRequestItemType,
            name="pull_request_item_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    opening_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opening_items.id"), nullable=True
    )
    hardware_category: Mapped[str | None] = mapped_column(String, nullable=True)
    product_code: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    pull_request: Mapped["PullRequest"] = relationship(back_populates="items")
