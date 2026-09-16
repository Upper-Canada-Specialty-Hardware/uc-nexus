"""GP-PROCESSING (#702): the read-back that completes a purchase order the moment GP has it.

A PO REGISTRATION records only what the relay hands back and dates the PO at the moment of the push.
GP-PROCESSING reads that one PO straight back by number and applies GP's copy through the mirror's
own upsert, so the GP-OWNED FIELDS converge, the NEXUS-ONLY FIELDS do not, and a NEXUS REGISTERED
LINE keeps the schedule's hardware category and product code.

**Never touches GP**: relay_gateway.relay_call is stubbed in every test here.

DB-backed (db_session). The schema half runs through the built Strawberry schema with the caller's
company stubbed, the way the other schema tests stub it (#637).
"""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app import auth
from app.errors import ConflictError, InvalidStateTransitionError
from app.models.enums import POOrigin, POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import user_repository
from app.schemas import po as po_schema
from app.services import gp_processing
from main import schema

COMPANY = "TUBC"
OTHER_COMPANY = "UCSH"
JOB = "J-702"
CATEGORY = "Hinges"
CODE = "HG-100"


class _NoCloseSession:
    """The test session as a context manager that does NOT close it - the db_session fixture owns its
    lifecycle, so a service opening SessionLocal() runs inside the test's own transaction."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id=JOB, description="Job", company=COMPANY)
    db_session.add(p)
    db_session.flush()
    return p


def _registered_po(
    db_session,
    project,
    *,
    company=COMPANY,
    status=POStatus.GP_REGISTERED,
    po_number=None,
    nexus_registered=True,
):
    """A PO as a PO REGISTRATION leaves it: GP's number and company stamped, ordered_at set to the
    moment of the push, and none of GP's own values on it yet. A `po_number` of None is a PO GP has
    not numbered - a draft, or a registration that never landed."""
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=company,
        gp_company=company if po_number else None,
        po_number=po_number,
        request_number="REQ-702",
        origin=POOrigin.NEXUS,
        project_id=project.id,
        status=status,
        # What the registration stamped: now, not GP's document date.
        ordered_at=datetime(2026, 3, 1, 14, 30),
        notes="Call the site before delivery",
        vendor_quote_number="Q-9",
        tariff_amount=Decimal("4.00"),
    )
    db_session.add(po)
    db_session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        gp_line_ord=16384,
        hardware_category=CATEGORY,
        product_code=CODE,
        ordered_quantity=5,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
        nexus_registered=nexus_registered,
    )
    db_session.add(line)
    db_session.flush()
    return po, line


def _gp_line(*, ord_=16384, item="Hinges", itemdesc="HG-100", qty=5, received=2, cost_code="310-000-3"):
    return {
        "ord": ord_,
        "item": item,
        "itemdesc": itemdesc,
        "qty": qty,
        "qty_cancelled": 0,
        "received": received,
        "unit_cost": 11.25,
        "job": JOB,
        "line_status": 2,
        "cost_code": cost_code,
    }


def _gp_po(po_number, *, lines=None, freight=12.5, doc_date="2026-01-05"):
    return {
        "po_number": po_number,
        "gp_status": 2,
        "vendor_id": "V-ACE",
        "vendor_name": "Ace Hardware Co",
        "doc_date": doc_date,
        "modified_at": "2026-01-06T09:00:00",
        "source_table": "work",
        "freight": freight,
        "lines": [_gp_line()] if lines is None else lines,
    }


def _stub_relay(monkeypatch, db_session, result, calls=None):
    """Point the service's sessions at the test transaction and answer read_pos_by_number with
    `result`. The service commits; the fixture's outer transaction is what rolls the test back."""
    monkeypatch.setattr(gp_processing, "SessionLocal", lambda: _NoCloseSession(db_session))
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    async def _call(company, op, payload=None, timeout=30.0, **kwargs):
        if calls is not None:
            calls.append((company, op, payload))
        return result

    monkeypatch.setattr(gp_processing.relay_gateway, "relay_call", _call)


# --- the service -------------------------------------------------------------------------------------


def test_gps_copy_lands_on_the_po_and_the_overlay_survives(monkeypatch, db_session, project):
    po, line = _registered_po(db_session, project, po_number="PO502350")
    calls = []
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO502350")], "missing": []}, calls)

    number = asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    assert number == "PO502350"
    # One key, read by number, through the same relay op OPEN-POS RECONCILIATION uses.
    assert calls == [(COMPANY, "read_pos_by_number", {"po_numbers": ["PO502350"]})]

    db_session.refresh(po)
    db_session.refresh(line)
    # GP-OWNED FIELDS: GP's document date replaces the moment of the push, freight lands as the
    # shipping cost, the line takes GP's cost code, unit cost and received quantity.
    assert po.ordered_at == datetime(2026, 1, 5, 0, 0)
    assert po.shipping_cost == Decimal("12.50")
    assert po.cost_code == "310-000-3"
    assert line.cost_code == "310-000-3"
    assert line.unit_cost == Decimal("11.25")
    assert line.received_quantity == 2
    # PO STATUS FROM QUANTITIES: some received, so the PO is no longer merely GP-registered.
    assert po.status == POStatus.PARTIALLY_RECEIVED
    assert po.gp_synced_at is not None
    # NEXUS-ONLY FIELDS are untouched.
    assert po.notes == "Call the site before delivery"
    assert po.vendor_quote_number == "Q-9"
    assert po.tariff_amount == Decimal("4.00")
    assert po.request_number == "REQ-702"


