import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Warehouse(Base):
    """A physical warehouse building. Locations (aisle/row/bay) are scoped to one warehouse."""

    __tablename__ = "warehouses"
    # Unique per company (#1256): one tenant's "Main" does not block another's, and codes are GP site
    # codes each company's GP assigns on its own.
    __table_args__ = (
        # Unique ignoring case (#1402), the rule the repository checks.
        Index("uq_warehouses_company_lower_name", "company", func.lower(text("name")), unique=True),
        Index("uq_warehouses_company_lower_code", "company", func.lower(text("code")), unique=True),
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
