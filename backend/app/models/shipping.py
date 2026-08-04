import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import PullRequestItemType, ReturnDisposition, ShipmentStatus

if TYPE_CHECKING:
    from .shipment_container import ShipmentContainer


class PackingSlip(Base):
    """One shipment out of the warehouse, and the Delivery Request that goes with it (#447).

    The header below is the paper form UC Hardware's shipping department fills in and the
    construction site signs off on: when it is being picked up and delivered, who is shipping it and
    how to reach them, where it is being collected from, the questions the site has to answer before
    a truck is worth sending, and the two contacts. It is written once at confirm time and printed
    from here every time afterwards, so a Delivery Request reprinted a year later says exactly what
    the driver was handed.

    Every header field is nullable. The form is filled in by a human against whatever the site has
    told them, and a blank on the paper is a real answer ("nobody asked about a forklift"), not a
    validation failure - so the schema records blanks rather than refusing them.

    `status` is the journey (see ShipmentStatus): the header is editable only while SCHEDULED, and
    the lifecycle stamps below are the record of who moved it and when.
    """

    __tablename__ = "packing_slips"
    __table_args__ = (Index("ix_packing_slips_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    shipped_by: Mapped[str] = mapped_column(String, nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    status: Mapped[ShipmentStatus] = mapped_column(
        Enum(
            ShipmentStatus,
            name="shipment_status",
            create_constraint=True,
        ),
        nullable=False,
    )

    # --- Delivery Request header ---------------------------------------------------------------
    # Dates the truck is expected, as days rather than instants: nobody schedules a pickup to the
    # minute, and printing a timezone-shifted timestamp on a form would be actively misleading.
    pickup_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    shipper_email: Mapped[str | None] = mapped_column(String, nullable=True)
    shipper_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    # Snapshot of the warehouse address, not a foreign key: the warehouse record can be edited or
    # retired years after the truck left, and the form has to keep printing where it was sent.
    pickup_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    # How the load travelled (#451). A snapshot of the chosen ShipmentMethod's name, not a foreign
    # key, for the same reason `pickup_location` beside it is a snapshot: the method can be renamed
    # or retired years later and the reprint has to keep saying what the driver was told.
    shipment_method: Mapped[str | None] = mapped_column(String, nullable=True)
    carrier_tag_bol: Mapped[str | None] = mapped_column(String, nullable=True)
    weight_lbs: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    special_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The site questions. Free text rather than booleans on purpose - the answers that come back are
    # "yes until 3pm" and "gate 4, ask for Dave", and squashing those to a checkbox loses the part
    # the driver needs.
    gate_number: Mapped[str | None] = mapped_column(String, nullable=True)
    forklift_onsite: Mapped[str | None] = mapped_column(String, nullable=True)
    material_coming_back: Mapped[str | None] = mapped_column(String, nullable=True)
    site_material_included: Mapped[str | None] = mapped_column(String, nullable=True)
    construction_temp_keys: Mapped[str | None] = mapped_column(String, nullable=True)
    extra_frame_anchors: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor_contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor_contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    ucsh_contact_name: Mapped[str | None] = mapped_column(String, nullable=True)
    ucsh_contact_phone: Mapped[str | None] = mapped_column(String, nullable=True)
    sales_order_number: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Lifecycle stamps ------------------------------------------------------------------------
    # Who confirmed each leg and when. The actor is the Clerk-authenticated caller (#427), never
    # something the client named.
    picked_up_at: Mapped[datetime | None] = mapped_column(nullable=True)
    picked_up_by: Mapped[str | None] = mapped_column(String, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    delivered_by: Mapped[str | None] = mapped_column(String, nullable=True)

    items: Mapped[list["PackingSlipItem"]] = relationship(back_populates="packing_slip")

    # The containers this shipment went out in (#451), empty for a slip cut before containers existed
    # or by any path that did not build one. `items` stays the record of WHAT shipped; this is how it
    # was physically arranged, which is what the Delivery Request has to print for the person
    # unloading it.
    containers: Mapped[list["ShipmentContainer"]] = relationship(
        "ShipmentContainer",
        back_populates="packing_slip",
        order_by="ShipmentContainer.created_at",
    )


class PackingSlipItem(Base):
    __tablename__ = "packing_slip_items"
    __table_args__ = (
        Index("ix_packing_slip_items_packing_slip", "packing_slip_id"),
        CheckConstraint("quantity >= 1", name="ck_packing_slip_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slips.id"), nullable=False)
    item_type: Mapped[PullRequestItemType] = mapped_column(
        Enum(
            PullRequestItemType,
            name="pull_request_item_type",
            create_constraint=True,
        ),
        nullable=False,
    )
    opening_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opening_items.id"), nullable=True)
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    # Door leaf this shipped line is for (#311): OPENING_ITEM rows stamp from the OpeningItem.leaf.
    # Immutable record on the slip. Null = legacy / loose.
    leaf: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # Where the leaf was going, snapshotted off the OpeningItem at confirm time (#452). The Delivery
    # Request prints these after the opening number, and a reprint years later has to say what the
    # driver's copy said - so they are copied onto the slip rather than followed back to the
    # OpeningItem, which can be re-placed or re-assembled long afterwards. Null on a LOOSE line
    # (fungible hardware has no placement) and on rows written before #452.
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    floor: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    packing_slip: Mapped["PackingSlip"] = relationship(back_populates="items")


class ShipmentReturn(Base):
    """A shipment came back from site. Header mirrors PackingSlip; only loose lines are returnable."""

    __tablename__ = "shipment_returns"
    __table_args__ = (Index("ix_shipment_returns_packing_slip", "packing_slip_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    packing_slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slips.id"), nullable=False)
    # Where the returned stock physically lands (new inventory / stock rows are created here).
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False)
    returned_by: Mapped[str] = mapped_column(String, nullable=False)
    returned_at: Mapped[datetime] = mapped_column(nullable=False)
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    items: Mapped[list["ShipmentReturnItem"]] = relationship(back_populates="shipment_return")


class ShipmentReturnItem(Base):
    """One returned loose-hardware line, routed by its disposition into project inventory or stock."""

    __tablename__ = "shipment_return_items"
    __table_args__ = (
        Index("ix_shipment_return_items_return", "shipment_return_id"),
        Index("ix_shipment_return_items_packing_slip_item", "packing_slip_item_id"),
        CheckConstraint("quantity >= 1", name="ck_shipment_return_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_return_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shipment_returns.id"), nullable=False)
    packing_slip_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("packing_slip_items.id"), nullable=False)
    disposition: Mapped[ReturnDisposition] = mapped_column(
        Enum(ReturnDisposition, name="return_disposition", create_constraint=True),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    opening_number: Mapped[str | None] = mapped_column(String, nullable=True)
    rma_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    resulting_inventory_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_locations.id"), nullable=True
    )
    resulting_stock_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stock_items.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    shipment_return: Mapped["ShipmentReturn"] = relationship(back_populates="items")
