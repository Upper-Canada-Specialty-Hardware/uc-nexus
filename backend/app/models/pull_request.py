import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestSource, PullRequestStatus


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
        # The pull number identifies the *live* pull for a request, not every pull that request has
        # ever had (#343). A cancelled pull keeps its number for the record, and re-accepting the
        # source request mints a fresh pull carrying the same number - so the uniqueness that makes
        # the number a usable key has to exclude cancelled rows, or the second accept would collide
        # exactly the way #325's reopen path had to hard-delete the PR to avoid.
        Index(
            "uq_pull_requests_request_number_live",
            "request_number",
            unique=True,
            postgresql_where=text("status <> 'CANCELLED'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(50), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
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
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # When the pick was confirmed and by whom (#367). This - not approved_at - is the moment stock
    # left inventory, so staging and completion gate on it. approved_at keeps its older, weaker
    # meaning: the warehouse started on this pull. The two are equal on every pull that predates
    # per-location picking, because approval was the deduction back then.
    picked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    picked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Who cancelled the pull and why (#343). Cancellation returns real hardware to the shelf and
    # sends the source request back for re-acceptance, so - like a request rejection - it carries
    # its actor and its reason on the row, not only in the audit log.
    cancelled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    items: Mapped[list["PullRequestItem"]] = relationship(back_populates="pull_request")


class PullRequestItem(Base):
    """One tag: this quantity of this product now belongs to this opening.

    This row is where hardware regains the demand identity that receiving dropped (inventory is
    fungible - see docs/HARDWARE_IDENTITY_LIFECYCLE.md). Every line claims fungible stock, so
    approval deducts inventory FIFO and is gated on sufficiency. `opening_number` rides along as a
    tag: the pick sheet groups its carts by it, and nothing else keys off it.
    """

    __tablename__ = "pull_request_items"
    __table_args__ = (
        Index("ix_pull_request_items_pull_request", "pull_request_id"),
        CheckConstraint("requested_quantity >= 1", name="ck_pull_request_items_requested_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pull_requests.id"), nullable=False)
    # Null on a line raised straight off inventory (#451) - a hinge on a shelf belongs to the
    # project, not to a door. The pick sheet groups its carts by this, so an unattributed line simply
    # has no cart to name.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    pull_request: Mapped["PullRequest"] = relationship(back_populates="items")
