"""Queries and mutations for the non-schedule inventory catalog (#454).

A separate module rather than more of warehouse.py because the catalog is not a warehouse operation:
it is maintained by warehouse staff, read by the PO dialog when a buyer orders a frame, and read
again by the inventory screens to describe what is on the shelf. Its own module keeps those three
consumers looking at one place.

Every root field below needs its entry in `app/auth_policy.py` - the schema extension refuses a
field that has none (#423).
"""

import uuid
from datetime import datetime

import strawberry

from app.database import SessionLocal
from app.repositories import custom_items_repository


@strawberry.type
class InventoryItemAttribute:
    """One attribute definition on a type - "Fire Rating", "Handing"."""

    id: strawberry.ID
    type_id: strawberry.ID
    name: str
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class InventoryItemType:
    """A kind of non-schedule inventory, and the attributes its items are described by (#454).

    `code` is the important field and the one nothing can change: it is what a purchase order line
    writes into `hardwareCategory`, so it is how the type is recognisable on every inventory,
    receiving and shipping screen downstream.
    """

    id: strawberry.ID
    code: str
    name: str
    is_active: bool
    sort_order: int
    attributes: list[InventoryItemAttribute]
    created_at: datetime
    updated_at: datetime


@strawberry.type
class CustomInventoryItemValue:
    """One item's answer for one attribute. `attributeName` is carried along so a caller can render
    a row without joining the type's attribute list itself."""

    attribute_id: strawberry.ID
    attribute_name: str
    value: str


@strawberry.type
class CustomInventoryItem:
    """A catalogued product: what it is, what it is called, and how it is described.

    `hardwareCategory` is the item's type code, spelled the way the rest of the system spells it.
    Together with `productCode` it is exactly the pair a PO line, an inventory row and a shipping
    line carry - which is the point: a caller never has to know the type is stored separately.
    """

    id: strawberry.ID
    type_id: strawberry.ID
    hardware_category: str
    type_name: str
    product_code: str
    description: str | None
    is_active: bool
    values: list[CustomInventoryItemValue]
    created_at: datetime
    updated_at: datetime


@strawberry.input
class CustomInventoryItemValueInput:
    attribute_id: strawberry.ID
    # Blank clears the attribute rather than storing an empty answer.
    value: str


