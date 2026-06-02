import uuid

import pytest

from app.errors import ValidationError
from app.models.vendor import Vendor
from app.repositories import po_repository


def _make_vendor(session, name: str = "Acme") -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}")
    session.add(v)
    session.flush()
    return v


def _line_item(order_as: str | None) -> dict:
    return {
        "hardware_category": "HINGE",
        "product_code": "AB123",
        "ordered_quantity": 1,
        "unit_cost": 12.50,
        "classification": None,
        "order_as": order_as,
    }


def test_create_po_succeeds_with_order_as(db_session):
    vendor = _make_vendor(db_session)
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
        vendor_id=vendor.id,
    )
    db_session.refresh(po)
    assert len(po.line_items) == 1
    assert po.line_items[0].order_as == "ML2010"


def test_create_po_strips_order_as_whitespace(db_session):
    vendor = _make_vendor(db_session)
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("  ML2010  ")],
        vendor_id=vendor.id,
    )
    db_session.refresh(po)
    assert po.line_items[0].order_as == "ML2010"


def test_create_po_rejects_missing_order_as(db_session):
    vendor = _make_vendor(db_session)
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(
            db_session,
            line_items=[_line_item(None)],
            vendor_id=vendor.id,
        )
    assert exc.value.field == "order_as"


def test_create_po_rejects_empty_order_as(db_session):
    vendor = _make_vendor(db_session)
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(
            db_session,
            line_items=[_line_item("")],
            vendor_id=vendor.id,
        )
    assert exc.value.field == "order_as"


def test_create_po_rejects_whitespace_only_order_as(db_session):
    vendor = _make_vendor(db_session)
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(
            db_session,
            line_items=[_line_item("   ")],
            vendor_id=vendor.id,
        )
    assert exc.value.field == "order_as"


def test_create_po_rejects_when_any_line_item_missing_order_as(db_session):
    vendor = _make_vendor(db_session)
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(
            db_session,
            line_items=[_line_item("ML2010"), _line_item(None)],
            vendor_id=vendor.id,
        )
    assert exc.value.field == "order_as"
