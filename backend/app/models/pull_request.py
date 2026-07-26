import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestItemType, PullRequestSource, PullRequestStatus


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
    """One tag: this quantity of this product now belongs to this door leaf of this opening.

    This row is where hardware regains the opening identity that receiving dropped (inventory is
    fungible - see docs/HARDWARE_IDENTITY_LIFECYCLE.md). The two item types tag differently:
    LOOSE claims fungible stock, so approval deducts inventory FIFO and is gated on sufficiency;
    OPENING_ITEM moves an assembled leaf that was already tagged at shop assembly, so approval
    deducts nothing and only locks the OpeningItem row.
    """

    __tablename__ = "pull_request_items"
    __table_args__ = (
        Index("ix_pull_request_items_pull_request", "pull_request_id"),
        Index("ix_pull_request_items_opening_item", "opening_item_id"),
        Index("ix_pull_request_items_sa_opening_item", "sa_opening_item_id"),
        CheckConstraint("requested_quantity >= 1", name="ck_pull_request_items_requested_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pull_requests.id"), nullable=False)
    item_type: Mapped[PullRequestItemType] = mapped_column(
        Enum(
            PullRequestItemType,
            name="pull_request_item_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    opening_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opening_items.id"), nullable=True)
    # The deficient shop-assembly checklist item this line replaces (#339). Set only on PR-REPL
    # replacement lines minted by report_deficiency_at_assembly, so a replacement pull can be traced
    # back to the exact ShopAssemblyOpeningItem that failed at the bench. Null on every other line.
    sa_opening_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shop_assembly_opening_items.id"), nullable=True
    )
    # Door leaf this pull line is for (#311): SHOP_ASSEMBLY LOOSE from ShopAssemblyOpening.leaf,
    # SHIPPING_OUT OPENING_ITEM from OpeningItem.leaf. Snapshot so a leaf-1 pull reads distinct from
    # a leaf-2 pull. Null = legacy / leaf-agnostic.
    leaf: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hardware_category: Mapped[str | None] = mapped_column(String, nullable=True)
    product_code: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    pull_request: Mapped["PullRequest"] = relationship(back_populates="items")
