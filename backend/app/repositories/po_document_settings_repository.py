"""Repository for the single-row PO-document boilerplate settings (issue #230)."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.po_document_settings import PODocumentSettings

# Defaults seeded on first read, transcribed from the "PO user manual edit instructions guideline"
# doc on issue #230. The admin edits them afterward; this is only the starting point.
DEFAULT_TAX_NUMBERS = "UCH GST = 83813 6539 RT0001\nUCH BC PST = 1014-8674\nUCH HST# 728227356TZ0001"

DEFAULT_MANDATORY_BULLETS = [
    "UCH will not pay any invoice that has an amount above the original PO or most recent PO "
    "revisions unless UCH has given written/email approval.",
    "All orders for UCH BC branch, must have a minimum of 48 hours notice before shipment to our "
    "warehouse manager Darren Watson darrenw@ucsh.com or 604-235-2609",
    "Send all order confirmations, acknowledgements along with all invoices and statements to "
    "AP@ucsh.com please. If you can copy BCAckinv@ucsh.com on them also then that'd be appreciated, "
    "but if not that's okay.",
]

DEFAULT_SHIPPING_ACCOUNTS = [
    "CCE Express 604-516-8437",
    "K&H Dispatch 604-249-1555 on acct# 3268",
    "Purolator acct# 8202291",
    "UPS acct# 1167F1",
]

DEFAULT_SHIPPING_METHODS = [
    "LOCAL DELIVERY",
    "Supply by your freight company",
    "Supply by our freight company",
    "Pick up",
]

DEFAULT_CUSTOMS_BROKER_BLOCK = (
    "UC Hardware Inc. (UCH) Business Number 728227356 RT0001\n"
    "UCH Customs Broker:\n"
    "DB Schenker acct#: 1001093135\n"
    "6555 Northwest Drive\n"
    "Mississauga, ON Canada L4V 1K2\n"
    "P# 1-800-225-5229     F# 1-905-676-1235\n"
    "EMAIL: CA.SM.TOR.COAST-SHIPMENTS@DBSCHENKER.COM"
)

DEFAULT_FSC_NOTE = (
    "For FSC certified wood doors: include the FSC percentage and all associated certification "
    "information on this document and on all commercial invoices."
)

DEFAULT_USA_TARIFF_NOTE = (
    "Please include Tariff SA Code '25-0466B' for Health Care on all commercial invoices. You still "
    "need the normal HS Code for the product(s). The SA Code is separate from the normal HS Code for "
    "the product(s), not a replacement."
)

DEFAULT_USA_TARIFF_EFFECTIVE_UNTIL = date(2025, 10, 12)

DEFAULT_COMPANY_FROM_ADDRESS = "UC Hardware Inc.\nUnit 1 - 7100 Warden Avenue\nMarkham, ON    L3R 8B5"

DEFAULT_PAYMENT_TERMS = "Net 30"

DEFAULT_CONFIRM_WITH = "Greg Sutton"

DEFAULT_FOOTER_NOTES = (
    "Please notify us immediately if you are unable to ship complete by date specified.\n"
    "If you attach a copy of your invoice to the goods, please ensure that another copy is sent to "
    "our Accounts Payable dept. under another cover."
)

DEFAULT_SIGNATURE_NOTE = "Authorized Signature"


def get_settings(session: Session) -> PODocumentSettings:
    """Return the single boilerplate row, creating it with the guideline defaults on first read.

    The caller commits; a plain read that triggers the create still needs the row flushed so the
    resolver can serialize it, so we flush here and let the caller's commit persist it.
    """
    settings = session.scalars(select(PODocumentSettings).order_by(PODocumentSettings.created_at).limit(1)).first()
    if settings is not None:
        return settings

    settings = PODocumentSettings(
        id=uuid.uuid4(),
        tax_numbers=DEFAULT_TAX_NUMBERS,
        mandatory_bullets=list(DEFAULT_MANDATORY_BULLETS),
        shipping_accounts=list(DEFAULT_SHIPPING_ACCOUNTS),
        shipping_methods=list(DEFAULT_SHIPPING_METHODS),
        customs_broker_block=DEFAULT_CUSTOMS_BROKER_BLOCK,
        fsc_note=DEFAULT_FSC_NOTE,
        usa_tariff_note=DEFAULT_USA_TARIFF_NOTE,
        usa_tariff_effective_until=DEFAULT_USA_TARIFF_EFFECTIVE_UNTIL,
        company_from_address=DEFAULT_COMPANY_FROM_ADDRESS,
        payment_terms=DEFAULT_PAYMENT_TERMS,
        confirm_with=DEFAULT_CONFIRM_WITH,
        footer_notes=DEFAULT_FOOTER_NOTES,
        signature_note=DEFAULT_SIGNATURE_NOTE,
    )
    session.add(settings)
    session.flush()
    return settings


_UNSET = object()


def update_settings(
    session: Session,
    *,
    tax_numbers=_UNSET,
    mandatory_bullets=_UNSET,
    shipping_accounts=_UNSET,
    shipping_methods=_UNSET,
    customs_broker_block=_UNSET,
    fsc_note=_UNSET,
    usa_tariff_note=_UNSET,
    usa_tariff_effective_until=_UNSET,
    company_from_address=_UNSET,
    payment_terms=_UNSET,
    confirm_with=_UNSET,
    footer_notes=_UNSET,
    signature_note=_UNSET,
) -> PODocumentSettings:
    """Patch the singleton boilerplate row. Only fields that aren't the _UNSET sentinel are written,
    so a partial input leaves the rest intact. List fields (bullets/accounts) are dropped of blank
    entries; text fields are stored as-is (an admin may legitimately blank one out)."""
    settings = get_settings(session)

    if tax_numbers is not _UNSET:
        settings.tax_numbers = tax_numbers or ""
    if mandatory_bullets is not _UNSET:
        settings.mandatory_bullets = [b.strip() for b in (mandatory_bullets or []) if b and b.strip()]
    if shipping_accounts is not _UNSET:
        settings.shipping_accounts = [a.strip() for a in (shipping_accounts or []) if a and a.strip()]
    if shipping_methods is not _UNSET:
        settings.shipping_methods = [m.strip() for m in (shipping_methods or []) if m and m.strip()]
    if customs_broker_block is not _UNSET:
        settings.customs_broker_block = customs_broker_block or ""
    if fsc_note is not _UNSET:
        settings.fsc_note = fsc_note or ""
    if usa_tariff_note is not _UNSET:
        settings.usa_tariff_note = usa_tariff_note or ""
    if usa_tariff_effective_until is not _UNSET:
        settings.usa_tariff_effective_until = usa_tariff_effective_until
    if company_from_address is not _UNSET:
        settings.company_from_address = company_from_address or ""
    if payment_terms is not _UNSET:
        settings.payment_terms = payment_terms or ""
    if confirm_with is not _UNSET:
        settings.confirm_with = confirm_with or ""
    if footer_notes is not _UNSET:
        settings.footer_notes = footer_notes or ""
    if signature_note is not _UNSET:
        settings.signature_note = signature_note or ""

    session.flush()
    return settings
