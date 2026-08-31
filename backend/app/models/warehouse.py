import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Warehouse(Base):
    """A physical warehouse building. Locations (aisle/row/bay) are scoped to one warehouse."""

    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("name", name="uq_warehouses_name"),
        UniqueConstraint("code", name="uq_warehouses_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The GP company that owns this building - the tenant (#637). Everything warehouse-linked
    # (locations, stock items, receive drafts) inherits its scope from here rather than carrying a
    # column of its own.
    company: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    province: Mapped[str | None] = mapped_column(String, nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
