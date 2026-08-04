"""The catalog of non-schedule inventory: types, their attributes, and the items themselves (#454).

Read app/models/inventory_item_type.py first - the design turns on one decision, that a type's
`code` is what gets written into the pipeline's free-text `hardware_category`, and this module is
mostly the consequences of that decision:

  - **A code is claimed forever the moment it is used.** Creating a type whose code is already in
    play as a hardware category would silently adopt somebody else's stock into the type's catalog,
    so `create_item_type` refuses it. After creation the code is immutable, which is why there is no
    parameter to change it.
  - **Nothing is ever deleted once it can have been used.** A type or attribute retires to
    `is_active = False`. Rows on a shelf carry the code, not a foreign key, so a delete would leave
    inventory nobody can describe.

The one thing this module deliberately does NOT do is touch inventory. It describes products; how
many are in the building stays with `InventoryLocation` / `StockItem`, unchanged.
"""

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import (
    CustomInventoryItem,
    CustomInventoryItemValue,
    InventoryItemAttribute,
    InventoryItemType,
)
from app.models.purchase_order import POLineItem
from app.models.stock_item import StockItem

# --- types ---------------------------------------------------------------------------------


def get_item_types(session: Session, *, active_only: bool = False) -> list[InventoryItemType]:
    """The type list, in the order every screen shows it, with attributes eagerly loaded.

    `selectinload` is not optional here: `_item_type_to_type` walks `.attributes` for every row, and
    a lazy load would issue one SELECT per type on a list view (CLAUDE.md's N+1 rule).

    `active_only` is what a picker passes. The management screen leaves it off so a retired type is
    still visible to reactivate.
    """
    stmt = (
        select(InventoryItemType)
        .options(selectinload(InventoryItemType.attributes))
        .order_by(InventoryItemType.sort_order.asc(), InventoryItemType.name.asc())
    )
    if active_only:
        stmt = stmt.where(InventoryItemType.is_active.is_(True))
    return list(session.scalars(stmt).unique().all())


def get_item_type(session: Session, type_id: uuid.UUID) -> InventoryItemType:
    """One type with its attributes, re-read rather than served from the identity map.

    `populate_existing` is what makes "add an attribute, then return the type" correct. Adding one
    goes through this function first (to check the type exists), which loads `.attributes` as it
    stood *before* the insert; without this flag the eager loader would leave that already-populated
    collection alone on the way back out, and the caller would be handed a type missing the very
    attribute it just created. A commit in between happens to hide it - expiry forces the reload -
    but that makes the answer depend on whether somebody committed, which is not a property this
    function should have.
    """
    item_type = session.scalars(
        select(InventoryItemType)
        .options(selectinload(InventoryItemType.attributes))
        .where(InventoryItemType.id == type_id)
        .execution_options(populate_existing=True)
    ).first()
    if item_type is None:
        raise NotFoundError(f"Inventory item type {type_id} not found")
    return item_type


def create_item_type(session: Session, *, name: str, code: str | None = None, sort_order: int = 0):
    """Add a type. `code` defaults to one derived from the name, and can never be changed afterwards.

    The derivation is deliberately dumb - uppercase, non-alphanumerics to underscores - because the
    code is going to appear on inventory screens beside HINGE and LOCK, and a user typing "Door
    Sweeps" should get DOOR_SWEEPS rather than something they cannot predict.
    """
    name = (name or "").strip()
    if not name:
        raise ValidationError("An inventory item type needs a name.", field="name")

    code = _normalize_code(code or name)
    if not code:
        raise ValidationError("An inventory item type needs a code.", field="code")

    _check_type_name_free(session, name)
    _check_code_free(session, code)

    item_type = InventoryItemType(
        id=uuid.uuid4(),
        code=code,
        name=name,
        is_active=True,
        sort_order=sort_order,
    )
    session.add(item_type)
    session.flush()
    return item_type


