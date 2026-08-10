import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import ShippingOutRequestStatus


class ShippingOutRequest(Base):
    """A shipping-out task minted by Start-a-Request (#293). It waits PENDING until any signed-in user
    accepts it, at which point the accept mints the warehouse PullRequest (SHIPPING_OUT, PENDING) and
    stamps pull_request_id. Mirrors ShopAssemblyRequest exactly - same flat lines, same accept gate,
    same link to its pull. The two differ only in which exit the completed pull is."""

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
        CheckConstraint(
            "requested_quantity >= 1",
            name="ck_shipping_out_request_items_requested_quantity_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipping_out_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipping_out_requests.id"), nullable=False)
    # Null on a line raised straight off project inventory (#451). Inventory carries no opening - a
    # hinge on a shelf belongs to the project, not to a door - so a line composed from a shelf has
    # nothing to attribute. Schedule-driven lines keep the opening they came off, which is what the
    # pick sheet groups its carts by.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipping_out_request: Mapped["ShippingOutRequest"] = relationship(back_populates="items")
