import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class WarehouseLocation(Base):
    """A defined put-away location (aisle/row/bay) in one warehouse - the registry (#632).

    Every location write validates against this: put-away, moves, destock/allocate targets and
    transfer destinations all refuse a triple that is not defined and active here, so the set of
    places hardware can land is managed rather than invented one free-text put-away at a time.

    Rows are stored in canonical form (`normalize_location_value`: uppercase, trimmed, collapsed
    whitespace), so a lookup against normalized input is exact string equality. `active` false
    retires a location from the pickers without touching hardware already sitting there - the
    utilization view still shows an occupied retired location until it drains.
    """

    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "aisle", "row", "bay", name="uq_warehouse_locations_triple"),
        Index("ix_warehouse_locations_warehouse", "warehouse_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False)
    aisle: Mapped[str] = mapped_column(String(20), nullable=False)
    row: Mapped[str] = mapped_column(String(20), nullable=False)
    bay: Mapped[str] = mapped_column(String(20), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