def update_item_type(
    session: Session,
    type_id: uuid.UUID,
    *,
    name: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> InventoryItemType:
    """Rename, retire or reorder a type. `code` is absent by design.

    A rename changes a label. Changing the code would change what future purchase orders stamp into
    `hardware_category`, splitting one type's stock across two categories with no way to find the
    rows already stamped - so the API simply does not offer it.
    """
    item_type = session.get(InventoryItemType, type_id)
    if item_type is None:
        raise NotFoundError(f"Inventory item type {type_id} not found")

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("An inventory item type needs a name.", field="name")
        if name.lower() != item_type.name.lower():
            _check_type_name_free(session, name)
        item_type.name = name
    if is_active is not None:
        item_type.is_active = is_active
    if sort_order is not None:
        item_type.sort_order = sort_order
    session.flush()
    return item_type


# --- attributes ----------------------------------------------------------------------------


def create_attribute(session: Session, *, type_id: uuid.UUID, name: str, sort_order: int = 0):
    """Add one of the things worth recording about every item of a type."""
    name = (name or "").strip()
    if not name:
        raise ValidationError("An attribute needs a name.", field="name")
    get_item_type(session, type_id)
    _check_attribute_name_free(session, type_id, name)

    attribute = InventoryItemAttribute(
        id=uuid.uuid4(),
        type_id=type_id,
        name=name,
        is_active=True,
        sort_order=sort_order,
    )
    session.add(attribute)
    session.flush()
    return attribute


def update_attribute(
    session: Session,
    attribute_id: uuid.UUID,
    *,
    name: str | None = None,
    is_active: bool | None = None,
    sort_order: int | None = None,
) -> InventoryItemAttribute:
    """Rename, retire or reorder an attribute.

    Values follow a rename automatically - they are keyed by this row's id, not by its name - and
    survive a retirement, so an attribute switched off by mistake comes back with its answers intact.
    """
    attribute = session.get(InventoryItemAttribute, attribute_id)
    if attribute is None:
        raise NotFoundError(f"Inventory item attribute {attribute_id} not found")

    if name is not None:
        name = name.strip()
        if not name:
            raise ValidationError("An attribute needs a name.", field="name")
        if name.lower() != attribute.name.lower():
            _check_attribute_name_free(session, attribute.type_id, name)
        attribute.name = name
    if is_active is not None:
        attribute.is_active = is_active
    if sort_order is not None:
        attribute.sort_order = sort_order
    session.flush()
    return attribute


# --- items ---------------------------------------------------------------------------------


def get_items(
    session: Session,
    *,
    type_id: uuid.UUID | None = None,
    product_code_contains: str | None = None,
    active_only: bool = False,
) -> list[CustomInventoryItem]:
    """The catalog, filtered the way the two callers need it.

    The PO dialog's picker passes a type and `active_only`; the management screen passes a type and
    nothing else. Both walk `.values` and `.item_type` per row, so both are eagerly loaded.
    """
    stmt = (
        select(CustomInventoryItem)
        .options(
            selectinload(CustomInventoryItem.values),
            selectinload(CustomInventoryItem.item_type),
        )
        .order_by(CustomInventoryItem.product_code.asc())
    )
    if type_id is not None:
        stmt = stmt.where(CustomInventoryItem.type_id == type_id)
    if active_only:
        stmt = stmt.where(CustomInventoryItem.is_active.is_(True))
    if product_code_contains:
        stmt = stmt.where(CustomInventoryItem.product_code.ilike(f"%{product_code_contains.strip()}%"))
    return list(session.scalars(stmt).unique().all())


def get_item(session: Session, item_id: uuid.UUID) -> CustomInventoryItem:
    """One catalogued product with its values. `populate_existing` for the reason `get_item_type`
    carries it: a write that re-reads its own subject has to see what it just wrote."""
    item = session.scalars(
        select(CustomInventoryItem)
        .options(
            selectinload(CustomInventoryItem.values),
            selectinload(CustomInventoryItem.item_type),
        )
        .where(CustomInventoryItem.id == item_id)
        .execution_options(populate_existing=True)
    ).first()
    if item is None:
        raise NotFoundError(f"Custom inventory item {item_id} not found")
    return item


def create_item(
    session: Session,
    *,
    type_id: uuid.UUID,
    product_code: str,
    description: str | None = None,
    values: list[dict] | None = None,
) -> CustomInventoryItem:
    """Catalog a product. `values` is [{attribute_id, value}] and may cover any subset of the type's
    attributes - an item whose fire rating is not known yet is still worth having a code for."""
    product_code = (product_code or "").strip()
    if not product_code:
        raise ValidationError("An item needs a product code.", field="product_code")
    get_item_type(session, type_id)

    existing = session.scalars(
        select(CustomInventoryItem).where(
            CustomInventoryItem.type_id == type_id,
            func.lower(CustomInventoryItem.product_code) == product_code.lower(),
        )
    ).first()
    if existing is not None:
        raise ConflictError(
            f"An item with product code {existing.product_code} already exists for this type",
            field="product_code",
        )

    item = CustomInventoryItem(
        id=uuid.uuid4(),
        type_id=type_id,
        product_code=product_code,
        description=(description or "").strip() or None,
        is_active=True,
    )
    session.add(item)
    session.flush()
    _apply_values(session, item, values or [])
    session.flush()
    return item


def update_item(
    session: Session,
    item_id: uuid.UUID,
    *,
    description: str | None = None,
    is_active: bool | None = None,
    values: list[dict] | None = None,
) -> CustomInventoryItem:
    """Edit a catalogued product. `product_code` is absent for the same reason a type's code is:
    inventory already carries it.

    `values`, when sent, is a full replace over the attributes it names - a blank value clears that
    attribute rather than storing an empty answer, so the grid's "clear this cell" is expressible.
    Attributes it does not name are left alone.
    """
    item = get_item(session, item_id)

    if description is not None:
        item.description = description.strip() or None
    if is_active is not None:
        item.is_active = is_active
    if values is not None:
        _apply_values(session, item, values)
    session.flush()
    session.refresh(item)
    return item


# --- internals -----------------------------------------------------------------------------


def _apply_values(session: Session, item: CustomInventoryItem, values: list[dict]) -> None:
    """Upsert the answers this call names, deleting the ones it blanks.

    Validates that each attribute belongs to the item's own type. Without that check a caller could
    hang a frame's fire rating off a consumable, and the grid would never show it - the column is
    not there - so the bad row would just sit in the table.
    """
    if not values:
        return

    existing = {v.attribute_id: v for v in item.values}
    valid_attribute_ids = {
        a_id
        for (a_id,) in session.execute(
            select(InventoryItemAttribute.id).where(InventoryItemAttribute.type_id == item.type_id)
        ).all()
    }

    for entry in values:
        attribute_id = entry.get("attribute_id")
        if attribute_id is None:
            continue
        attribute_id = attribute_id if isinstance(attribute_id, uuid.UUID) else uuid.UUID(str(attribute_id))
        if attribute_id not in valid_attribute_ids:
            raise ValidationError("That attribute does not belong to this item's type.", field="attribute_id")

        text = (entry.get("value") or "").strip()
        current = existing.get(attribute_id)
        if not text:
            if current is not None:
                session.delete(current)
                item.values.remove(current)
            continue
        if current is None:
            new_value = CustomInventoryItemValue(
                id=uuid.uuid4(),
                item_id=item.id,
                attribute_id=attribute_id,
                value=text,
            )
            session.add(new_value)
            item.values.append(new_value)
            existing[attribute_id] = new_value
        else:
            current.value = text


def _normalize_code(raw: str) -> str:
    """ "Door Sweeps" -> DOOR_SWEEPS. Predictable enough that a user can guess what their type will
    be called on the inventory screen before they press save."""
    cleaned = [c if c.isalnum() else "_" for c in (raw or "").strip().upper()]
    code = "".join(cleaned).strip("_")
    while "__" in code:
        code = code.replace("__", "_")
    return code[:50]


def _check_type_name_free(session: Session, name: str) -> None:
    existing = session.scalars(
        select(InventoryItemType).where(func.lower(InventoryItemType.name) == name.lower())
    ).first()
    if existing is not None:
        raise ConflictError(f"An inventory item type named {existing.name} already exists", field="name")


def _check_attribute_name_free(session: Session, type_id: uuid.UUID, name: str) -> None:
    existing = session.scalars(
        select(InventoryItemAttribute).where(
            InventoryItemAttribute.type_id == type_id,
            func.lower(InventoryItemAttribute.name) == name.lower(),
        )
    ).first()
    if existing is not None:
        raise ConflictError(f"This type already has an attribute named {existing.name}", field="name")


def _check_code_free(session: Session, code: str) -> None:
    """Refuse a code that is already in play - as another type's, or as a hardware category on stock.

    The second half is the one that matters. Hardware categories come off the TITAN schedule and are
    never registered anywhere, so the only way to know HINGE is taken is to look at what has been
    bought and received. A type created on a code already carrying hardware would show every hinge in
    the building as an uncatalogued item of that type, which reads as data corruption to the person
    looking at the screen.
    """
    existing = session.scalars(select(InventoryItemType).where(InventoryItemType.code == code)).first()
    if existing is not None:
        raise ConflictError(f"The code {code} is already used by the type {existing.name}", field="code")

    in_use = session.execute(
        select(1).where(
            or_(
                select(POLineItem.id).where(func.upper(POLineItem.hardware_category) == code).exists(),
                select(InventoryLocation.id).where(func.upper(InventoryLocation.hardware_category) == code).exists(),
                select(StockItem.id).where(func.upper(StockItem.hardware_category) == code).exists(),
            )
        )
    ).first()
    if in_use is not None:
        raise ConflictError(
            f"The code {code} is already in use as a hardware category on existing stock or purchase orders",
            field="code",
        )