def _attribute_to_type(a) -> InventoryItemAttribute:
    return InventoryItemAttribute(
        id=strawberry.ID(str(a.id)),
        type_id=strawberry.ID(str(a.type_id)),
        name=a.name,
        is_active=a.is_active,
        sort_order=a.sort_order,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


def _item_type_to_type(t) -> InventoryItemType:
    return InventoryItemType(
        id=strawberry.ID(str(t.id)),
        code=t.code,
        name=t.name,
        is_active=t.is_active,
        sort_order=t.sort_order,
        attributes=[_attribute_to_type(a) for a in t.attributes],
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _item_to_type(i) -> CustomInventoryItem:
    return CustomInventoryItem(
        id=strawberry.ID(str(i.id)),
        type_id=strawberry.ID(str(i.type_id)),
        hardware_category=i.item_type.code,
        type_name=i.item_type.name,
        product_code=i.product_code,
        description=i.description,
        is_active=i.is_active,
        values=[
            CustomInventoryItemValue(
                attribute_id=strawberry.ID(str(v.attribute_id)),
                attribute_name=v.attribute.name,
                value=v.value,
            )
            for v in i.values
        ],
        created_at=i.created_at,
        updated_at=i.updated_at,
    )


def _values_input(values) -> list[dict]:
    return [{"attribute_id": str(v.attribute_id), "value": v.value} for v in values]


@strawberry.type
class CustomItemQueries:
    @strawberry.field
    def inventory_item_types(self, info: strawberry.Info, active_only: bool = False) -> list[InventoryItemType]:
        """The types and their attributes (#454). Pickers pass `activeOnly`; the management screen
        does not, so a retired type stays visible to reactivate."""
        with SessionLocal() as session:
            return [
                _item_type_to_type(t) for t in custom_items_repository.get_item_types(session, active_only=active_only)
            ]

    @strawberry.field
    def custom_inventory_items(
        self,
        info: strawberry.Info,
        type_id: strawberry.ID | None = None,
        product_code_contains: str | None = None,
        active_only: bool = False,
    ) -> list[CustomInventoryItem]:
        """The catalog, optionally narrowed to one type (#454)."""
        with SessionLocal() as session:
            rows = custom_items_repository.get_items(
                session,
                type_id=uuid.UUID(str(type_id)) if type_id else None,
                product_code_contains=product_code_contains,
                active_only=active_only,
            )
            return [_item_to_type(i) for i in rows]


@strawberry.type
class CustomItemMutations:
    @strawberry.mutation
    def create_inventory_item_type(
        self,
        info: strawberry.Info,
        name: str,
        code: str | None = None,
        sort_order: int = 0,
    ) -> InventoryItemType:
        """Add a type of non-schedule inventory (#454).

        `code` defaults to one derived from the name and is fixed from here on - it is what reaches
        `hardwareCategory` on every row this type's items produce. A code already in use, whether by
        another type or as a hardware category on existing stock, is refused."""
        with SessionLocal() as session:
            item_type = custom_items_repository.create_item_type(session, name=name, code=code, sort_order=sort_order)
            session.commit()
            return _item_type_to_type(custom_items_repository.get_item_type(session, item_type.id))

    @strawberry.mutation
    def update_inventory_item_type(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        name: str | None = None,
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> InventoryItemType:
        """Rename, retire or reorder a type (#454). There is no way to change its code: stock
        already on a shelf carries that code and cannot be found from here to be rewritten."""
        with SessionLocal() as session:
            type_id = uuid.UUID(str(id))
            custom_items_repository.update_item_type(
                session, type_id, name=name, is_active=is_active, sort_order=sort_order
            )
            session.commit()
            return _item_type_to_type(custom_items_repository.get_item_type(session, type_id))

    @strawberry.mutation
    def create_inventory_item_attribute(
        self,
        info: strawberry.Info,
        type_id: strawberry.ID,
        name: str,
        sort_order: int = 0,
    ) -> InventoryItemType:
        """Add an attribute to a type, and return the type so the caller re-renders its whole
        column set from one round trip (#454)."""
        with SessionLocal() as session:
            parsed = uuid.UUID(str(type_id))
            custom_items_repository.create_attribute(session, type_id=parsed, name=name, sort_order=sort_order)
            session.commit()
            return _item_type_to_type(custom_items_repository.get_item_type(session, parsed))

    @strawberry.mutation
    def update_inventory_item_attribute(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        name: str | None = None,
        is_active: bool | None = None,
        sort_order: int | None = None,
    ) -> InventoryItemType:
        """Rename, retire or reorder an attribute (#454). Values follow a rename and survive a
        retirement - they are keyed by the attribute's id, not its name."""
        with SessionLocal() as session:
            attribute = custom_items_repository.update_attribute(
                session, uuid.UUID(str(id)), name=name, is_active=is_active, sort_order=sort_order
            )
            type_id = attribute.type_id
            session.commit()
            return _item_type_to_type(custom_items_repository.get_item_type(session, type_id))

    @strawberry.mutation
    def create_custom_inventory_item(
        self,
        info: strawberry.Info,
        type_id: strawberry.ID,
        product_code: str,
        description: str | None = None,
        # `| None = None`, not `strawberry.field(default_factory=list)`: that helper is for input-type
        # ATTRIBUTES, and on a resolver argument it renders as required non-null in the SDL while
        # handing the resolver the StrawberryField object itself when a caller omits it.
        values: list[CustomInventoryItemValueInput] | None = None,
    ) -> CustomInventoryItem:
        """Catalog a product (#454). The values may cover any subset of the type's attributes."""
        with SessionLocal() as session:
            item = custom_items_repository.create_item(
                session,
                type_id=uuid.UUID(str(type_id)),
                product_code=product_code,
                description=description,
                values=_values_input(values or []),
            )
            item_id = item.id
            session.commit()
            return _item_to_type(custom_items_repository.get_item(session, item_id))

    @strawberry.mutation
    def update_custom_inventory_item(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        description: str | None = None,
        is_active: bool | None = None,
        values: list[CustomInventoryItemValueInput] | None = None,
    ) -> CustomInventoryItem:
        """Edit a catalogued product (#454).

        `productCode` is not editable for the same reason a type's code is not: inventory rows
        already carry it. A blank value clears that attribute."""
        with SessionLocal() as session:
            item_id = uuid.UUID(str(id))
            custom_items_repository.update_item(
                session,
                item_id,
                description=description,
                is_active=is_active,
                values=_values_input(values) if values is not None else None,
            )
            session.commit()
            return _item_to_type(custom_items_repository.get_item(session, item_id))
