import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestItemType, ShippingOutRequestStatus


class ShippingOutRequest(Base):
    """A shipping-out task minted by Start-a-Request (#293). It waits PENDING until any signed-in user
    accepts it, at which point the accept mints the warehouse PullRequest (SHIPPING_OUT, PENDING) and
    stamps pull_request_id. Mirrors ShopAssemblyRequest, but its items live here (there are no
    ShopAssemblyOpening rows to hang the PR off), so pull_request_id is the only link to its PR."""

    __tablename__ = "shipping_out_requests"
    __table_args__ = (Index("ix_shipping_out_requests_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[ShippingOutRequestStatus] = mapped_column(
        Enum(
            ShippingOutRequestStatus,
            name="shipping_out_request_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # See ShopAssemblyRequest.integrity_note (#342): a schedule re-upload landed under this request,
    # or the reservations backfill could not cover it. Null = nothing has happened to it.
    integrity_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # Backfilled at accept: the warehouse PullRequest this request minted.
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pull_requests.id"), nullable=True)

    items: Mapped[list["ShippingOutRequestItem"]] = relationship(back_populates="shipping_out_request")


class ShippingOutRequestItem(Base):
    __tablename__ = "shipping_out_request_items"
    __table_args__ = (
        Index("ix_shipping_out_request_items_request", "shipping_out_request_id"),
        Index("ix_shipping_out_request_items_opening_item", "opening_item_id"),
        CheckConstraint(
            "requested_quantity >= 1",
            name="ck_shipping_out_request_items_requested_quantity_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipping_out_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipping_out_requests.id"), nullable=False)
    item_type: Mapped[PullRequestItemType] = mapped_column(
        Enum(
            PullRequestItemType,
            name="pull_request_item_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    # Null on a line raised straight off project inventory (#451). Inventory carries no opening - a
    # hinge on a shelf belongs to the project, not to a door - so a line composed from a shelf has
    # nothing to attribute. Schedule-driven lines keep the opening they came off, which is what the
    # pick sheet groups its carts by.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    opening_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opening_items.id"), nullable=True)
    # Door leaf this request line is for (#311/#335): OPENING_ITEM lines snapshot the assembled
    # OpeningItem.leaf so a pair reads as two distinct lines before anyone accepts the request.
    # LOOSE lines are null - loose stock is fungible and the shipping selection aggregates it
    # leaf-agnostically. Copied onto PullRequestItem.leaf at accept.
    leaf: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    hardware_category: Mapped[str | None] = mapped_column(String, nullable=True)
    product_code: Mapped[str | None] = mapped_column(String, nullable=True)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipping_out_request: Mapped["ShippingOutRequest"] = relationship(back_populates="items")
