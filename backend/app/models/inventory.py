import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class InventoryLocation(Base):
    __tablename__ = "inventory_locations"
    __table_args__ = (
        Index(
            "ix_inventory_locations_project_cat_code",
            "project_id",
            "hardware_category",
            "product_code",
        ),
        Index("ix_inventory_locations_aisle", "aisle"),
        Index("ix_inventory_locations_stock_item", "stock_item_id"),
        Index("ix_inventory_locations_shipment_return_item", "shipment_return_item_id"),
        Index("ix_inventory_locations_warehouse", "warehouse_id", "aisle", "row", "bay"),
        CheckConstraint("quantity >= 0", name="ck_inventory_locations_quantity_nonneg"),
        CheckConstraint(
            "deficient_quantity >= 0",
            name="ck_inventory_locations_deficient_quantity_nonneg",
        ),
        CheckConstraint(
            "deficient_quantity <= quantity",
            name="ck_inventory_locations_deficient_within_quantity",
        ),
        CheckConstraint(
            "(po_line_item_id IS NOT NULL AND receive_line_item_id IS NOT NULL) "
            "OR stock_item_id IS NOT NULL "
            "OR shipment_return_item_id IS NOT NULL",
            name="ck_inventory_locations_has_origin",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    po_line_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("po_line_items.id"), nullable=True)
    receive_line_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("receive_line_items.id"), nullable=True)
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("stock_items.id", ondelete="SET NULL"), nullable=True
    )
    shipment_return_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipment_return_items.id", ondelete="SET NULL"), nullable=True
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    deficient_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aisle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    row: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bay: Mapped[str | None] = mapped_column(String(20), nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
