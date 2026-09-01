"""The shipping department's list of how a load can travel (#451).

Small deliberately. A shipment method is documentation, not an entity anything downstream reasons
about: nothing joins to it, nothing is gated on it, and the slip keeps a string copy rather than a
reference. What this module is really protecting is the *list* - one spelling per carrier, and a
retired method that still reads correctly on the shipments it carried.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.shipment_method import ShipmentMethod


def get_shipment_methods(
    session: Session, *, active_only: bool = False, company: str | None = None
) -> list[ShipmentMethod]:
    """The list, in the order the dropdown shows it: sort_order, then name.

    `active_only` is what the Delivery Request form passes. The management screen leaves it off so a
    retired method is still visible to reactivate - hiding it there would make retirement a one-way
    door with no undo.
    """
    stmt = select(ShipmentMethod).order_by(ShipmentMethod.sort_order.asc(), ShipmentMethod.name.asc())
    if active_only:
        stmt = stmt.where(ShipmentMethod.is_active.is_(True))
    if company is not None:
        stmt = stmt.where(ShipmentMethod.company == company)
    return list(session.scalars(stmt).all())


def create_shipment_method(session: Session, *, name: str, sort_order: int = 0, company: str) -> ShipmentMethod:
    name = (name or "").strip()
    company = (company or "").strip().upper()
    if not name:
        raise ValidationError("A shipment method needs a name.", field="name")
    if not company:
        raise ValidationError("A GP company is required for a shipment method.", field="company")
    _check_name_free(session, name, company)
    method = ShipmentMethod(id=uuid.uuid4(), company=company, name=name, is_active=True, sort_order=sort_order)
    session.add(method)
    session.flush()
    return method


def update_shipment_method(
    session: Session,
    method_id: uuid.UUID,
    *,
    name: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> ShipmentMethod:
    """Rename, retire or reorder one. Only the fields actually sent are touched.

    Renaming does NOT rewrite the shipments that already carry the old name - they hold their own
    copy on purpose (see `packing_slips.shipment_method`), so this changes what future shipments
    will be offered and nothing else.
    """
    method = session.get(ShipmentMethod, method_id)
    if method is None:
        raise NotFoundError(f"Shipment method {method_id} not found")

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("A shipment method needs a name.", field="name")
        if name != method.name:
            _check_name_free(session, name, method.company)
            method.name = name
    if is_active is not None:
        method.is_active = is_active
    if sort_order is not None:
        method.sort_order = sort_order
    session.flush()
    return method


def delete_shipment_method(session: Session, method_id: uuid.UUID) -> None:
    """Remove a method from the list outright.

    Safe because no shipment references this row - each one snapshotted the name it shipped under -
    so deleting affects what can be picked next, never what was picked before. Retiring
    (`is_active = False`) is still the better move for a carrier that may come back; this is for a
    row that was a mistake.
    """
    method = session.get(ShipmentMethod, method_id)
    if method is None:
        raise NotFoundError(f"Shipment method {method_id} not found")
    session.delete(method)
    session.flush()


def _check_name_free(session: Session, name: str, company: str) -> None:
    """One spelling per carrier within a company, case-insensitively - "Flatbed" and "flatbed" are
    the same answer, and two companies each running their own "Our truck" are two rows (#637)."""
    existing = session.scalars(
        select(ShipmentMethod).where(func.lower(ShipmentMethod.name) == name.lower(), ShipmentMethod.company == company)
    ).first()
    if existing is not None:
        raise ConflictError(f"A shipment method named {existing.name} already exists", field="name")
