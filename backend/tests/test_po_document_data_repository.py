"""Tests for per-PO PODocumentData upsert + buyer_id persistence (issue #230)."""

import uuid
from decimal import Decimal

import pytest

from app.errors import NotFoundError
from app.repositories import po_repository


def _make_po(session, *, buyer_id: str | None = None):
    return po_repository.create_po(
        session,
        line_items=[
            {
                "hardware_category": "HINGE",
                "product_code": "AB123",
                "ordered_quantity": 1,
                "unit_cost": 12.50,
                "classification": None,
                "order_as": "ML2010",
            }
        ],
        buyer_id=buyer_id,
    )


def test_create_po_persists_buyer_id(db_session):
    po = _make_po(db_session, buyer_id="  mira  ")
    db_session.refresh(po)
    assert po.buyer_id == "mira"


def test_upsert_creates_document_data(db_session):
    po = _make_po(db_session)

    data = po_repository.upsert_po_document_data(
        db_session,
        po.id,
        vendor_address="50 West Drive\nBrampton ON",
        buyer_name="Norm Jung",
        currency="USD",
        ship_to="Affix ship-to label",
        quotation_number="0038515-R1",
        freight=100,
        miscellaneous=25.5,
        tax_amount=200,
        tax_label="HST",
        include_fsc=True,
    )

    assert data.po_id == po.id
    assert data.vendor_address == "50 West Drive\nBrampton ON"
    assert data.buyer_name == "Norm Jung"
    assert data.currency == "USD"
    assert data.freight == Decimal("100.00")
    assert data.miscellaneous == Decimal("25.50")
    assert data.tax_amount == Decimal("200.00")
    assert data.tax_label == "HST"
    assert data.include_fsc is True
    assert data.include_usa_tariff is False


def test_upsert_updates_existing_row_in_place(db_session):
    po = _make_po(db_session)
    first = po_repository.upsert_po_document_data(db_session, po.id, buyer_name="First", freight=10)
    second = po_repository.upsert_po_document_data(db_session, po.id, buyer_name="Second", freight=20)

    assert first.id == second.id  # 1:1, updated not duplicated
    assert second.buyer_name == "Second"
    assert second.freight == Decimal("20.00")
    assert po_repository.get_po_document_data(db_session, po.id).id == second.id


def test_upsert_coerces_invalid_currency_to_cad(db_session):
    po = _make_po(db_session)
    data = po_repository.upsert_po_document_data(db_session, po.id, currency="gbp")
    assert data.currency == "CAD"


def test_upsert_blank_text_becomes_none(db_session):
    po = _make_po(db_session)
    data = po_repository.upsert_po_document_data(db_session, po.id, vendor_address="   ", quotation_number="")
    assert data.vendor_address is None
    assert data.quotation_number is None


def test_upsert_blank_tax_label_keeps_default(db_session):
    po = _make_po(db_session)
    data = po_repository.upsert_po_document_data(db_session, po.id, tax_label="   ")
    assert data.tax_label == "Taxes"


def test_upsert_rejects_unknown_po(db_session):
    with pytest.raises(NotFoundError):
        po_repository.upsert_po_document_data(db_session, uuid.uuid4(), buyer_name="Nobody")


def test_upsert_persists_tariff_amount(db_session):
    # Issue #156: tariff is a money field like freight/misc/tax - coerced to Decimal, defaults to 0.
    po = _make_po(db_session)
    data = po_repository.upsert_po_document_data(db_session, po.id, tariff_amount=42.75)
    assert data.tariff_amount == Decimal("42.75")

    untouched = po_repository.upsert_po_document_data(db_session, po.id, buyer_name="Second")
    assert untouched.tariff_amount == Decimal("42.75")


def test_get_document_data_none_when_never_saved(db_session):
    po = _make_po(db_session)
    assert po_repository.get_po_document_data(db_session, po.id) is None
