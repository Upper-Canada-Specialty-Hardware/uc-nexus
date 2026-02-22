import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestItemType


class PackingSlip(Base):
    __tablename__ = "packing_slips"
    __table_args__ = (Index("ix_packing_slips_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
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
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    packing_slip: Mapped["PackingSlip"] = relationship(back_populates="items")
