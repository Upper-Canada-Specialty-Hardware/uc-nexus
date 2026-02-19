import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, Integer, Numeric, Index, ForeignKey, Enum, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import Classification, HardwareItemState


class HardwareItem(Base):
    __tablename__ = "hardware_items"
    __table_args__ = (
        Index(
            "ix_hardware_items_project_cat_code",
            "project_id",
            "hardware_category",
            "product_code",
        ),
        Index("ix_hardware_items_state", "state"),
        Index("ix_hardware_items_po_line_item", "po_line_item_id"),
        CheckConstraint("item_quantity >= 1", name="ck_hardware_items_item_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    opening_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("openings.id"), nullable=False
    )
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    material_id: Mapped[str] = mapped_column(String, nullable=False)
    item_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    list_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    vendor_discount: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    markup_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    vendor_no: Mapped[str | None] = mapped_column(String, nullable=True)
    phase_code: Mapped[str | None] = mapped_column(String, nullable=True)
    item_category_code: Mapped[str | None] = mapped_column(String, nullable=True)
    product_group_code: Mapped[str | None] = mapped_column(String, nullable=True)
    submittal_id: Mapped[str | None] = mapped_column(String, nullable=True)
    classification: Mapped[Classification | None] = mapped_column(
        Enum(Classification, name="classification", create_constraint=True),
        nullable=True,
    )
    state: Mapped[HardwareItemState] = mapped_column(
        Enum(HardwareItemState, name="hardware_item_state", create_constraint=True),
        nullable=False,
    )
    po_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("po_line_items.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
