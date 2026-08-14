import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class StockItem(Base):
    """Company-owned shelf hardware not tied to any project (non-stock inventory)."""

    __tablename__ = "stock_items"
    __table_args__ = (
        Index("ix_stock_items_cat_code", "hardware_category", "product_code"),
        Index("ix_stock_items_aisle", "aisle"),
        Index("ix_stock_items_warehouse", "warehouse_id", "aisle", "row", "bay"),
        CheckConstraint("quantity >= 0", name="ck_stock_items_quantity_nonneg"),
        CheckConstraint(
            "deficient_quantity >= 0",
            name="ck_stock_items_deficient_quantity_nonneg",
        ),
        CheckConstraint(
            "deficient_quantity <= quantity",
            name="ck_stock_items_deficient_within_quantity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    deficient_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aisle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    row: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bay: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Cost per unit for rows that entered off-PO (the SharePoint migration). Null on rows whose cost
    # lives on a PO line; valuation reads coalesce(po_line.unit_cost, row.unit_cost, 0).
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
