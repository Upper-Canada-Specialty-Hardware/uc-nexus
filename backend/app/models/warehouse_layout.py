import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class WarehouseAisle(Base):
    __tablename__ = "warehouse_aisles"
    __table_args__ = (Index("ix_warehouse_aisles_active", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    x_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    y_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    bays: Mapped[list["WarehouseBay"]] = relationship(back_populates="aisle")


class WarehouseBay(Base):
    __tablename__ = "warehouse_bays"
    __table_args__ = (
        UniqueConstraint("aisle_id", "name", name="uq_warehouse_bays_aisle_name"),
        Index("ix_warehouse_bays_aisle", "aisle_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    aisle_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_aisles.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    row_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    col_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    aisle: Mapped["WarehouseAisle"] = relationship(back_populates="bays")
    bins: Mapped[list["WarehouseBin"]] = relationship(back_populates="bay")


class WarehouseBin(Base):
    __tablename__ = "warehouse_bins"
    __table_args__ = (
        UniqueConstraint("bay_id", "name", name="uq_warehouse_bins_bay_name"),
        Index("ix_warehouse_bins_bay", "bay_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bay_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouse_bays.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(20), nullable=False)
    row_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    col_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    bay: Mapped["WarehouseBay"] = relationship(back_populates="bins")
