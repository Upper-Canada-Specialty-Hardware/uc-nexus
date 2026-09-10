"""The NEXUS REGISTERED LINE: where it is set, and what the GraphQL schema publishes about it.

A line is Nexus-registered when its hardware category and product code came off a hardware schedule
rather than off GP's PO line. Every line the draft/register path writes is one from birth; a line the
GP mirror creates is not. A PO reads as Nexus-registered only when every one of its lines is.

DB-backed (db_session). The schema half runs through the built Strawberry schema, with the caller's
company stubbed the way the other schema tests stub it (#637).
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import auth
from app.models.enums import POOrigin, POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import po_repository, user_repository
from main import schema

COMPANY = "TUBC"


def _line_item(**overrides) -> dict:
    base = {
        "hardware_category": "HINGE",
        "product_code": "HG-100",
        "ordered_quantity": 2,
        "unit_cost": 12.5,
        "classification": None,
        "order_as": "ML2010",
    }
    base.update(overrides)
    return base


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id=f"J-{uuid.uuid4().hex[:6]}", description="Job", company=COMPANY)
    db_session.add(p)
    db_session.flush()
    return p


# --- where the flag is set ---------------------------------------------------------------------------


def test_every_line_a_draft_is_raised_with_is_registered(db_session, project):
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item(), _line_item(product_code="HG-200")],
        project_id=project.id,
    )
    db_session.flush()

    lines = db_session.scalars(select(POLineItem).where(POLineItem.po_id == po.id)).all()
    assert len(lines) == 2
    assert all(li.nexus_registered for li in lines)


def test_registering_a_draft_leaves_every_line_registered(db_session, project):
    po = po_repository.create_po(db_session, line_items=[_line_item()], project_id=project.id)
    db_session.flush()
    existing = db_session.scalars(select(POLineItem).where(POLineItem.po_id == po.id)).one()

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
        po_number=f"PO{uuid.uuid4().hex[:8].upper()}",
        gp_company=COMPANY,
        line_items=[
            # the line the draft already had, kept and edited
            _line_item(id=str(existing.id), product_code="HG-101"),
            # and one added at register time
            _line_item(product_code="HG-300"),
        ],
    )
    db_session.flush()

    lines = db_session.scalars(select(POLineItem).where(POLineItem.po_id == po.id)).all()
    assert {li.product_code for li in lines} == {"HG-101", "HG-300"}
    assert all(li.nexus_registered for li in lines)


# --- what the schema publishes -----------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context():
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": COMPANY,
    }


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context()))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    """A signed-in caller whose PO resolvers run against the test's own session."""
    from app.schemas import po as po_module

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: COMPANY)

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    return db_session


def _mirrored_po(session, project, *, registered_flags):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=COMPANY,
        gp_company=COMPANY,
        po_number=f"PO{uuid.uuid4().hex[:8].upper()}",
        request_number=None,
        origin=POOrigin.GP,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
    )
    session.add(po)
    session.flush()
    for idx, registered in enumerate(registered_flags, start=1):
        session.add(
            POLineItem(
                id=uuid.uuid4(),
                po_id=po.id,
                gp_line_ord=idx * 16384,
                hardware_category="HD 001 description",
                product_code="HD 001",
                ordered_quantity=3,
                received_quantity=0,
                unit_cost=Decimal("10.00"),
                nexus_registered=registered,
            )
        )
    session.flush()
    return po


_QUERY = "query($id: ID!){ purchaseOrder(id: $id){ nexusRegistered lineItems { nexusRegistered } } }"


def test_a_po_reads_registered_only_when_every_line_is(signed_in, db_session, project):
    po = _mirrored_po(db_session, project, registered_flags=[True, True])

    result = _execute(_QUERY, {"id": str(po.id)})

    assert result.errors is None, result.errors
    assert result.data["purchaseOrder"]["nexusRegistered"] is True
    assert [li["nexusRegistered"] for li in result.data["purchaseOrder"]["lineItems"]] == [True, True]


def test_one_unregistered_line_leaves_the_whole_po_unregistered(signed_in, db_session, project):
    po = _mirrored_po(db_session, project, registered_flags=[True, False])

    result = _execute(_QUERY, {"id": str(po.id)})

    assert result.errors is None, result.errors
    assert result.data["purchaseOrder"]["nexusRegistered"] is False
    assert sorted(li["nexusRegistered"] for li in result.data["purchaseOrder"]["lineItems"]) == [False, True]


def test_a_po_with_no_lines_at_all_is_not_registered(signed_in, db_session, project):
    po = _mirrored_po(db_session, project, registered_flags=[])

    result = _execute(_QUERY, {"id": str(po.id)})

    assert result.errors is None, result.errors
    assert result.data["purchaseOrder"]["nexusRegistered"] is False
    assert result.data["purchaseOrder"]["lineItems"] == []
