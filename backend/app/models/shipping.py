import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestItemType, ReturnDisposition


class PackingSlip(Base):
    __tablename__ = "packing_slips"
    __table_args__ = (Index("ix_packing_slips_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    shipped_by: Mapped[str] = mapped_column(String, nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    items: Mapped[list["PackingSlipItem"]] = relationship(back_populates="packing_slip")


class PackingSlipItem(Base):
    __tablename__ = "packing_slip_items"
    __table_args__ = (
        Index("ix_packing_slip_items_packing_slip", "packing_slip_id"),
        CheckConstraint("quantity >= 1", name="ck_packing_slip_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slips.id"), nullable=False)
    item_type: Mapped[PullRequestItemType] = mapped_column(
        Enum(
            PullRequestItemType,
            name="pull_request_item_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    opening_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opening_items.id"), nullable=True)
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    # Door leaf this shipped line is for (#311): OPENING_ITEM rows stamp from the OpeningItem.leaf.
    # Immutable record on the slip. Null = legacy / loose.
    leaf: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    packing_slip: Mapped["PackingSlip"] = relationship(back_populates="items")


class ShipmentReturn(Base):
    """A shipment came back from site. Header mirrors PackingSlip; only loose lines are returnable."""

    __tablename__ = "shipment_returns"
    __table_args__ = (Index("ix_shipment_returns_packing_slip", "packing_slip_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slips.id"), nullable=False)
    # Where the returned stock physically lands (new inventory / stock rows are created here).
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    returned_by: Mapped[str] = mapped_column(String, nullable=False)
    returned_at: Mapped[datetime] = mapped_column(nullable=False)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    items: Mapped[list["ShipmentReturnItem"]] = relationship(back_populates="shipment_return")


class ShipmentReturnItem(Base):
    """One returned loose-hardware line, routed by its disposition into project inventory or stock."""

    __tablename__ = "shipment_return_items"
    __table_args__ = (
        Index("ix_shipment_return_items_return", "shipment_return_id"),
        Index("ix_shipment_return_items_packing_slip_item", "packing_slip_item_id"),
        CheckConstraint("quantity >= 1", name="ck_shipment_return_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipment_returns.id"), nullable=False)
    packing_slip_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slip_items.id"), nullable=False)
    disposition: Mapped[ReturnDisposition] = mapped_column(
        Enum(ReturnDisposition, name="return_disposition", create_constraint=True),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    rma_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resulting_inventory_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_locations.id"), nullable=True
    )
    resulting_stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    shipment_return: Mapped["ShipmentReturn"] = relationship(back_populates="items")
