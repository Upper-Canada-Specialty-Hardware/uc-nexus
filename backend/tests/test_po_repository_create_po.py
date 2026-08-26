import logging
import uuid
from datetime import datetime

import pytest

from app.errors import ValidationError
from app.models.enums import HardwareItemState, POStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.repositories import po_repository
from app.schemas import po as po_schema
from app.services.gp_po import build_create_po_payload


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


# --- issue #233: _resolve_line_manufacturers resolves each line's manufacturer from HardwareItems ------


def test_resolve_line_manufacturers_attaches_per_line(db_session):
    project = _make_project(db_session)
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")
    _add_hardware_item(db_session, project, hardware_category="LOCK", product_code="LK-200", manufacturer="SARGENT")

    resolved = po_schema._resolve_line_manufacturers(
        db_session, project.id, [_po_line("HINGE", "HG-100"), _po_line("LOCK", "LK-200")]
    )

    assert resolved == ["SCHLAGE", "SARGENT"]


def test_resolve_line_manufacturers_blank_without_a_hardware_match(db_session):
    project = _make_project(db_session)
    # a hardware item exists, but not for this line's category + code
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")

    resolved = po_schema._resolve_line_manufacturers(db_session, project.id, [_po_line("LOCK", "LK-999")])

    assert resolved == [None]


def test_resolve_line_manufacturers_disagreeing_items_take_first_non_null_and_log(db_session, caplog):
    project = _make_project(db_session)
    # same category + code across three openings: a null, then two conflicting manufacturers. created_at
    # is set explicitly so "first non-null" is deterministic (SCHLAGE precedes SARGENT).
    _add_hardware_item(
        db_session,
        project,
        hardware_category="HINGE",
        product_code="HG-100",
        manufacturer=None,
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    _add_hardware_item(
        db_session,
        project,
        hardware_category="HINGE",
        product_code="HG-100",
        manufacturer="SCHLAGE",
        created_at=datetime(2026, 1, 1, 0, 0, 1),
    )
    _add_hardware_item(
        db_session,
        project,
        hardware_category="HINGE",
        product_code="HG-100",
        manufacturer="SARGENT",
        created_at=datetime(2026, 1, 1, 0, 0, 2),
    )

    with caplog.at_level(logging.WARNING):
        resolved = po_schema._resolve_line_manufacturers(db_session, project.id, [_po_line("HINGE", "HG-100")])

    assert resolved == ["SCHLAGE"]
    assert any("manufacturer disagreement" in r.message for r in caplog.records)


def test_resolve_line_manufacturers_without_a_project_sends_none(db_session):
    resolved = po_schema._resolve_line_manufacturers(db_session, None, [_po_line("HINGE", "HG-100")])
    assert resolved == [None]


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
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
    )
    db_session.refresh(po)
    assert len(po.line_items) == 1
    assert po.line_items[0].order_as == "ML2010"


def test_create_po_strips_order_as_whitespace(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("  ML2010  ")],
    )
    db_session.refresh(po)
    assert po.line_items[0].order_as == "ML2010"


# #563: order_as is optional when the line has a product_code - GP's item number falls back to it
# (services/gp_po.py). A blank order_as persists as NULL rather than being rejected.


def test_create_po_allows_missing_order_as(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item(None)],
    )
    db_session.refresh(po)
    assert po.line_items[0].order_as is None


def test_create_po_allows_empty_order_as(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("")],
    )
    db_session.refresh(po)
    assert po.line_items[0].order_as is None


def test_create_po_allows_whitespace_only_order_as(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("   ")],
    )
    db_session.refresh(po)
    assert po.line_items[0].order_as is None


def test_create_po_allows_line_item_missing_order_as(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010"), _line_item(None)],
    )
    db_session.refresh(po)
    assert {li.order_as for li in po.line_items} == {"ML2010", None}


def test_create_po_still_rejects_when_order_as_and_product_code_both_missing(db_session):
    # #563 relaxed the requirement to order_as OR product_code, not neither.
    line = {
        "hardware_category": "HINGE",
        "product_code": "  ",
        "ordered_quantity": 1,
        "unit_cost": 12.50,
        "classification": None,
        "order_as": None,
    }
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(db_session, line_items=[line])
    assert exc.value.field == "order_as"


