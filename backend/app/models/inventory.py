import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class InventoryLocation(Base):
    """A quantity of one product sitting in one warehouse location.

    Note what is NOT here: no opening, no door leaf. Hardware is procured per opening, but receiving
    deliberately drops that identity and inventory becomes fungible - a hinge is a hinge. Identity is
    re-attached later, by the pull request that tags a quantity onto a specific leaf of a specific
    opening. See docs/HARDWARE_IDENTITY_LIFECYCLE.md before adding an opening or leaf column here.
    """

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
    # Cost per unit for rows with no PO origin (the SharePoint migration). Null when the cost lives on
    # a PO line; travels with the units the way the origin FKs do (allocate/destock/transfer/split all
    # carry it). Valuation reads coalesce(po_line.unit_cost, row.unit_cost, 0).
    # Numeric(19,5) tracks po_line_items.unit_cost: resolve_project_combo_cost copies a PO line's cost
    # onto a re-materialized row (a shipment return, a pull-cancel restock), so a GP-fed seven-figure
    # cost reaches this column too and a narrower one would just move the overflow to receive time.
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(19, 5), nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
