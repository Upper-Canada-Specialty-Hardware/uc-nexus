import logging
import uuid
from datetime import datetime

import pytest

from app.errors import ValidationError
from app.models.enums import HardwareItemState
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.vendor import Vendor
from app.repositories import po_repository
from app.schemas import mutations


def _make_vendor(session, name: str = "Acme") -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}")
    session.add(v)
    session.flush()
    return v


class _NoCloseSession:
    """Wrap the test session as a context manager that does NOT close it (the db_session fixture owns
    its lifecycle), so a monkeypatched _prepare_* runs against the test's uncommitted transaction
    instead of opening a fresh, empty connection via the real SessionLocal()."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _use_test_session(monkeypatch, db_session) -> None:
    monkeypatch.setattr(mutations, "SessionLocal", lambda: _NoCloseSession(db_session))


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _add_hardware_item(session, project, *, hardware_category, product_code, manufacturer, created_at=None):
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"OP-{uuid.uuid4().hex[:4]}")
    session.add(opening)
    session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=hardware_category,
        product_code=product_code,
        item_quantity=1,
        manufacturer=manufacturer,
        state=HardwareItemState.AVAILABLE,
    )
    if created_at is not None:
        hi.created_at = created_at
    session.add(hi)
    session.flush()
    return hi


def _po_line(hardware_category, product_code, order_as="ML2010") -> dict:
    return {
        "hardware_category": hardware_category,
        "product_code": product_code,
        "ordered_quantity": 1,
        "unit_cost": 12.5,
        "classification": None,
        "order_as": order_as,
    }


# --- issue #233: _prepare_create_po resolves each line's manufacturer from matching HardwareItems ------


def test_prepare_create_po_attaches_manufacturer_per_line(monkeypatch, db_session):
    project = _make_project(db_session)
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")
    _add_hardware_item(db_session, project, hardware_category="LOCK", product_code="LK-200", manufacturer="SARGENT")
    _use_test_session(monkeypatch, db_session)

    payload = mutations._prepare_create_po(
        project_id=project.id,
        vendor_id=None,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code="210-200-2",
        po_number=None,
        line_items_data=[_po_line("HINGE", "HG-100"), _po_line("LOCK", "LK-200")],
    )

    assert [line["manufacturer"] for line in payload["lines"]] == ["SCHLAGE", "SARGENT"]


def test_prepare_create_po_leaves_manufacturer_blank_without_a_hardware_match(monkeypatch, db_session):
    project = _make_project(db_session)
    # a hardware item exists, but not for this line's category + code
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")
    _use_test_session(monkeypatch, db_session)

    payload = mutations._prepare_create_po(
        project_id=project.id,
        vendor_id=None,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code="210-200-2",
        po_number=None,
        line_items_data=[_po_line("LOCK", "LK-999")],
    )

    assert payload["lines"][0]["manufacturer"] is None


def test_prepare_create_po_disagreeing_items_take_first_non_null_and_log(monkeypatch, db_session, caplog):
    project = _make_project(db_session)
    # same category + code across three openings: a null, then two conflicting manufacturers. created_at
    # is set explicitly so "first non-null" is deterministic (SCHLAGE precedes SARGENT).
    _add_hardware_item(
        db_session, project, hardware_category="HINGE", product_code="HG-100",
        manufacturer=None, created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    _add_hardware_item(
        db_session, project, hardware_category="HINGE", product_code="HG-100",
        manufacturer="SCHLAGE", created_at=datetime(2026, 1, 1, 0, 0, 1),
    )
    _add_hardware_item(
        db_session, project, hardware_category="HINGE", product_code="HG-100",
        manufacturer="SARGENT", created_at=datetime(2026, 1, 1, 0, 0, 2),
    )
    _use_test_session(monkeypatch, db_session)

    with caplog.at_level(logging.WARNING):
        payload = mutations._prepare_create_po(
            project_id=project.id,
            vendor_id=None,
            gp_vendor_id="GPV1",
            buyer_id="mira",
            cost_code="210-200-2",
            po_number=None,
            line_items_data=[_po_line("HINGE", "HG-100")],
        )

    assert payload["lines"][0]["manufacturer"] == "SCHLAGE"
    assert any("manufacturer disagreement" in r.message for r in caplog.records)


def test_prepare_create_po_without_a_project_sends_no_manufacturer(monkeypatch, db_session):
    _use_test_session(monkeypatch, db_session)

    payload = mutations._prepare_create_po(
        project_id=None,
        vendor_id=None,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code=None,
        po_number=None,
        line_items_data=[_po_line("HINGE", "HG-100")],
    )

    assert payload["lines"][0]["manufacturer"] is None


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
