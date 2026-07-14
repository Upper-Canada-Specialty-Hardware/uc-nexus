import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PODocumentSettings(Base):
    """Admin-configurable boilerplate for the generated supplier PO document (issue #230).

    A single-row table: the PO document is the same company-wide letterhead/legal text on every
    supplier PO, so there is one row that the admin edits. Read via a get-or-create helper that seeds
    the guideline-doc defaults on first access, so a fresh DB (or one after a migration downgrade) is
    never missing the row.
    """

    __tablename__ = "po_document_settings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The three UCH tax-registration lines printed under the totals (GST / BC PST / HST). Free text,
    # one per line.
    tax_numbers: Mapped[str] = mapped_column(Text, nullable=False)
    # The mandatory bullet paragraphs added below the total and above the signature on every PO.
    mandatory_bullets: Mapped[list] = mapped_column(JSON, nullable=False)
    # Courier / freight account numbers (informational block).
    shipping_accounts: Mapped[list] = mapped_column(JSON, nullable=False)
    # The selectable shipping-method options for the generate dialog's dropdown.
    shipping_methods: Mapped[list] = mapped_column(JSON, nullable=False)
    # The customs-broker + business-number block, included on international shipments.
    customs_broker_block: Mapped[str] = mapped_column(Text, nullable=False)
    # Wood-door FSC certification note (conditional, toggled per PO).
    fsc_note: Mapped[str] = mapped_column(Text, nullable=False)
    # USA health-care tariff SA-code note (conditional, toggled per PO). effective_until is the date the
    # instruction lapses - shown to the PO user next to the toggle; not auto-enforced.
    usa_tariff_note: Mapped[str] = mapped_column(Text, nullable=False)
    usa_tariff_effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The company from-address block printed at the top of the document.
    company_from_address: Mapped[str] = mapped_column(Text, nullable=False)
    # Company-standard header-row defaults (rarely change; admin-editable).
    payment_terms: Mapped[str] = mapped_column(String, nullable=False, default="Net 30")
    confirm_with: Mapped[str] = mapped_column(String, nullable=False, default="")
    # The fixed footer under the signature line.
    footer_notes: Mapped[str] = mapped_column(Text, nullable=False)
    signature_note: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
