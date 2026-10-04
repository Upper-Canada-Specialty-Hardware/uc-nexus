"""A PO's delivery dates can be cleared (#1463).

The edit form sent an emptied date as null, and null meant "leave it", so a wrong expected date could
not be taken back off a PO. Now an omitted date is left alone, a value sets it, and an explicit null
clears it - in the status where that date is editable. Outside it a null still leaves the date alone,
which is what the form used to send for the date it could not edit."""

import asyncio
import uuid
from datetime import date

import pytest

from app import auth
from app.errors import InvalidStateTransitionError
from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository, user_repository
from app.schemas import po as po_module
from main import schema


def _po(session, status, **dates) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        status=status,
        company="TUBC",
        **dates,
    )
    session.add(po)
    session.flush()
    return po


def test_an_explicit_null_clears_the_expected_date_on_a_registered_po(db_session):
    po = _po(db_session, POStatus.GP_REGISTERED, expected_delivery_date=date(2026, 9, 1))
    po_repository.update_po(db_session, po.id, expected_delivery_date=None)
    assert po.expected_delivery_date is None


def test_an_explicit_null_clears_the_preferred_date_on_a_draft(db_session):
    po = _po(db_session, POStatus.DRAFT, preferred_delivery_date=date(2026, 9, 1))
    po_repository.update_po(db_session, po.id, preferred_delivery_date=None)
    assert po.preferred_delivery_date is None


def test_an_omitted_date_is_left_alone(db_session):
    po = _po(db_session, POStatus.GP_REGISTERED, expected_delivery_date=date(2026, 9, 1))
    po_repository.update_po(db_session, po.id, notes="unrelated")
    assert po.expected_delivery_date == date(2026, 9, 1)


def test_a_null_for_the_date_not_editable_now_leaves_it_alone(db_session):
    """What a form opened before #1463 sends: null for the other date. Neither refused nor cleared."""
    po = _po(
        db_session,
        POStatus.GP_REGISTERED,
        preferred_delivery_date=date(2026, 8, 1),
        expected_delivery_date=date(2026, 9, 1),
    )
    po_repository.update_po(db_session, po.id, preferred_delivery_date=None, expected_delivery_date=date(2026, 9, 2))
    assert po.preferred_delivery_date == date(2026, 8, 1)
    assert po.expected_delivery_date == date(2026, 9, 2)

    draft = _po(db_session, POStatus.DRAFT, preferred_delivery_date=date(2026, 8, 1))
    po_repository.update_po(db_session, draft.id, expected_delivery_date=None)
    assert draft.preferred_delivery_date == date(2026, 8, 1)


def test_setting_a_date_outside_its_status_is_still_refused(db_session):
    registered = _po(db_session, POStatus.GP_REGISTERED)
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, registered.id, preferred_delivery_date=date(2026, 8, 1))
    draft = _po(db_session, POStatus.DRAFT)
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, draft.id, expected_delivery_date=date(2026, 8, 1))


class _FakeRequest:
    headers = {"authorization": "Bearer tok"}


@pytest.fixture
def run_update(db_session, monkeypatch):
    """Executes updatePo through the GraphQL schema, so an omitted variable is what Strawberry sees."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    # The resolver commits; inside the test's transaction a flush is the commit.
    monkeypatch.setattr(db_session, "commit", db_session.flush)

    def _run(variables: dict):
        result = asyncio.run(
            schema.execute(
                "mutation($id: ID!, $expectedDeliveryDate: Date, $preferredDeliveryDate: Date, $poolKind: PoolKind) {"
                " updatePo(id: $id, expectedDeliveryDate: $expectedDeliveryDate,"
                " preferredDeliveryDate: $preferredDeliveryDate, poolKind: $poolKind) { id } }",
                variable_values=variables,
                context_value={
                    "request": _FakeRequest(),
                    "_auth_user_id": "u_test",
                    "_auth_roles": [],
                    "_auth_company": "TUBC",
                },
            )
        )
        assert result.errors is None, result.errors

    return _run


def test_a_pool_kind_only_update_leaves_both_dates(db_session, run_update):
    """The register dialog's pool pick sends id and poolKind only; the declared but unsent date
    variables must reach the resolver as omitted, not as null."""
    po = _po(db_session, POStatus.DRAFT, preferred_delivery_date=date(2026, 8, 1))
    run_update({"id": str(po.id), "poolKind": "OVERHEAD"})
    db_session.refresh(po)
    assert po.preferred_delivery_date == date(2026, 8, 1)


def test_an_explicit_null_through_graphql_clears_the_expected_date(db_session, run_update):
    po = _po(db_session, POStatus.GP_REGISTERED, expected_delivery_date=date(2026, 9, 1))
    run_update({"id": str(po.id), "expectedDeliveryDate": None})
    db_session.refresh(po)
    assert po.expected_delivery_date is None
