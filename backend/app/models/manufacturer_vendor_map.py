import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ManufacturerVendorMap(Base):
    """Learned mapping from a hardware line's TITAN manufacturer to the GP vendor a PO for it was
    confirmed against (issue #232). The PO dialog suggests an ordering vendor from the line's
    manufacturer; a saved mapping wins over a fuzzy match, and every confirmed PO upserts the
    manufacturer -> chosen-vendor pair here so the next PO for the same manufacturer auto-picks it.

    Keyed per GP company (the vendor master is per-company) on a normalized manufacturer_key so
    case/whitespace/punctuation/legal-suffix variants of the same manufacturer collapse to one row.
    manufacturer_label keeps a human-readable form of the manufacturer as last seen. gp_vendor_name
    is the vendor's display name snapshotted at confirm time (the GP vendor list isn't re-fetched just
    to render a suggestion). source records how the row was learned: `confirmed` from a PO the user
    pushed to GP, `imported` from a bulk seed."""

    __tablename__ = "manufacturer_vendor_map"
    __table_args__ = (
        Index(
            "ix_manufacturer_vendor_map_company_key",
            "gp_company",
            "manufacturer_key",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    gp_company: Mapped[str] = mapped_column(String(15), nullable=False)
    manufacturer_key: Mapped[str] = mapped_column(String, nullable=False)
    manufacturer_label: Mapped[str] = mapped_column(String, nullable=False)
    gp_vendor_id: Mapped[str] = mapped_column(String(15), nullable=False)
    gp_vendor_name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False, default="confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
