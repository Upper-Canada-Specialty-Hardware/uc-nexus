"""Schema-level regression guards for the warehouse/shipping pull-request resolvers (#613).

Two production breakages introduced by #554 lived entirely in the resolver layer - the one layer the
repository-level tests never execute:

- cancelPullRequest read `result.released_opening_ids`, a field #554 had deleted from CancelResult, so
  every cancel committed server-side and then 500'd building its response.
- stagingPool read `pool["loose"]` after #554 flattened build_staged_pool's return to
  `{(opening, category, product): {...}}`, so every staging query threw KeyError and the workspace
  rendered an empty floor.

These run the real operations through the real Strawberry schema against DB fixtures, so a
resolver/DTO drift of exactly that shape fails here by construction. completePullRequest is exercised
the same way because it is the other terminal write the shipping pipeline depends on.
"""

import asyncio
import uuid
from datetime import datetime

import pytest

from app import auth
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    user_repository,
    warehouse_admin_repository,
)
from app.repositories import warehouse as warehouse_repository
from app.schemas import shipping as shipping_module
from app.schemas import warehouse as warehouse_module
from main import schema
from tests.pick_helpers import pick_pull

# --- seed helpers (mirror test_accept_requests) ----------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock.id,
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _finalize_shipping(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "opening_number": opening_number,
                            "hardware_category": "HINGE",
                            "product_code": code,
                            "requested_quantity": qty,
                        }
                    ],
                }
            ],
        },
    )


def _accept_and_pick_shipping(session, project, *, qty=2):
    """A shipping-out request accepted into a pull and picked off the shelf: IN_PROGRESS, picked."""
    req = _finalize_shipping(session, project, qty=qty)["shipping_out_requests"][0]
    session.flush()
    accepted = shipping_repository.accept_shipping_out_request(session, req.id, "acceptor")
    session.flush()
    pr = warehouse_repository.get_pull_request_details(session, accepted.pull_request_id)
    pick_pull(session, pr.id, "picker")
    return req, pr


# --- schema execution harness ----------------------------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context(company: str | None = "TUBC"):
    """A request context with the auth memos already filled.

    `get_context` returns a bare {"request": ...} and the gate fills the rest from Clerk on first
    ask. Seeding them here is what keeps these tests off the network: since #637 a resolver also
    resolves the caller's COMPANY, and an unseeded one reaches Clerk and fails on the missing secret
    key long before the behaviour under test runs. The memo keys are the ones app/auth.py reads, so
    this stubs the caller without weakening `tenant_scope`.

    Roles are empty and the company is the one the fixtures build under: the operations here are open
    to any signed-in user, and the point is that such a user works inside their own tenant."""
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": company,
    }


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context()))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    """A signed-in caller whose resolvers run against the test's own session.

    Resolvers open their own SessionLocal and commit; here that session is the fixture's, and commit is
    turned into flush so the fixture's outer-transaction rollback still isolates the test. Auth is
    stubbed to a verifiable identity with no roles - all the operations under test are open to any
    signed-in user.
    """
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    # #637: belt and braces beside the seeded memo in `_context` - a resolver that builds its own
    # context must not reach Clerk either.
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")
    monkeypatch.setattr(
        user_repository,
        "get_user",
        lambda user_id: {"first_name": "Test", "last_name": "Picker", "email": ""},
    )

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(warehouse_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(shipping_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    return db_session


# --- stagingPool: the #554 KeyError -----------------------------------------------------------


def test_staging_pool_of_an_empty_project_is_not_a_keyerror(signed_in, db_session):
    """Even with nothing staged the resolver must return, not throw: `pool["loose"]` raised KeyError
    on the empty dict too, which is why the workspace looked empty rather than broken."""
    project = _make_project(db_session)
    result = _execute(
        "query($pid: ID!){ stagingPool(projectId:$pid){ looseItems{ productCode } containers{ id } } }",
        {"pid": str(project.id)},
    )
    assert result.errors is None, result.errors
    assert result.data["stagingPool"]["looseItems"] == []


def test_staging_pool_lists_a_completed_shipping_pull(signed_in, db_session):
    """The pipeline the issue walks: accept -> pick -> mark as pulled must surface the hardware on the
    staging floor."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _req, pr = _accept_and_pick_shipping(db_session, project, qty=2)
    warehouse_repository.complete_pull_request(db_session, pr.id, completed_by="picker")
    db_session.flush()

    result = _execute(
        """query($pid: ID!){
             stagingPool(projectId:$pid){
               looseItems{ openingNumber productCode stagedQuantity placedQuantity unplacedQuantity }
             }
           }""",
        {"pid": str(project.id)},
    )
    assert result.errors is None, result.errors
    assert result.data["stagingPool"]["looseItems"] == [
        {
            "openingNumber": "A01",
            "productCode": "HG-100",
            "stagedQuantity": 2,
            "placedQuantity": 0,
            "unplacedQuantity": 2,
        }
    ]


# --- cancelPullRequest: the #554 AttributeError + the returned-to-Pending note -----------------


def test_cancel_result_no_longer_exposes_released_opening_ids():
    """The field #554 deleted must not creep back onto the type: a selection of it fails validation
    before any resolver runs."""
    result = asyncio.run(
        schema.execute(
            "mutation($input: CancelPullRequestInput!){ cancelPullRequest(input:$input){ releasedOpeningIds } }",
            variable_values={"input": {"id": str(uuid.uuid4()), "reason": ""}},
            context_value=_context(),
        )
    )
    assert result.errors is not None
    assert any("releasedOpeningIds" in e.message for e in result.errors), result.errors


def test_cancel_pull_request_returns_cleanly_and_sends_the_request_back(signed_in, db_session):
    """The regression: cancel committed, then 500'd reading a deleted field. It must now return a
    well-formed result, and the source request must reappear PENDING carrying a return note."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req, pr = _accept_and_pick_shipping(db_session, project, qty=2)

    result = _execute(
        """mutation($input: CancelPullRequestInput!){
             cancelPullRequest(input:$input){
               pullRequest{ id status }
               restocked{ productCode quantity }
               sourceRequestReturnedToPending
               integrityNote
             }
           }""",
        {"input": {"id": str(pr.id), "reason": "wrong pull"}},
    )
    assert result.errors is None, result.errors
    payload = result.data["cancelPullRequest"]
    assert payload["pullRequest"]["status"] == "CANCELLED"
    assert payload["sourceRequestReturnedToPending"] is True
    assert payload["restocked"] == [{"productCode": "HG-100", "quantity": 2}]

    board = _execute(
        "query($pid: ID!){ shippingOutRequests(projectId:$pid, status: PENDING){ id status stage returnNote } }",
        {"pid": str(project.id)},
    )
    assert board.errors is None, board.errors
    rows = board.data["shippingOutRequests"]
    assert [r["id"] for r in rows] == [str(req.id)]
    assert rows[0]["status"] == "PENDING"
    assert rows[0]["stage"] == "REQUESTED"
    assert rows[0]["returnNote"] is not None
    assert "cancelled" in rows[0]["returnNote"].lower()


# --- completePullRequest: the other terminal resolver write -----------------------------------


def test_complete_pull_request_executes_through_the_schema(signed_in, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _req, pr = _accept_and_pick_shipping(db_session, project, qty=2)

    result = _execute(
        "mutation($id: ID!){ completePullRequest(id:$id){ id status } }",
        {"id": str(pr.id)},
    )
    assert result.errors is None, result.errors
    assert result.data["completePullRequest"]["status"] == "COMPLETED"
