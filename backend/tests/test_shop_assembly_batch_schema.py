"""Schema-level guards for the shop-assembly manager's board (#646/#643/#644).

The repository tests prove the batching rules; these prove the layer above them, which is the one
layer repository tests never execute. Three things can only break here:

- the converters walking a relationship the reader did not load (the #342-era `get_request_with_
  openings` crash, in a new shape now that a request carries openings AND batches AND batch items);
- the role gate, which is what makes the four writes the Shop Assembly Manager's rather than
  anyone's;
- the allocation review's shape, which the manager's screen is built directly on.

Run through the real Strawberry schema against DB fixtures, so any of those fails here by
construction.
"""

import asyncio
import uuid
from datetime import datetime

import pytest

from app import auth
from app.auth import ADMIN_ROLE, SHOP_ASSEMBLY_MANAGER_ROLE
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import import_repository, user_repository, warehouse_admin_repository
from app.schemas import shop_assembly as shop_assembly_module
from main import schema

REQUEST_FIELDS = """
  id
  requestNumber
  status
  stage
  returnNote
  items { openingNumber productCode requestedQuantity }
  openings { openingNumber status batchId dismissedBy dismissalReason }
  batches { batchNumber sequence status pullRequestId pullStatus items { openingNumber allocatedQuantity } }
"""


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


def _raise_request(session, project, *, openings=("A01", "A02"), qty=2):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": n} for n in openings],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": n, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": qty}
                for n in openings
            ],
        },
    )["shop_assembly_request"]


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(
        schema.execute(query, variable_values=variables or {}, context_value={"request": _FakeRequest()})
    )


# This file's own Clerk subject, not the `u_test` the other schema suites use. `resolve_display_name`
# memoises name-by-user-id in a module-level TTL cache, so two files stubbing `get_user` differently
# for the SAME id race: whichever runs first wins, and the other's actor stamps come out as its
# neighbour's name. A distinct id plus the invalidate below makes the actor assertions this file
# makes - which are the whole point of recording an actor - independent of test order.
_MANAGER_ID = "u_shop_assembly_manager"


