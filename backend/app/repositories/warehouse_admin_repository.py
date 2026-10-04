"""Repository for Warehouse entity CRUD (the physical buildings, not inventory ops)."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.receive_draft import ReceiveDraft as ReceiveDraftModel
from app.models.shipping import ShipmentReturn as ShipmentReturnModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse import Warehouse

# What makes a warehouse OCCUPIED for the purpose of moving it to another company (#637), as
# (model, singular, plural). These are the four tables that carry `warehouse_id` and would be
# dragged into the new tenant by a move - stock on its shelves, project inventory on its shelves,
# counted-but-unapproved receives against it, and shipment returns that landed in it (#1411: a return
# whose units have since moved on is still the old company's record, and the delete already counts it).
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
    (ShipmentReturnModel, "shipment return", "shipment returns"),
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
    # Active buildings first (#1254), then the primary among them, then the oldest. A retired building
    # is not offered as a destination anywhere, so defaulting into it would park stock where nobody can
    # pick it; an active non-primary building beats a retired primary one. A retired building is still
    # the last resort rather than a failure, so creates never fail while any warehouse exists.
    wh_id = session.scalar(
        base.order_by(Warehouse.is_active.desc(), Warehouse.is_primary.desc(), Warehouse.created_at).limit(1)
    )
    if wh_id is None:
        raise ConflictError("No warehouse exists; cannot place inventory")
    return wh_id


def assert_usable_destination(
    session: Session, warehouse_id: uuid.UUID, *, company: str | None, field: str
) -> Warehouse:
    """A warehouse that units are about to be put into: it exists, it is active (#1374), and it is the
    owning company's own building (#1375).

    The company is compared directly, whatever the caller's scope: a UC NEXUS ADMIN is unscoped, so a
    by-id tenancy check passes them through, and a cross-company destination would leave a row whose
    warehouse and project (or PO) disagree about whose it is. `company` is the side the units belong
    to - the project's, the source warehouse's, or the PO's; None skips the comparison."""
    wh = session.get(Warehouse, warehouse_id)
    if wh is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    if not wh.is_active:
        raise ValidationError(f"Warehouse {wh.code} is no longer active; choose another warehouse.", field=field)
    if company is not None and wh.company != company:
        raise ValidationError(
            f"Warehouse {wh.code} belongs to another GP company; choose one of {company}'s warehouses.",
            field=field,
        )
    return wh


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _check_primary_active(*, is_primary: bool, is_active: bool) -> None:
    """A primary warehouse is always active (#1254).

    The primary building is where every receive with no warehouse chosen lands; a retired one is no
    longer offered as a destination anywhere, so stock booked into it could not be picked again."""
    if is_primary and not is_active:
        raise ValidationError(
            "The primary warehouse must stay active. Make another warehouse primary first.",
            field="is_active",
        )


def _check_name_unique(session: Session, name: str, *, company: str, exclude_id: uuid.UUID | None = None) -> None:
    """Names are unique within a company (#1256): another tenant's building does not block a name, and
    the refusal never reveals a building the caller cannot see."""
    stmt = (
        select(func.count())
        .select_from(Warehouse)
        .where(Warehouse.company == company, func.lower(Warehouse.name) == name.lower())
    )
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


def _check_code_unique(session: Session, code: str, *, company: str, exclude_id: uuid.UUID | None = None) -> None:
    """Codes are unique within a company (#1256): they are GP site codes, which each company's GP
    database assigns on its own."""
    stmt = (
        select(func.count())
        .select_from(Warehouse)
        .where(Warehouse.company == company, func.lower(Warehouse.code) == code.lower())
    )
    if exclude_id is not None:
        stmt = stmt.where(Warehouse.id != exclude_id)
    if session.scalar(stmt):
        raise ConflictError(f"A warehouse with code '{code}' already exists")


def _flush_refusing_duplicates(session: Session, *, name: str, code: str) -> None:
    """Flush inside a savepoint, so two saves of one name or code racing past the pre-checks get the
    same conflict the checks give rather than a masked server error (#1402)."""
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as e:
        constraint = getattr(getattr(e.orig, "diag", None), "constraint_name", None)
        if constraint == "uq_warehouses_company_lower_name":
            raise ConflictError(f"A warehouse named '{name}' already exists") from e
        if constraint == "uq_warehouses_company_lower_code":
            raise ConflictError(f"A warehouse with code '{code}' already exists") from e
        if constraint == "uq_warehouses_company_primary":
            # Only reachable for a company with no building to lock yet (#1431): two first buildings
            # both created primary at once.
            raise ValidationError(
                "Another warehouse was just made this company's primary; reload and try again",
                field="is_primary",
            ) from e
        raise


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
    _check_primary_active(is_primary=is_primary, is_active=is_active)
    _check_name_unique(session, name, company=company)
    _check_code_unique(session, code, company=company)

    if is_primary:
        _clear_primary(session, company=company)

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
    _flush_refusing_duplicates(session, name=name, code=code)
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
    _check_primary_active(
        is_primary=wh.is_primary if is_primary is None else is_primary,
        is_active=wh.is_active if is_active is None else is_active,
    )

    if company is not None:
        company = company.strip().upper()
        # Only an actual change is guarded or written. The admin form re-sends every field on every
        # save, so treating "the company it already has" as a move would make an occupied warehouse
        # un-editable in any other respect.
        if company and company != wh.company:
            if len(company) > 15:
                raise ValidationError("A GP company code is at most 15 characters", field="company")
            # The primary flag is read per company (#919), so a primary that moved would leave its old
            # company with none and give the new one two (#1411). Refused rather than quietly unflagged:
            # the old company's default receiving building is a choice for the admin to make first.
            if wh.is_primary:
                raise ValidationError(
                    f"Warehouse {wh.code} is the primary warehouse for {wh.company}; make another warehouse "
                    "primary before changing its company.",
                    field="company",
                )
            _assert_movable(session, wh)
            wh.company = company

    # Names and codes are unique per company (#1256), so they are checked against the company the
    # building ends up in - a move re-checks the name and code it keeps, not only an edited one.
    name = wh.name if name is None else name.strip()
    if not name:
        raise ValidationError("Warehouse name is required", field="name")
    # no_autoflush: a pending company move must not reach the database (and its per-company unique
    # index) before these checks have had the chance to refuse it with a field error.
    with session.no_autoflush:
        _check_name_unique(session, name, company=wh.company, exclude_id=warehouse_id)
    wh.name = name
    code = wh.code if code is None else code.strip()
    if not code:
        raise ValidationError("Warehouse code is required", field="code")
    if len(code) > 20:
        raise ValidationError("Warehouse code must be 20 characters or fewer", field="code")
    with session.no_autoflush:
        _check_code_unique(session, code, company=wh.company, exclude_id=warehouse_id)
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
            _clear_primary(session, company=wh.company, exclude_id=warehouse_id)
            wh.is_primary = True
        else:
            wh.is_primary = False

    _flush_refusing_duplicates(session, name=wh.name, code=wh.code)
    return wh


def delete_warehouse(session: Session, warehouse_id: uuid.UUID) -> None:
    wh = get_warehouse(session, warehouse_id)
    if wh.is_primary:
        raise ConflictError("Cannot delete the primary warehouse")

    # Every table whose warehouse_id points here without a cascade (#1229): a receive draft has no
    # ondelete and a shipment return is RESTRICT, so either used to fail the delete at flush as a
    # masked server error instead of saying what is in the way.
    for model, label in (
        (InventoryLocationModel, "inventory location"),
        (StockItemModel, "stock"),
        (ReceiveDraftModel, "receive draft"),
        (ShipmentReturnModel, "shipment return"),
    ):
        count = session.scalar(select(func.count()).select_from(model).where(model.warehouse_id == warehouse_id))
        if count and count > 0:
            raise ConflictError(f"Cannot delete warehouse: {count} {label} row(s) still reference it")

    session.delete(wh)
    session.flush()


def _clear_primary(session: Session, *, company: str, exclude_id: uuid.UUID | None = None) -> None:
    """Unflag the company's other primary warehouse. Scoped to `company` (#919): the flag is read per
    company (`get_primary_warehouse_id`), and clearing it everywhere made one company's new primary
    silently un-primary every other company's building.

    Serialized per company (#1431): two admins making different buildings primary at once each read the
    old primary unlocked, each unflagged it, and both new ones stayed primary. The company's warehouse
    rows are locked first, in id order, so the second waits and then clears the first one's choice.
    The clear is an UPDATE run now rather than at flush: the database holds one primary per company
    (uq_warehouses_company_primary), and a flush could write the new flag before this one is lifted."""
    with session.no_autoflush:
        session.execute(
            select(Warehouse.id).where(Warehouse.company == company).order_by(Warehouse.id).with_for_update()
        )
        stmt = (
            update(Warehouse)
            .where(Warehouse.is_primary.is_(True), Warehouse.company == company)
            .values(is_primary=False)
            .execution_options(synchronize_session="fetch")
        )
        if exclude_id is not None:
            stmt = stmt.where(Warehouse.id != exclude_id)
        session.execute(stmt)