def test_a_nexus_registered_line_keeps_the_schedules_identity(monkeypatch, db_session, project):
    # GP holds a cost bucket as the item number and the part number as the description; the line is a
    # NEXUS REGISTERED LINE, so neither may be written over it.
    po, line = _registered_po(db_session, project, po_number="PO502351")
    gp = _gp_po("PO502351", lines=[_gp_line(item="HD 001 HINGE", itemdesc="HD 001")])
    _stub_relay(monkeypatch, db_session, {"pos": [gp], "missing": []})

    asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    db_session.refresh(line)
    assert line.hardware_category == CATEGORY
    assert line.product_code == CODE
    assert line.nexus_registered is True


def test_an_unregistered_line_takes_gps_own_identity(monkeypatch, db_session, project):
    po, line = _registered_po(db_session, project, po_number="PO502352", nexus_registered=False)
    gp = _gp_po("PO502352", lines=[_gp_line(item="HD 001 HINGE", itemdesc="HD 001")])
    _stub_relay(monkeypatch, db_session, {"pos": [gp], "missing": []})

    asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    db_session.refresh(line)
    assert line.hardware_category == "HD 001 HINGE"
    assert line.product_code == "HD 001"


def test_a_po_gp_does_not_show_yet_is_refused_so_the_dialog_can_offer_a_retry(monkeypatch, db_session, project):
    po, _line = _registered_po(db_session, project, po_number="PO502353")
    _stub_relay(monkeypatch, db_session, {"pos": [], "missing": ["PO502353"]})

    with pytest.raises(ConflictError) as exc:
        asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    assert exc.value.code == gp_processing.NOT_READY_CODE
    assert "does not show" in str(exc.value)


def test_a_header_with_no_lines_yet_reads_the_same_as_not_in_gp_yet(monkeypatch, db_session, project):
    # GP reported the PO but has not given it a line, which the mirror skips: a header alone would
    # converge the quantities and the status against an empty line set.
    po, line = _registered_po(db_session, project, po_number="PO502354")
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO502354", lines=[])], "missing": []})

    with pytest.raises(ConflictError) as exc:
        asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    assert exc.value.code == gp_processing.NOT_READY_CODE
    db_session.refresh(line)
    assert line.received_quantity == 0  # nothing was written


def test_a_reply_that_names_another_po_is_not_applied(monkeypatch, db_session, project):
    po, _line = _registered_po(db_session, project, po_number="PO502355")
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO999999")], "missing": []})

    with pytest.raises(ConflictError):
        asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))


def test_a_draft_has_nothing_in_gp_to_read_back(monkeypatch, db_session, project):
    po, _line = _registered_po(db_session, project, status=POStatus.DRAFT)
    _stub_relay(monkeypatch, db_session, {"pos": [], "missing": []})

    with pytest.raises(InvalidStateTransitionError) as exc:
        asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    assert "still a draft" in str(exc.value)


def test_a_po_past_draft_with_no_gp_number_is_refused(monkeypatch, db_session, project):
    po, _line = _registered_po(db_session, project)
    _stub_relay(monkeypatch, db_session, {"pos": [], "missing": []})

    with pytest.raises(InvalidStateTransitionError) as exc:
        asyncio.run(gp_processing.run_gp_processing(COMPANY, po.id))

    assert "no GP number" in str(exc.value)


def test_a_po_in_another_gp_company_is_not_read_under_this_one(monkeypatch, db_session, project):
    po, _line = _registered_po(db_session, project, po_number="PO502356")
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO502356")], "missing": []})

    with pytest.raises(InvalidStateTransitionError) as exc:
        asyncio.run(gp_processing.run_gp_processing(OTHER_COMPANY, po.id))

    assert COMPANY in str(exc.value)


# --- what the schema publishes -----------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context(company: str = COMPANY):
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": company,
    }


def _execute(query: str, variables: dict | None = None, company: str = COMPANY):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context(company)))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    """A signed-in caller whose PO resolvers run against the test's own session."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: COMPANY)
    monkeypatch.setattr(po_schema, "SessionLocal", lambda: _NoCloseSession(db_session))
    return db_session


_MUTATION = """
mutation($poId: ID!) {
  runGpProcessing(poId: $poId) {
    id
    poNumber
    status
    orderedAt
    shippingCost
    costCode
    notes
    lineItems { costCode receivedQuantity hardwareCategory productCode }
  }
}
"""


def test_the_mutation_completes_the_po_from_gps_copy(monkeypatch, signed_in, db_session, project):
    po, _line = _registered_po(db_session, project, po_number="PO502360")
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO502360")], "missing": []})

    result = _execute(_MUTATION, {"poId": str(po.id)})

    assert result.errors is None, result.errors
    payload = result.data["runGpProcessing"]
    assert payload["poNumber"] == "PO502360"
    assert payload["status"] == "PARTIALLY_RECEIVED"
    assert payload["orderedAt"].startswith("2026-01-05")
    assert payload["shippingCost"] == 12.5
    assert payload["costCode"] == "310-000-3"
    assert payload["notes"] == "Call the site before delivery"
    assert payload["lineItems"] == [
        {
            "costCode": "310-000-3",
            "receivedQuantity": 2,
            "hardwareCategory": CATEGORY,
            "productCode": CODE,
        }
    ]


def test_the_mutation_refuses_a_po_of_another_company(monkeypatch, signed_in, db_session, project):
    other = Project(id=uuid.uuid4(), project_id="J-OTHER", description="Job", company=OTHER_COMPANY)
    db_session.add(other)
    db_session.flush()
    po, _line = _registered_po(db_session, other, company=OTHER_COMPANY, po_number="PO502361")
    calls = []
    _stub_relay(monkeypatch, db_session, {"pos": [_gp_po("PO502361")], "missing": []}, calls)

    result = _execute(_MUTATION, {"poId": str(po.id)})

    # Out of scope reads as absent, and nothing reached GP.
    assert result.errors
    assert "not found" in result.errors[0].message
    assert calls == []
