"""Repository for Vendor CRUD operations."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.vendor import Vendor


def list_vendors(session: Session) -> list[Vendor]:
    return list(session.scalars(select(Vendor).order_by(Vendor.name)).all())


def get_vendor(session: Session, vendor_id: uuid.UUID) -> Vendor:
    vendor = session.get(Vendor, vendor_id)
    if vendor is None:
        raise NotFoundError(f"Vendor {vendor_id} not found")
    return vendor


def _check_name_unique(session: Session, name: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(Vendor).where(Vendor.name == name)
    if exclude_id is not None:
        stmt = stmt.where(Vendor.id != exclude_id)
    existing = session.scalars(stmt).first()
    if existing is not None:
        raise ConflictError(f"Vendor name '{name}' already exists", field="name")


def create_vendor(
    session: Session,
    name: str,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> Vendor:
    name = name.strip()
    if not name:
        raise ValidationError("Vendor name is required", field="name")

    _check_name_unique(session, name)

    vendor = Vendor(
        id=uuid.uuid4(),
        name=name,
        contact_name=contact_name,
        email=email,
        phone=phone,
        notes=notes,
    )
    session.add(vendor)
    session.flush()
    return vendor


def update_vendor(
    session: Session,
    vendor_id: uuid.UUID,
    name: str | None = None,
    contact_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    notes: str | None = None,
) -> Vendor:
    vendor = get_vendor(session, vendor_id)

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("Vendor name is required", field="name")
        _check_name_unique(session, name, exclude_id=vendor_id)
        vendor.name = name
    if contact_name is not None:
        vendor.contact_name = contact_name
    if email is not None:
        vendor.email = email
    if phone is not None:
        vendor.phone = phone
    if notes is not None:
        vendor.notes = notes

    session.flush()
    return vendor


def delete_vendor(session: Session, vendor_id: uuid.UUID) -> None:
    vendor = get_vendor(session, vendor_id)

    referenced = session.scalar(select(func.count()).select_from(POModel).where(POModel.vendor_id == vendor_id))
    if referenced and referenced > 0:
        raise ConflictError(
            f"Cannot delete vendor: referenced by {referenced} purchase order(s)",
        )

    session.delete(vendor)
    session.flush()
