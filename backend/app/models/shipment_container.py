import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import ShipmentContainerType

if TYPE_CHECKING:
    from .shipping import PackingSlip

# A skid is loaded by hand and a stack taller than this is not safe to strap or to lift. It is a
# physical limit on the object, not a policy, which is why it lives beside the model rather than in
# a settings table somebody could raise without buying a bigger skid.
MAX_LEAVES_PER_SKID = 30


class ShipmentContainer(Base):
    """A physical thing the warehouse loads: a skid, a door cart, a box, an envelope, a bundle (#451).

    Shipping out used to go straight from "these units are ship-ready" to a packing slip, with the
    organising done on the floor and recorded nowhere. It is real work - a skid has to be stacked in
    an order the site can unload, and a shipment is several containers that get built up over days -
    so it is an entity rather than a step inside the confirm dialog.

    `packing_slip_id` is what makes a container open or shipped. Null means it is still being built
    and can be renamed, added to and emptied; once a shipment is confirmed the id is stamped and the
    container is history, exactly like the slip's own items. That single column is also why an
    "open" container needs no status enum: the question is only ever "has this left".

    Nothing here moves inventory. The hardware left inventory when its pull was picked (#367); this
    is a record of how what is already staged is arranged for the truck.
    """

    __tablename__ = "shipment_containers"
    __table_args__ = (
        Index("ix_shipment_containers_project_slip", "project_id", "packing_slip_id"),
        # One name per open container per project, so "Skid 1" cannot be built twice at once. Shipped
        # ones are excluded: next month's Skid 1 is a different skid, and refusing the name because a
        # shipment used it in March would make the numbering unusable.
        Index(
            "uq_shipment_containers_open_name",
            "project_id",
            "name",
            unique=True,
            postgresql_where="packing_slip_id IS NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    container_type: Mapped[ShipmentContainerType] = mapped_column(
        Enum(ShipmentContainerType, name="shipment_container_type", create_constraint=True),
        nullable=False,
    )
    # What the floor calls it - "Skid 1", "Door Cart 3". Operator-chosen rather than generated: the
    # label goes on the physical thing in marker, and a uuid does not.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    packing_slip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packing_slips.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    items: Mapped[list["ShipmentContainerItem"]] = relationship(
        back_populates="container", cascade="all, delete-orphan"
    )
    packing_slip: Mapped["PackingSlip | None"] = relationship("PackingSlip", back_populates="containers")


class ShipmentContainerItem(Base):
    """One thing placed in a container, and where in the stack it sits (#451).

    Mirrors `PackingSlipItem` on purpose: confirming a shipment copies these onto the slip, so a
    shape that could not become a slip line would be a container that cannot ship.

    `position` is the stacking order, and it is only meaningful on a skid or a door cart - the two
    that are loaded in a sequence somebody has to reverse at the far end. Position 1 is the FIRST
    one loaded, which on a skid is the bottom of the stack. A box of loose hardware has an arbitrary
    order and simply carries whatever positions it was given.
    """

    __tablename__ = "shipment_container_items"
    __table_args__ = (
        Index("ix_shipment_container_items_container", "shipment_container_id"),
        CheckConstraint("quantity >= 1", name="ck_shipment_container_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_container_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipment_containers.id", ondelete="CASCADE"), nullable=False
    )
    # Null on loose stock with no opening attribution (#451), same as everywhere else in the chain.
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    container: Mapped["ShipmentContainer"] = relationship(back_populates="items")