def test_create_po_blank_order_as_payload_falls_back_to_product_code(db_session):
    # The GP payload uses product_code as the item number when order_as is blank.
    payload = build_create_po_payload(
        vendor_gp_id="GPV1",
        vendor_contact_name=None,
        buyer_id="BUYER1",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(None)],
    )
    assert payload["lines"][0]["item_number"] == "AB123"


# --- issue #216: status-gated delivery dates ------------------------------------------------------


def test_update_po_preferred_date_only_on_draft(db_session):
    from datetime import date as date_cls

    from app.errors import InvalidStateTransitionError
    from app.models.enums import POStatus

    po = po_repository.create_po(db_session, line_items=[_line_item("ML2010")])
    db_session.flush()

    po_repository.update_po(db_session, po.id, preferred_delivery_date=date_cls(2026, 8, 1))
    assert po.preferred_delivery_date == date_cls(2026, 8, 1)

    # Expected is rejected while DRAFT
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, expected_delivery_date=date_cls(2026, 8, 15))

    # After GP registration, expected is allowed and preferred is locked
    po.status = POStatus.GP_REGISTERED
    db_session.flush()
    po_repository.update_po(db_session, po.id, expected_delivery_date=date_cls(2026, 8, 15))
    assert po.expected_delivery_date == date_cls(2026, 8, 15)
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, preferred_delivery_date=date_cls(2026, 8, 2))


# --- issue #156: optional order-time shipping cost + tariff -------------------------------------


def test_create_po_persists_shipping_cost_and_tariff(db_session):
    from decimal import Decimal

    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
        shipping_cost=125.5,
        tariff_amount=0,
    )
    db_session.refresh(po)
    assert po.shipping_cost == Decimal("125.50")
    # 0 is a valid entered value, distinct from "not entered" (null)
    assert po.tariff_amount == Decimal("0")


def test_create_po_defaults_shipping_cost_and_tariff_to_null(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
    )
    db_session.refresh(po)
    assert po.shipping_cost is None
    assert po.tariff_amount is None


def test_create_po_rejects_negative_shipping_cost(db_session):
    with pytest.raises(ValidationError) as exc:
        po_repository.create_po(
            db_session,
            line_items=[_line_item("ML2010")],
            shipping_cost=-1,
        )
    assert exc.value.field == "shipping_cost"


def test_update_po_rejects_negative_tariff(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
    )
    db_session.flush()
    with pytest.raises(ValidationError) as exc:
        po_repository.update_po(db_session, po.id, tariff_amount=-0.01)
    assert exc.value.field == "tariff_amount"


def test_update_po_sets_clears_and_leaves_shipping_cost_and_tariff(db_session):
    from decimal import Decimal

    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
    )
    db_session.flush()

    po_repository.update_po(db_session, po.id, shipping_cost=75.25, tariff_amount=10)
    assert po.shipping_cost == Decimal("75.25")
    assert po.tariff_amount == Decimal("10")

    # Omitted (_UNSET) leaves the values untouched
    po_repository.update_po(db_session, po.id, notes="unrelated edit")
    assert po.shipping_cost == Decimal("75.25")
    assert po.tariff_amount == Decimal("10")

    # Explicit null clears
    po_repository.update_po(db_session, po.id, shipping_cost=None, tariff_amount=None)
    assert po.shipping_cost is None
    assert po.tariff_amount is None


def test_update_po_rejects_changing_po_number_once_registered(db_session):
    from app.errors import InvalidStateTransitionError  # noqa: F401 - imported for symmetry with repo raises

    project = _make_project(db_session)
    # A GP-registered PO: create_po's GP-first branch stamps the number and advances to GP_REGISTERED.
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item("ML2010")],
        project_id=project.id,
        po_number="PO0000123",
        gp_company="TUBC",
        gp_vendor_id="V1",
        vendor_name_snapshot="Acme",
    )
    db_session.flush()
    assert po.status == POStatus.GP_REGISTERED

    # Changing the number now would orphan the row from the (gp_company, po_number) mirror key.
    with pytest.raises(ValidationError):
        po_repository.update_po(db_session, po.id, po_number="PO0000999")
    # Blanking it is rejected the same way.
    with pytest.raises(ValidationError):
        po_repository.update_po(db_session, po.id, po_number="")
    # Passing the SAME number is a no-op, not a rejection.
    po_repository.update_po(db_session, po.id, po_number="PO0000123")
    assert po.po_number == "PO0000123"


