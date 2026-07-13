"""Repository for the learned manufacturer -> GP vendor mapping (issue #232)."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.manufacturer_vendor_map import ManufacturerVendorMap


def lookup(session: Session, gp_company: str, manufacturer_key: str) -> ManufacturerVendorMap | None:
    """The saved mapping for a normalized manufacturer key in a GP company, or None. manufacturer_key
    must already be normalized (via manufacturer_match.normalize) - it is the stored key verbatim."""
    if not gp_company or not manufacturer_key:
        return None
    stmt = select(ManufacturerVendorMap).where(
        ManufacturerVendorMap.gp_company == gp_company,
        ManufacturerVendorMap.manufacturer_key == manufacturer_key,
    )
    return session.scalars(stmt).first()


def upsert(
    session: Session,
    gp_company: str,
    manufacturer_key: str,
    label: str,
    gp_vendor_id: str,
    gp_vendor_name: str,
    source: str = "confirmed",
) -> ManufacturerVendorMap:
    """Insert or update the mapping for (gp_company, manufacturer_key). An existing row is repointed to
    the newly chosen vendor and its label/source refreshed - the latest confirmed choice wins.
    manufacturer_key must already be normalized. Flushes so a caller wrapping this in a savepoint sees
    any constraint error at the flush."""
    existing = lookup(session, gp_company, manufacturer_key)
    if existing is not None:
        existing.manufacturer_label = label
        existing.gp_vendor_id = gp_vendor_id
        existing.gp_vendor_name = gp_vendor_name
        existing.source = source
        session.flush()
        return existing

    row = ManufacturerVendorMap(
        id=uuid.uuid4(),
        gp_company=gp_company,
        manufacturer_key=manufacturer_key,
        manufacturer_label=label,
        gp_vendor_id=gp_vendor_id,
        gp_vendor_name=gp_vendor_name,
        source=source,
    )
    session.add(row)
    session.flush()
    return row
