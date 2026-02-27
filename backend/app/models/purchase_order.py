import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import Classification, POStatus


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_purchase_orders_project_status", "project_id", "status"),
        Index("ix_purchase_orders_po_number", "po_number", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus, name="po_status", create_constraint=True), nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String, nullable=True)
    vendor_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    line_items: Mapped[list["POLineItem"]] = relationship(back_populates="purchase_order")


class POLineItem(Base):
    __tablename__ = "po_line_items"
    __table_args__ = (
        Index("ix_po_line_items_po_id", "po_id"),
        CheckConstraint("ordered_quantity >= 1", name="ck_po_line_items_ordered_quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="ck_po_line_items_received_quantity_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[Classification | None] = mapped_column(
        Enum(Classification, name="classification", create_constraint=True),
        nullable=True,
    )
    ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="line_items")
