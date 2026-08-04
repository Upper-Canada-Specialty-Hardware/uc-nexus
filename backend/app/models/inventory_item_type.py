"""Inventory that is not schedule hardware: frames, specialties, consumables (#454).

Everything UC Nexus tracks today arrives off a TITAN hardware schedule, where an item's identity is
`opening -> door leaf -> hardware`. Frames, specialties and consumables have no place in that
hierarchy - they are what the business calls "other" inventory - and yet they travel the same
pipeline: somebody buys them, the warehouse receives them into stock, they sit on a shelf, and they
ship to site. What they additionally need is description, and the schedule is not there to supply it:
a frame is characterised by things like its fire rating and handing, a consumable by nothing of the
sort. So each type carries its own set of **custom attributes**, defined by warehouse staff, with
free-text values.

The design decision that keeps this small: **the type rides in `hardware_category`.** Every table in
the pipeline - `po_line_items`, `receive_draft_line_items`, `inventory_locations`, `stock_items`,
`inventory_reservations`, pull lines, shipping lines - keys an item on the free-text pair
`(hardware_category, product_code)`. An `InventoryItemType` therefore owns an immutable uppercase
`code` (FRAME, SPECIALTY, CONSUMABLE), that code is what a purchase order line writes into
`hardware_category`, and it flows untouched through receiving, put-away, picking and shipping. None
of those tables learn anything new, and a frame stays as fungible as a hinge - which is correct:
identity here belongs to the product code, not to the physical piece.

That is also why `code` is immutable while `name` is not. `name` is a label on a screen and renaming
"Specialties" costs nothing; `code` is stamped into inventory rows that this table has no way to
find, let alone rewrite, so changing it would orphan the stock it was stamped on.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class InventoryItemType(Base):
    """A category of non-schedule inventory - Frames, Specialties, Consumables - and its attribute set.

    A row rather than an enum because the business adds kinds of stock the way it adds vendors, and
    "add a fourth type" should not be a deploy. The three the issue names are seeded by the migration
    so the list is never empty on a fresh database.

    `code` is what reaches inventory (see the module docstring) and never changes after creation.
    `name` is the label, free to be corrected. Retiring a type is `is_active = False`: stock received
    under its code is still on a shelf and still has to read correctly, so there is no delete path.
    """

    __tablename__ = "inventory_item_types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_inventory_item_types_code"),
        UniqueConstraint("name", name="uq_inventory_item_types_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Uppercase, immutable, and what gets written to `hardware_category` on every row this type's
    # items produce downstream.
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    attributes: Mapped[list["InventoryItemAttribute"]] = relationship(
        back_populates="item_type",
        order_by="InventoryItemAttribute.sort_order, InventoryItemAttribute.name",
    )


class InventoryItemAttribute(Base):
    """One thing worth recording about every item of a type - "Fire Rating", "Handing", "Size".

    Scoped to its type on purpose: the issue is explicit that frames' attributes are separate from
    specialties', separate from consumables'. Nothing is shared, and nothing has to be, because the
    set is small and warehouse staff maintain it themselves.

    Values are free text (`CustomInventoryItemValue.value`) - no types, no dropdowns. The user asked
    for exactly that, and a typed attribute system is the sort of thing that gets built ahead of
    knowing which attributes people actually keep.

    Retiring one is `is_active = False`. The values already recorded against it stay in the table:
    they are keyed by attribute id, so reactivating brings them back rather than losing them.
    """

    __tablename__ = "inventory_item_attributes"
    __table_args__ = (
        UniqueConstraint("type_id", "name", name="uq_inventory_item_attributes_type_name"),
        Index("ix_inventory_item_attributes_type_id", "type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_item_types.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    item_type: Mapped["InventoryItemType"] = relationship(back_populates="attributes")


class CustomInventoryItem(Base):
    """A catalogued non-schedule product: a type, a product code, and its attribute values.

    This is a **catalog** row, not a stock row. It says "FR-101 is a frame, 90-minute rated,
    left-handed"; how many of them are in the building is `InventoryLocation` / `StockItem`, exactly
    as for hardware. The link between the two is the `(type.code, product_code)` pair - there is
    deliberately no foreign key from inventory back to here, because inventory must keep working for
    a code whose catalog entry is later retired, and because adding one would mean touching the
    fungibility key that the whole receiving/picking chain is built on.

    Attribute values live here rather than on the physical rows because they describe the product,
    not the piece: every FR-101 in the rack is 90-minute rated. A genuinely one-off piece is its own
    product code, which is how the warehouse already thinks about it.
    """

    __tablename__ = "custom_inventory_items"
    __table_args__ = (
        UniqueConstraint("type_id", "product_code", name="uq_custom_inventory_items_type_code"),
        Index("ix_custom_inventory_items_type_id", "type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_item_types.id", ondelete="CASCADE"), nullable=False
    )
    # What a PO line and every inventory row downstream will carry as `product_code`.
    product_code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    item_type: Mapped["InventoryItemType"] = relationship()
    values: Mapped[list["CustomInventoryItemValue"]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
    )


class CustomInventoryItemValue(Base):
    """One item's answer for one attribute. Free text, because that is what was asked for.

    Keyed by attribute id rather than by attribute name, so renaming "Fire Rating" to "Fire rating"
    carries every value with it instead of stranding them.
    """

    __tablename__ = "custom_inventory_item_values"
    __table_args__ = (
        UniqueConstraint("item_id", "attribute_id", name="uq_custom_inventory_item_values_item_attr"),
        Index("ix_custom_inventory_item_values_item_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("custom_inventory_items.id", ondelete="CASCADE"), nullable=False
    )
    attribute_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("inventory_item_attributes.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    item: Mapped["CustomInventoryItem"] = relationship(back_populates="values")
    attribute: Mapped["InventoryItemAttribute"] = relationship()
