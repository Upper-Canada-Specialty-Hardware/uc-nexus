"""Repository for Warehouse entity CRUD (the physical buildings, not inventory ops)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse import Warehouse


def list_warehouses(session: Session, *, include_inactive: bool = True) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.is_primary.desc(), Warehouse.name)
    if not include_inactive:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(session.scalars(stmt).all())


def get_warehouse(session: Session, warehouse_id: uuid.UUID) -> Warehouse:
    wh = session.get(Warehouse, warehouse_id)
    if wh is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    return wh


def get_primary_warehouse_id(session: Session) -> uuid.UUID:
    """The default warehouse new rows fall back to when none is otherwise determined."""
    wh_id = session.scalar(
        select(Warehouse.id).where(Warehouse.is_primary.is_(True)).order_by(Warehouse.created_at).limit(1)
    )
    if wh_id is None:
        # No primary flagged: fall back to the oldest warehouse so creates never fail.
        wh_id = session.scalar(select(Warehouse.id).order_by(Warehouse.created_at).limit(1))
    if wh_id is None:
        raise ConflictError("No warehouse exists; cannot place inventory")
    return wh_id


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_name_unique(session: Session, name: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(func.count()).select_from(Warehouse).where(func.lower(Warehouse.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(Warehouse.id != exclude_id)
    if session.scalar(stmt):
        raise ConflictError(f"A warehouse named '{name}' already exists")


def _check_code_unique(session: Session, code: str, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(func.count()).select_from(Warehouse).where(func.lower(Warehouse.code) == code.lower())
    if exclude_id is not None:
        stmt = stmt.where(Warehouse.id != exclude_id)
    if session.scalar(stmt):
        raise ConflictError(f"A warehouse with code '{code}' already exists")


def create_warehouse(
    session: Session,
    *,
    name: str,
    code: str,
    address: str | None = None,
    city: str | None = None,
    province: str | None = None,
    postal_code: str | None = None,
    is_primary: bool = False,
    is_active: bool = True,
) -> Warehouse:
    name = (name or "").strip()
    code = (code or "").strip()
    if not name:
        raise ValidationError("Warehouse name is required", field="name")
    if not code:
        raise ValidationError("Warehouse code is required", field="code")
    if len(code) > 20:
        raise ValidationError("Warehouse code must be 20 characters or fewer", field="code")
    _check_name_unique(session, name)
    _check_code_unique(session, code)

    if is_primary:
        _clear_primary(session)

    wh = Warehouse(
        id=uuid.uuid4(),
        name=name,
        code=code,
        address=_norm(address),
        city=_norm(city),
        province=_norm(province),
        postal_code=_norm(postal_code),
        is_primary=is_primary,
        is_active=is_active,
    )
    session.add(wh)
    session.flush()
    return wh


def update_warehouse(
    session: Session,
    warehouse_id: uuid.UUID,
    *,
    name: str | None = None,
    code: str | None = None,
    address: str | None = None,
    city: str | None = None,
    province: str | None = None,
    postal_code: str | None = None,
    is_primary: bool | None = None,
    is_active: bool | None = None,
) -> Warehouse:
    wh = get_warehouse(session, warehouse_id)

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("Warehouse name is required", field="name")
        _check_name_unique(session, name, exclude_id=warehouse_id)
        wh.name = name
    if code is not None:
        code = code.strip()
        if not code:
            raise ValidationError("Warehouse code is required", field="code")
        if len(code) > 20:
            raise ValidationError("Warehouse code must be 20 characters or fewer", field="code")
        _check_code_unique(session, code, exclude_id=warehouse_id)
        wh.code = code
    if address is not None:
        wh.address = _norm(address)
    if city is not None:
        wh.city = _norm(city)
    if province is not None:
        wh.province = _norm(province)
    if postal_code is not None:
        wh.postal_code = _norm(postal_code)
    if is_active is not None:
        wh.is_active = is_active
    if is_primary is not None:
        if is_primary:
            _clear_primary(session, exclude_id=warehouse_id)
            wh.is_primary = True
        else:
            wh.is_primary = False

    session.flush()
    return wh


def delete_warehouse(session: Session, warehouse_id: uuid.UUID) -> None:
    wh = get_warehouse(session, warehouse_id)
    if wh.is_primary:
        raise ConflictError("Cannot delete the primary warehouse")

    for model, label in (
        (InventoryLocationModel, "inventory location"),
        (StockItemModel, "stock"),
        (OpeningItemModel, "opening item"),
    ):
        count = session.scalar(select(func.count()).select_from(model).where(model.warehouse_id == warehouse_id))
        if count and count > 0:
            raise ConflictError(f"Cannot delete warehouse: {count} {label} row(s) still reference it")

    session.delete(wh)
    session.flush()


def _clear_primary(session: Session, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(Warehouse).where(Warehouse.is_primary.is_(True))
    if exclude_id is not None:
        stmt = stmt.where(Warehouse.id != exclude_id)
    for wh in session.scalars(stmt).all():
        wh.is_primary = False
