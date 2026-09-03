import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import Classification, PODocumentType, POOrigin, POStatus

if TYPE_CHECKING:
    from .hardware import HardwareItem


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_purchase_orders_project_status", "project_id", "status"),
        Index(
            "ix_purchase_orders_project_po_number",
            "project_id",
            "po_number",
            unique=True,
            postgresql_where="project_id IS NOT NULL AND po_number IS NOT NULL",
        ),
        # The jobless-PO number key. Scoped by company (#637): a GP PO number is unique within a
        # company, never across them, and TUCSH is a copy of UCSH down to its PONUMBERs - an unscoped
        # index made the second company's mirror of the same number a duplicate-key failure. The
        # project-scoped index above needs no such column: a project already belongs to one company.
        Index(
            "ix_purchase_orders_company_no_project_po_number",
            "company",
            "po_number",
            unique=True,
            postgresql_where="project_id IS NULL AND po_number IS NOT NULL",
        ),
        Index("ix_purchase_orders_request_number", "request_number", unique=True),
        # The GP identity of a mirrored PO, and the upsert key the sync converges on: one Nexus row
        # per (gp_company, po_number). A nexus-registered PO gets both stamped together at registration,
        # so it collapses onto its own mirror row rather than duplicating. DRAFTs carry neither and are
        # excluded by the po_number predicate (multiple NULLs never collide in a partial index).
        Index(
            "ix_purchase_orders_gp_company_po_number",
            "gp_company",
            "po_number",
            unique=True,
            postgresql_where="po_number IS NOT NULL",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The GP company that owns this PO - the tenant (#637). Distinct from `gp_company` below, which is
    # nullable and only recorded once a PO has actually been pushed to (or mirrored from) GP: a DRAFT
    # has a tenant from the moment it is raised, and every non-admin read filters on this.
    company: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    po_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # The PO-REQ-NNN a Nexus-drafted PO was raised from. Null on a mirrored (GP-origin) PO, which was
    # never requested through Nexus - the register falls back to po_number for the display id there.
    request_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Where this PO's authoritative record lives (gp-owned-po mirror). NEXUS: drafted here, pushed to
    # GP. GP: discovered in GP's tables by the mirror sync. Defaults NEXUS so every pre-existing PO,
    # and every draft/register path, keeps its meaning without change.
    origin: Mapped[POOrigin] = mapped_column(
        Enum(POOrigin, name="po_origin", create_constraint=True), nullable=False, default=POOrigin.NEXUS
    )
    # Last time the mirror sync wrote GP-derived fields onto this row. Null on a NEXUS PO the sync has
    # never touched; set on every mirrored row and on a NEXUS row once its mirror pass converges.
    gp_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    status: Mapped[POStatus] = mapped_column(Enum(POStatus, name="po_status", create_constraint=True), nullable=False)
    # GP cost code chosen per-PO (the issue #121 dropdown, 'phase-step-element' e.g. '210-200-2'),
    # applied to every job-cost line when pushed to GP. Null for stock POs / not-yet-pushed.
    cost_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # GP company this PO was created in (TUBC/TUCSH for the POC). Recorded at GP registration with the
    # returned po_number; a relay /receipt needs it to target the right company DB. Null until pushed.
    gp_company: Mapped[str | None] = mapped_column(String(15), nullable=True)
    # GP VENDORID (char 15) this PO was pushed to, picked live from PM00200 at push time. GP is the
    # only vendor authority - Nexus keeps no vendor records of its own (#200 dropped the sync'd
    # mirror, #509 the local contact table). vendor_name_snapshot is that same pick's display name,
    # frozen at push time since the GP vendor list isn't re-fetched just to render a PO. A DRAFT that
    # has not been registered yet has neither, and shows no vendor at all.
    gp_vendor_id: Mapped[str | None] = mapped_column(String(15), nullable=True)
    vendor_name_snapshot: Mapped[str | None] = mapped_column(String, nullable=True)
    # GP BUYERID (POP00101, char 15) picked in the Create/Register PO dialog and sent to GP at push
    # time. Persisted so the generated PO document (issue #230) can pre-fill the Buyer field.
    buyer_id: Mapped[str | None] = mapped_column(String(15), nullable=True)
    # Clerk user id of the person who raised this PO request - the import wizard user who finalized
    # it, or the caller of createDraftPo. Taken from the authenticated caller, never an argument
    # (#427). Used to address the rejected-draft notification back to the PO's originator; NULL on
    # every PO raised before the column existed.
    created_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    vendor_quote_number: Mapped[str | None] = mapped_column(String, nullable=True)
    # Issue #156: optional order-time dollar costs captured during the ordering action (Create PO
    # dialog), editable on the PO afterward. Null means "not entered"; 0 is a valid entered value.
    shipping_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    tariff_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Issue #216: the PM's requested date, captured at PO-request creation (import wizard) and
    # editable only while DRAFT. expected_delivery_date is the vendor's answer - it can only be
    # entered after the PO is GP-Registered (and before receiving starts).
    preferred_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_delivery_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    ordered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    line_items: Mapped[list["POLineItem"]] = relationship(back_populates="purchase_order")
    documents: Mapped[list["PODocument"]] = relationship(back_populates="purchase_order")
    document_data: Mapped["PODocumentData | None"] = relationship(back_populates="purchase_order", uselist=False)


class POLineItem(Base):
    __tablename__ = "po_line_items"
    __table_args__ = (
        Index("ix_po_line_items_po_id", "po_id"),
        CheckConstraint("ordered_quantity >= 1", name="ck_po_line_items_ordered_quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="ck_po_line_items_received_quantity_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[Classification | None] = mapped_column(
        Enum(Classification, name="classification", create_constraint=True),
        nullable=True,
    )
    ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Numeric(19,5) matches GP's own POP10110/POP30110.UNITCOST. The mirror writes GP's value here
    # verbatim, and Numeric(10,4) capped at 999,999.9999 - a single seven-figure GP line blew the
    # column and the whole PO's upsert failed with it. Nothing rounds to cents on the way in.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(19, 5), nullable=False)
    order_as: Mapped[str | None] = mapped_column(String, nullable=True)
    # GP POP10110.ORD this line maps to (16384, 32768, ...). Assigned positionally at create time
    # (the relay assigns ORD = line index * 16384); used to target the GP line on a relay /receipt.
    gp_line_ord: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="line_items")
    # Issue #232: the imported HardwareItem rows this PO line covers (HardwareItem.po_line_item_id).
    # viewonly, read-only - used only to derive the line's TITAN manufacturer for the vendor
    # suggestion. No DB change: the FK already lives on hardware_items.
    hardware_items: Mapped[list["HardwareItem"]] = relationship(
        "HardwareItem",
        primaryjoin="POLineItem.id == HardwareItem.po_line_item_id",
        # Order by created_at, id so the derived manufacturer (queries._po_line_item_manufacturer,
        # first non-null) matches mutations._resolve_line_manufacturers, which resolves the GP-written
        # value with the same ordering. Without this the two paths could pick different manufacturers
        # when items for one (category, product_code) disagree.
        order_by="HardwareItem.created_at, HardwareItem.id",
        viewonly=True,
    )


class PODocument(Base):
    __tablename__ = "po_documents"
    __table_args__ = (Index("ix_po_documents_po_id", "po_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    document_type: Mapped[PODocumentType] = mapped_column(
        Enum(PODocumentType, name="po_document_type", create_constraint=True), nullable=False
    )
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="documents")


class PODocumentData(Base):
    """The per-PO fields the generated supplier PO document (issue #230) needs but Nexus doesn't
    otherwise hold. GP computes some of these (freight/misc/tax), and others are only known at
    generate time (vendor mailing address, currency, resolved ship-to block); the PO user captures
    them once in the generate dialog and they persist here 1:1 with the PO so a re-generate pre-fills.
    """

    __tablename__ = "po_document_data"
    __table_args__ = (UniqueConstraint("po_id", name="uq_po_document_data_po_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    # Vendor mailing address block (GP holds it on the PM vendor card; Nexus doesn't mirror it).
    vendor_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Buyer display name for the document (defaults from PurchaseOrder.buyer_id, editable here).
    buyer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Document currency: 'CAD' or 'USD'. Drives the "$" vs "$US" money prefix.
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="CAD")
    # The resolved Ship-To block that prints on the document (from a warehouse, the project job site,
    # or custom text - resolved in the frontend and stored verbatim).
    ship_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Shipping method line for the header row (e.g. "LOCAL DELIVERY", "Supply by your freight company").
    shipping_method: Mapped[str | None] = mapped_column(String, nullable=True)
    # The vendor's quotation this PO is placed against. Renders as "Quote #" on the document (#507).
    quotation_number: Mapped[str | None] = mapped_column(String, nullable=True)
    # GP-computed totals lines Nexus can't derive without a relay read - captured from the user.
    freight: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    miscellaneous: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    # Label for the tax line (e.g. 'HST' or 'Taxes').
    tax_label: Mapped[str] = mapped_column(String, nullable=False, default="Taxes")
    # Tariff line for the document totals (issue #156). Prefills from PurchaseOrder.tariff_amount.
    tariff_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0"))
    # Overrides the header Required-by date (defaults to PurchaseOrder.expected_delivery_date).
    required_by_override: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Conditional boilerplate toggles (wood-door FSC note, USA tariff note, international customs block).
    include_fsc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    include_usa_tariff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    include_customs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="document_data")