def test_update_po_still_allows_setting_po_number_on_a_draft(db_session):
    po = po_repository.create_po(db_session, line_items=[_line_item("ML2010")])
    db_session.flush()
    assert po.status == POStatus.DRAFT
    po_repository.update_po(db_session, po.id, po_number="PO-DRAFT-1")
    assert po.po_number == "PO-DRAFT-1"


# #481: the vendor quotation is usually typed onto the PO after the draft exists, but a buyer working
# from a quote in hand had nowhere to record it at creation. Optional, and blank must stay NULL - the
# VENDOR_CONFIRMED auto-transition tests "a quote exists", which an empty string would satisfy.
def test_create_po_persists_a_vendor_quote_number(db_session):
    po = po_repository.create_po(
        db_session,
        line_items=[
            {
                "hardware_category": "Hinges",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 5,
                "order_as": "HG-100",
            }
        ],
        vendor_quote_number="  Q-1234  ",
    )

    assert po.vendor_quote_number == "Q-1234"


@pytest.mark.parametrize("value", [None, "", "   "])
def test_create_po_leaves_a_blank_vendor_quote_number_null(db_session, value):
    po = po_repository.create_po(
        db_session,
        line_items=[
            {
                "hardware_category": "Hinges",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 5,
                "order_as": "HG-100",
            }
        ],
        vendor_quote_number=value,
    )

    assert po.vendor_quote_number is None


def test_create_po_with_a_quote_stays_a_draft(db_session):
    """A quote on a draft records what the buyer was quoted. It must not advance status: the
    VENDOR_CONFIRMED transition is GP_REGISTERED-only and additionally wants a vendor ack document."""
    po = po_repository.create_po(
        db_session,
        line_items=[
            {
                "hardware_category": "Hinges",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 5,
                "order_as": "HG-100",
            }
        ],
        vendor_quote_number="Q-1234",
    )

    assert po.status == POStatus.DRAFT


# --- #632: notes stay editable after the PO is locked --------------------------------------------
# Notes are a Nexus-only overlay - the GP mirror sync never writes them - so the edit-lock update_po
# puts on GP-authoritative fields once receiving starts has nothing to protect here. A warehouse
# remark is usually learned at exactly the moment the PO can no longer be edited.


def _po_with_a_receive(session):
    from datetime import datetime as datetime_cls

    from app.models.receiving import ReceiveRecord

    po = po_repository.create_po(session, line_items=[_line_item("ML2010")])
    session.flush()
    session.add(ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=datetime_cls.utcnow(), received_by="warehouse"))
    session.flush()
    return po


def test_notes_land_after_receiving_has_started_where_update_po_is_refused(db_session):
    from app.errors import InvalidStateTransitionError

    po = _po_with_a_receive(db_session)

    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, notes="blocked")

    po_repository.update_po_notes(db_session, po.id, "  box crushed on delivery  ")
    assert po.notes == "box crushed on delivery"


def test_notes_land_on_a_closed_po_where_update_po_is_refused(db_session):
    from app.errors import InvalidStateTransitionError

    po = po_repository.create_po(db_session, line_items=[_line_item("ML2010")])
    po.status = POStatus.CLOSED
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, notes="blocked")

    po_repository.update_po_notes(db_session, po.id, "short 2 per slip")
    assert po.notes == "short 2 per slip"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_notes_clear_the_column_rather_than_storing_whitespace(db_session, blank):
    po = po_repository.create_po(db_session, line_items=[_line_item("ML2010")])
    db_session.flush()
    po_repository.update_po_notes(db_session, po.id, "something worth saying")
    assert po.notes == "something worth saying"

    po_repository.update_po_notes(db_session, po.id, blank)
    assert po.notes is None


def test_notes_on_a_po_that_does_not_exist_is_not_found(db_session):
    from app.errors import NotFoundError

    with pytest.raises(NotFoundError):
        po_repository.update_po_notes(db_session, uuid.uuid4(), "nowhere")
