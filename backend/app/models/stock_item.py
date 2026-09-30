import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import PoolKind


class StockItem(Base):
    """Company-owned shelf hardware not tied to any project: the Stock & Overhead pool (#832)."""

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
    # Stock or Overhead (#832). Part of the row's identity: a stock row and an overhead row of the same
    # product on the same shelf are two rows and never merge (see _find_or_create_stock_row).
    kind: Mapped[PoolKind] = mapped_column(
        Enum(PoolKind, name="pool_kind", create_constraint=True),
        nullable=False,
        default=PoolKind.STOCK,
        server_default=PoolKind.STOCK.value,
    )
    aisle: Mapped[str | None] = mapped_column(String(20), nullable=True)
    row: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bay: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Cost per unit of every unit on the row: a receipt off a no-project PO carries its line's price,
    # a destock the price the person chose, a migration its entry's. It is part of the row's merge key
    # (#942), so a row never holds units at two prices; null and zero both mean $0 and valuation reads
    # coalesce(unit_cost, 0). Numeric(19,5) for the same reason as inventory_locations.unit_cost: a
    # destock or a transfer copies that column onto this one, so a GP-fed cost ends up here as well.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
