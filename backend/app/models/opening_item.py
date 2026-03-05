import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import OpeningItemState


class OpeningItem(Base):
    __tablename__ = "opening_items"
    __table_args__ = (
        Index("ix_opening_items_project_state", "project_id", "state"),
        Index("ix_opening_items_opening_id", "opening_id"),
        CheckConstraint("quantity >= 1", name="ck_opening_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    opening_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("openings.id"), nullable=False)
    opening_number: Mapped[str] = mapped_column(String, nullable=False)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    floor: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assembly_completed_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[OpeningItemState] = mapped_column(
        Enum(OpeningItemState, name="opening_item_state", create_constraint=True),
        nullable=False,
    )
    aisle: Mapped[str | None] = mapped_column(String, nullable=True)
    bay: Mapped[str | None] = mapped_column(String, nullable=True)
    bin: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    installed_hardware: Mapped[list["OpeningItemHardware"]] = relationship(back_populates="opening_item")


class OpeningItemHardware(Base):
    __tablename__ = "opening_item_hardware"
    __table_args__ = (
        Index("ix_opening_item_hardware_opening_item", "opening_item_id"),
        CheckConstraint("quantity >= 1", name="ck_opening_item_hardware_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    opening_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("opening_items.id"), nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    opening_item: Mapped["OpeningItem"] = relationship(back_populates="installed_hardware")
