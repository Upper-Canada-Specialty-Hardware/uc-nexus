import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import DeficiencyResolution


class DeficiencyReview(Base):
    """A reviewed outcome for a batch of deficient units (project or stock origin).

    Exactly one of inventory_location_id / stock_item_id is set, enforced by CHECK.
    """

    __tablename__ = "deficiency_reviews"
    __table_args__ = (
        Index("ix_deficiency_reviews_reviewed_at", "reviewed_at"),
        CheckConstraint(
            "(inventory_location_id IS NULL) <> (stock_item_id IS NULL)",
            name="ck_deficiency_reviews_exactly_one_source",
        ),
        CheckConstraint("quantity >= 1", name="ck_deficiency_reviews_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    inventory_location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("inventory_locations.id"), nullable=True)
    stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
    resolution: Mapped[DeficiencyResolution] = mapped_column(
        Enum(DeficiencyResolution, name="deficiency_resolution", create_constraint=True),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    rma_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    resulting_stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