@pytest.fixture
def as_manager(monkeypatch, db_session):
    """A Shop Assembly Manager whose resolvers run against the test's own session.

    Resolvers open their own SessionLocal and commit; here that session is the fixture's, and commit
    is turned into flush so the fixture's outer-transaction rollback still isolates the test.
    """
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": _MANAGER_ID})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [SHOP_ASSEMBLY_MANAGER_ROLE])
    # #637: tenant_scope also resolves the caller's company; stub it the way roles are stubbed so the
    # suite stays off the network, scoped to the company the fixtures build under.
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")
    monkeypatch.setattr(
        user_repository,
        "get_user",
        lambda user_id: {"first_name": "Morgan", "last_name": "Shop", "email": ""},
    )
    auth.invalidate_display_name(_MANAGER_ID)

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(shop_assembly_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    yield db_session
    # The cache outlives the monkeypatch, so a name stubbed here must not be handed to whatever runs
    # next under the same id.
    auth.invalidate_display_name(_MANAGER_ID)


# --- the allocation review the manager's screen is built on ------------------------------------


def test_allocation_review_lists_pending_openings_with_live_availability(as_manager, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)
    sar = _raise_request(db_session, project, qty=2)
    db_session.flush()

    result = _execute(
        """query($rid: ID!){
             shopAssemblyAllocationReview(requestId: $rid){
               requestNumber
               status
               openings{
                 openingNumber
                 lines{ hardwareCategory productCode requestedQuantity availableQuantity }
               }
             }
           }""",
        {"rid": str(sar.id)},
    )

    assert result.errors is None, result.errors
    review = result.data["shopAssemblyAllocationReview"]
    assert review["requestNumber"] == sar.request_number
    assert [o["openingNumber"] for o in review["openings"]] == ["A01", "A02"]
    # Availability is the project-wide pool, shown whole on both openings - they are competing for
    # the same three hinges, and the screen has to show that rather than pre-splitting it.
    assert [line["availableQuantity"] for o in review["openings"] for line in o["lines"]] == [3, 3]
    assert [line["requestedQuantity"] for o in review["openings"] for line in o["lines"]] == [2, 2]


def test_a_batched_opening_drops_off_the_review(as_manager, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _raise_request(db_session, project, qty=2)
    db_session.flush()

    batched = _execute(
        f"""mutation($input: CreateShopAssemblyBatchInput!){{
              createShopAssemblyBatch(input: $input){{ {REQUEST_FIELDS} }}
            }}""",
        {
            "input": {
                "requestId": str(sar.id),
                "lines": [
                    {
                        "openingNumber": "A01",
                        "hardwareCategory": "HINGE",
                        "productCode": "HG-100",
                        "allocatedQuantity": 2,
                    }
                ],
            }
        },
    )
    assert batched.errors is None, batched.errors
    request = batched.data["createShopAssemblyBatch"]
    assert request["status"] == "PENDING"  # A02 is still waiting
    assert request["stage"] == "REQUESTED"
    assert {o["openingNumber"]: o["status"] for o in request["openings"]} == {
        "A01": "BATCHED",
        "A02": "PENDING",
    }
    batch = request["batches"][0]
    assert batch["batchNumber"] == f"{sar.request_number}-B1"
    assert batch["status"] == "ACTIVE"
    assert batch["pullStatus"] == "PENDING"
    assert batch["items"] == [{"openingNumber": "A01", "allocatedQuantity": 2}]

    review = _execute(
        "query($rid: ID!){ shopAssemblyAllocationReview(requestId: $rid){ openings{ openingNumber } } }",
        {"rid": str(sar.id)},
    )
    assert review.errors is None, review.errors
    assert [o["openingNumber"] for o in review.data["shopAssemblyAllocationReview"]["openings"]] == ["A02"]


# --- dismiss / discard, through the schema ------------------------------------------------------


def test_dismissing_the_remainder_closes_the_request_out(as_manager, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _raise_request(db_session, project, qty=2)
    db_session.flush()

    result = _execute(
        f"""mutation($rid: ID!, $reason: String){{
              dismissShopAssemblyOpenings(requestId: $rid, reason: $reason){{ {REQUEST_FIELDS} }}
            }}""",
        {"rid": str(sar.id), "reason": "hardware never arrived"},
    )

    assert result.errors is None, result.errors
    request = result.data["dismissShopAssemblyOpenings"]
    assert request["status"] == "APPROVED"
    assert request["stage"] == "DONE"
    assert {o["status"] for o in request["openings"]} == {"DISMISSED"}
    assert {o["dismissedBy"] for o in request["openings"]} == {"Morgan Shop"}
    assert {o["dismissalReason"] for o in request["openings"]} == {"hardware never arrived"}


def test_discarding_a_batch_returns_its_openings_through_the_schema(as_manager, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _raise_request(db_session, project, openings=("A01",), qty=2)
    db_session.flush()

    created = _execute(
        """mutation($input: CreateShopAssemblyBatchInput!){
             createShopAssemblyBatch(input: $input){ batches{ id } }
           }""",
        {
            "input": {
                "requestId": str(sar.id),
                "lines": [
                    {
                        "openingNumber": "A01",
                        "hardwareCategory": "HINGE",
                        "productCode": "HG-100",
                        "allocatedQuantity": 2,
                    }
                ],
            }
        },
    )
    assert created.errors is None, created.errors
    batch_id = created.data["createShopAssemblyBatch"]["batches"][0]["id"]

    discarded = _execute(
        f"""mutation($bid: ID!){{ discardShopAssemblyBatch(batchId: $bid){{ {REQUEST_FIELDS} }} }}""",
        {"bid": batch_id},
    )
    assert discarded.errors is None, discarded.errors
    request = discarded.data["discardShopAssemblyBatch"]
    assert request["status"] == "PENDING"
    assert request["batches"] == []
    assert [o["status"] for o in request["openings"]] == ["PENDING"]


def test_rejecting_a_batched_request_is_refused_with_its_code(as_manager, db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _raise_request(db_session, project, qty=2)
    db_session.flush()

    _execute(
        "mutation($input: CreateShopAssemblyBatchInput!){ createShopAssemblyBatch(input: $input){ id } }",
        {
            "input": {
                "requestId": str(sar.id),
                "lines": [
                    {
                        "openingNumber": "A01",
                        "hardwareCategory": "HINGE",
                        "productCode": "HG-100",
                        "allocatedQuantity": 2,
                    }
                ],
            }
        },
    )

    result = _execute(
        "mutation($id: ID!){ rejectShopAssemblyRequest(id: $id){ id } }",
        {"id": str(sar.id)},
    )
    assert result.errors
    assert result.errors[0].extensions["code"] == "INVALID_STATE_TRANSITION"


# --- the role gate ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,query",
    [
        (
            "createShopAssemblyBatch",
            'mutation{ createShopAssemblyBatch(input:{requestId:"00000000-0000-0000-0000-000000000000",'
            "lines:[]}){ id } }",
        ),
        (
            "dismissShopAssemblyOpenings",
            'mutation{ dismissShopAssemblyOpenings(requestId:"00000000-0000-0000-0000-000000000000"){ id } }',
        ),
        (
            "rejectShopAssemblyRequest",
            'mutation{ rejectShopAssemblyRequest(id:"00000000-0000-0000-0000-000000000000"){ id } }',
        ),
        (
            "discardShopAssemblyBatch",
            'mutation{ discardShopAssemblyBatch(batchId:"00000000-0000-0000-0000-000000000000"){ id } }',
        ),
    ],
)
def test_the_manager_board_refuses_a_plain_signed_in_caller(field, query, monkeypatch, db_session):
    """The four writes are the Shop Assembly Manager's, with Admin/Manager beside them as an any-of.
    A signed-in user with neither role is refused before the resolver runs."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: ["Shop Assembly User"])

    result = _execute(query)

    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert result.errors[0].message == f"{ADMIN_ROLE} or {SHOP_ASSEMBLY_MANAGER_ROLE} role required"


def test_reading_a_request_stays_open_to_any_signed_in_user(monkeypatch, db_session):
    """The reads are not gated: the PM who raised the request has to be able to watch it, and the
    availability arithmetic is the same one every other screen already shows."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    # #637: the list is tenant-scoped, so even a roleless signed-in reader resolves a company.
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    result = _execute("{ shopAssemblyRequests { id } }")

    assert result.errors is None, result.errors
