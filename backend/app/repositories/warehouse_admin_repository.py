"""Repository for Warehouse entity CRUD (the physical buildings, not inventory ops)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.receive_draft import ReceiveDraft as ReceiveDraftModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse import Warehouse

# What makes a warehouse OCCUPIED for the purpose of moving it to another company (#637), as
# (model, singular, plural). These are the three tables that carry `warehouse_id` and would be
# dragged into the new tenant by a move - stock on its shelves, project inventory on its shelves, and
# counted-but-unapproved receives against it.
#
# `warehouse_locations` is deliberately NOT here: a defined layout is a description of the building,
# not something in it, and an empty rack moves harmlessly with the walls.
#
# Rows are counted whatever their quantity. A fully-emptied StockItem is kept on purpose - it stays
# the origin of any InventoryLocation allocated out of it - so it is still a row carrying this
# warehouse's id, and moving it would put one company's origin record under another company's roof.
_OCCUPANCY = (
    (StockItemModel, "stock item", "stock items"),
    (InventoryLocationModel, "inventory row", "inventory rows"),
    (ReceiveDraftModel, "receive draft", "receive drafts"),
)


def list_warehouses(session: Session, *, include_inactive: bool = True, company: str | None = None) -> list[Warehouse]:
    stmt = select(Warehouse).order_by(Warehouse.is_primary.desc(), Warehouse.name)
    if company is not None:
        stmt = stmt.where(Warehouse.company == company)
    if not include_inactive:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    return list(session.scalars(stmt).all())


def get_warehouse(session: Session, warehouse_id: uuid.UUID) -> Warehouse:
    wh = session.get(Warehouse, warehouse_id)
    if wh is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    return wh


def find_warehouse(session: Session, warehouse_id: uuid.UUID) -> Warehouse | None:
    """None-safe lookup for the nullable `warehouse` query (get_warehouse raises)."""
    return session.get(Warehouse, warehouse_id)


def get_primary_warehouse_id(session: Session, *, company: str | None = None) -> uuid.UUID:
    """The default warehouse new rows fall back to when none is otherwise determined.

    `company` narrows it to that tenant's buildings (#637), which is what every caller that knows the
    company should pass: `is_primary` is a single global flag, so without it a UCSH receive with no
    explicit warehouse would land in TUBC's primary building."""
    base = select(Warehouse.id)
    if company is not None:
        base = base.where(Warehouse.company == company)
    wh_id = session.scalar(base.where(Warehouse.is_primary.is_(True)).order_by(Warehouse.created_at).limit(1))
    if wh_id is None:
        # No primary flagged: fall back to the oldest warehouse so creates never fail.
        wh_id = session.scalar(base.order_by(Warehouse.created_at).limit(1))
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


def describe_occupancy(session: Session, warehouse_id: uuid.UUID) -> list[str]:
    """What is in a warehouse, as countable English phrases ("12 stock items", "1 receive draft").

    Empty when nothing references it. One COUNT per table and no rows loaded - this runs on an admin
    edit, but a warehouse at company scale holds hundreds of thousands of inventory rows and none of
    them need to be materialized to say how many there are.
    """
    described: list[str] = []
    for model, singular, plural in _OCCUPANCY:
        count = session.scalar(select(func.count()).select_from(model).where(model.warehouse_id == warehouse_id)) or 0
        if count:
            described.append(f"{count} {singular if count == 1 else plural}")
    return described


def _assert_movable(session: Session, wh: Warehouse) -> None:
    """Refuse to move an OCCUPIED warehouse to another company (#637).

    Everything in the building takes its tenant from the building, so a move re-tenants all of it at
    once - and the project inventory in it belongs to projects of the OLD company, which would leave
    a row whose project and warehouse disagree about whose it is. There is no repair for that from
    the admin screen, so the move is refused while anything is in there rather than performed and
    then reported.

    A ValidationError on `company` rather than a Conflict: the admin sent a field, the field is the
    problem, and the dialog can anchor the message to it. The message names what is in the way,
    because "cannot move" without a count sends someone hunting through four screens.
    """
    occupying = describe_occupancy(session, wh.id)
    if occupying:
        raise ValidationError(
            f"Warehouse {wh.code} holds {', '.join(occupying)}; move or clear them before changing its company.",
            field="company",
        )


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
    company: str,
    address: str | None = None,
    city: str | None = None,
    province: str | None = None,
    postal_code: str | None = None,
    is_primary: bool = False,
    is_active: bool = True,
) -> Warehouse:
    name = (name or "").strip()
    code = (code or "").strip()
    company = (company or "").strip().upper()
    if not name:
        raise ValidationError("Warehouse name is required", field="name")
    if not code:
        raise ValidationError("Warehouse code is required", field="code")
    if len(code) > 20:
        raise ValidationError("Warehouse code must be 20 characters or fewer", field="code")
    if not company:
        raise ValidationError("A GP company is required for a warehouse", field="company")
    _check_name_unique(session, name)
    _check_code_unique(session, code)

    if is_primary:
        _clear_primary(session)

    wh = Warehouse(
        id=uuid.uuid4(),
        company=company,
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
    company: str | None = None,
    address: str | None = None,
    city: str | None = None,
    province: str | None = None,
    postal_code: str | None = None,
    is_primary: bool | None = None,
    is_active: bool | None = None,
) -> Warehouse:
    """Update the editable fields of one warehouse. Any argument left as None is not changed.

    `company` moves the building to another GP company (#637), normalized the way every other company
    value in this codebase is - trimmed and uppercased. A blank one is treated as "not sent" rather
    than as a clear, because the column is NOT NULL: a building always belongs to somebody. Sending
    the company it already has is a no-op, so an edit form that round-trips every field never trips
    the occupancy guard. An actual CHANGE is refused while anything is in the building - see
    `_assert_movable`. Admin-only, like the mutation.
    """
    wh = get_warehouse(session, warehouse_id)

    if company is not None:
        company = company.strip().upper()
        # Only an actual change is guarded or written. The admin form re-sends every field on every
        # save, so treating "the company it already has" as a move would make an occupied warehouse
        # un-editable in any other respect.
        if company and company != wh.company:
            if len(company) > 15:
                raise ValidationError("A GP company code is at most 15 characters", field="company")
            _assert_movable(session, wh)
            wh.company = company

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
