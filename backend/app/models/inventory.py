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
        Index("ix_inventory_locations_shelf", "shelf"),
        CheckConstraint("quantity >= 0", name="ck_inventory_locations_quantity_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    po_line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_line_items.id"), nullable=False)
    receive_line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receive_line_items.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    shelf: Mapped[str | None] = mapped_column(String(20), nullable=True)
    column: Mapped[str | None] = mapped_column(String(20), nullable=True)
    row: Mapped[str | None] = mapped_column(String(20), nullable=True)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
