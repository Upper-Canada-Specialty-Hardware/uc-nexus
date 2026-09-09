"""INVENTORY VALUE: the three figures, the doors behind them, and who may ask (#662).

The arithmetic is the point of this file. OSSA / NON-OSSA / GENERAL STOCK is a partition of one GP
company - a project is OSSA or it is not, the stock pool is neither - so every dollar in the building
lands in exactly one figure, and the way to prove that is to seed known rows and assert the totals to
the cent.

Two of those dollars are harder than the rest, and both get their own case:

- **Staged hardware has left the shelf.** There is no inventory row to price it by any more, only the
  APPLIED pick lines saying which rows it came off (#367). Those rows are kept at quantity 0 and keep
  their cost, so the price of the very units on the cart is recoverable - quantity-weighted, because
  one pull can take the same product off two rows bought at different prices.
- **A pull with no pick lines behind it** (picked before #367, or off rows since deleted) falls back
  to the project's average cost for that product, and to 0 when even that knows nothing. Zero is the
  honest answer there; guessing would put an invented number in a figure somebody reports upward.

Each case seeds its OWN GP company rather than sharing one. These are whole-company aggregates, so a
shared company means every assertion is really "the delta over whatever else happened to be seeded",
and a bug that double-counts a row would hide behind the subtraction.
"""

import asyncio
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app import auth
from app.auth import ADMIN_ROLE, SHOP_ASSEMBLY_MANAGER_ROLE
from app.errors import NotFoundError, ValidationError
from app.models.enums import POStatus, PullRequestSource, PullRequestStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories import inventory_value_repository, shipping_repository, shipping_requests, user_repository
from app.repositories import warehouse as warehouse_repository
from app.schemas import inventory_value as inventory_value_module
from main import schema
from tests.pick_helpers import pick_pull

CATEGORY = "HINGE"
CODE = "HG-100"


# --- fixtures -------------------------------------------------------------------------------------


def _company() -> str:
    """A GP company code nothing else in the suite uses - see the module docstring."""
    return f"T{uuid.uuid4().hex[:8].upper()}"


def _warehouse(session, company: str) -> Warehouse:
    tag = uuid.uuid4().hex[:8]
    wh = Warehouse(
        id=uuid.uuid4(),
        company=company,
        name=f"Building {tag}",
        code=tag.upper()[:10],
        is_primary=False,
        is_active=True,
    )
    session.add(wh)
    session.flush()
    return wh


def _project(session, company: str, *, ossa: bool = False) -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=f"PROJ-{uuid.uuid4().hex[:8]}",
        description=f"Job {uuid.uuid4().hex[:4]}",
        company=company,
        off_site_storage_agreement=ossa,
    )
    session.add(p)
    session.flush()
    return p


def _po_priced_row(session, project, warehouse, *, unit_cost, quantity, age_days=2, code=CODE) -> InventoryLocation:
    """Shelf hardware whose cost lives on its PO line - the ordinary received row.

    The PO line AND the receive line are both built because `ck_inventory_locations_has_origin`
    demands the pair: a row priced off a PO is a row that was received against one.
    """
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        company=project.company,
        status=POStatus.CLOSED,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category=CATEGORY,
        product_code=code,
        ordered_quantity=quantity,
        received_quantity=quantity,
        unit_cost=unit_cost,
    )
    session.add(line)
    session.flush()
    record = ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=datetime.utcnow(), received_by="receiver")
    session.add(record)
    session.flush()
    receive_line = ReceiveLineItem(
        id=uuid.uuid4(),
        receive_record_id=record.id,
        po_line_item_id=line.id,
        hardware_category=CATEGORY,
        product_code=code,
        quantity_received=quantity,
    )
    session.add(receive_line)
    session.flush()
    row = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        po_line_item_id=line.id,
        receive_line_item_id=receive_line.id,
        warehouse_id=warehouse.id,
        hardware_category=CATEGORY,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow() - timedelta(days=age_days),
    )
    session.add(row)
    session.flush()
    return row


def _row_priced_row(session, project, warehouse, *, unit_cost, quantity, age_days=1, code=CODE) -> InventoryLocation:
    """Shelf hardware carrying its own off-PO cost - what the SharePoint migration wrote."""
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse.id,
        hardware_category=CATEGORY,
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    row = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        stock_item_id=stock.id,
        warehouse_id=warehouse.id,
        hardware_category=CATEGORY,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        unit_cost=unit_cost,
        received_at=datetime.utcnow() - timedelta(days=age_days),
    )
    session.add(row)
    session.flush()
    return row


def _stock_row(session, warehouse, *, quantity, unit_cost, code=CODE) -> StockItem:
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse.id,
        hardware_category=CATEGORY,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        unit_cost=unit_cost,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    return stock


def _stage_by_picking(session, project, *, quantity: int, ship: int = 0, code=CODE):
    """The real pipeline: raise a shipping-out request, accept it, pick it off the shelf, complete it,
    and optionally cut a packing slip for part of what it staged."""
    req = shipping_requests.create_shipping_out_requests(
        session,
        project.id,
        [
            {
                "request_number": f"SOR-{uuid.uuid4().hex[:6]}",
                "items": [
                    {
                        "opening_number": None,
                        "hardware_category": CATEGORY,
                        "product_code": code,
                        "requested_quantity": quantity,
                    }
                ],
            }
        ],
        created_by="requester",
    )[0]
    accepted = shipping_repository.accept_shipping_out_request(session, req.id, "acceptor")
    session.flush()
    pick_pull(session, accepted.pull_request_id, "picker")
    warehouse_repository.complete_pull_request(session, accepted.pull_request_id, completed_by="picker")
    session.flush()
    if ship:
        shipping_repository.confirm_shipment(
            session,
            project.id,
            "shipper",
            [
                {
                    "opening_number": None,
                    "hardware_category": CATEGORY,
                    "product_code": code,
                    "quantity": ship,
                }
            ],
        )
        session.flush()
    return accepted


def _stage_without_picking(session, project, *, quantity: int, code=CODE) -> PullRequest:
    """A completed shipping-out pull with no pick lines behind it - hardware staged before #367, or
    off rows that have since been deleted. Nothing comes off the shelf, which is the whole point."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            opening_number=None,
            hardware_category=CATEGORY,
            product_code=code,
            requested_quantity=quantity,
        )
    )
    session.flush()
    return pr


def _value(session, company: str) -> dict:
    return inventory_value_repository.get_inventory_value(session, company)


# --- the three figures ----------------------------------------------------------------------------


def test_the_three_figures_partition_the_company(db_session):
    """Greg's formula end to end: shelf plus staged plus stock, each at its own cost, plus every door
    at AVERAGE DOOR COST, split by whether the project carries the OSSA flag."""
    company = _company()
    warehouse = _warehouse(db_session, company)
    ossa_project = _project(db_session, company, ossa=True)
    plain_project = _project(db_session, company)

    # OSSA project: 4 units at 12.50 on a PO line, 3 at 7.25 on the rows' own cost. The pick below
    # takes 2 off the older (PO-priced) row, leaving 2 there.
    _po_priced_row(db_session, ossa_project, warehouse, unit_cost=Decimal("12.50"), quantity=4, age_days=3)
    _row_priced_row(db_session, ossa_project, warehouse, unit_cost=Decimal("7.25"), quantity=3, age_days=1)
    _stage_by_picking(db_session, ossa_project, quantity=2, ship=1)

    # Non-OSSA project: 5 units at 3.00, plus 3 staged by a pull with no pick lines - priced off the
    # project's own average for the product.
    _row_priced_row(db_session, plain_project, warehouse, unit_cost=Decimal("3.00"), quantity=5)
    _stage_without_picking(db_session, plain_project, quantity=3)

    # The jobless pool: 10 at 2.50, and 4 that know no cost and are therefore worth nothing.
    _stock_row(db_session, warehouse, quantity=10, unit_cost=Decimal("2.50"))
    _stock_row(db_session, warehouse, quantity=4, unit_cost=None, code="XX-999")

    inventory_value_repository.set_average_door_cost(db_session, company, Decimal("250.00"), "Greg")
    inventory_value_repository.save_doors_on_hand(db_session, company, None, 6)
    inventory_value_repository.save_doors_on_hand(db_session, company, ossa_project.id, 3)
    inventory_value_repository.save_doors_on_hand(db_session, company, plain_project.id, 2)
    db_session.flush()

    value = _value(db_session, company)

    # OSSA: shelf 2 x 12.50 + 3 x 7.25 = 46.75, staged 1 x 12.50 = 12.50.
    assert value["ossa"]["hardware_value"] == Decimal("59.25")
    assert value["ossa"]["door_count"] == 3
    assert value["ossa"]["door_value"] == Decimal("750.00")
    assert value["ossa"]["total_value"] == Decimal("809.25")

    # Non-OSSA: shelf 5 x 3.00 = 15.00, staged 3 x 3.00 = 9.00 off the project average.
    assert value["non_ossa"]["hardware_value"] == Decimal("24.00")
    assert value["non_ossa"]["door_count"] == 2
    assert value["non_ossa"]["door_value"] == Decimal("500.00")
    assert value["non_ossa"]["total_value"] == Decimal("524.00")

    # General stock: the pool only. The costless rows count units, not dollars.
    assert value["general_stock"]["hardware_value"] == Decimal("25.00")
    assert value["general_stock"]["door_count"] == 6
    assert value["general_stock"]["door_value"] == Decimal("1500.00")
    assert value["general_stock"]["total_value"] == Decimal("1525.00")

    assert value["average_door_cost"] == Decimal("250.00")
    assert value["average_door_cost_updated_by"] == "Greg"
    assert value["total_door_count"] == 11
    assert (value["general_door_count"], value["ossa_door_count"], value["non_ossa_door_count"]) == (6, 3, 2)

    # The general row leads the table, then the OSSA project, then the rest.
    rows = value["doors_on_hand"]
    assert [r["project_id"] for r in rows] == [None, ossa_project.id, plain_project.id]
    assert [r["is_ossa"] for r in rows] == [False, True, False]
    assert [r["quantity"] for r in rows] == [6, 3, 2]
    assert rows[1]["project_number"] == ossa_project.project_id
    assert rows[1]["project_name"] == ossa_project.description


def test_staged_hardware_is_priced_off_the_rows_it_was_picked_from(db_session):
    """A pull spanning two rows bought at different prices is worth the quantity-weighted blend of
    the two, not either one and not the project's average."""
    company = _company()
    warehouse = _warehouse(db_session, company)
    project = _project(db_session, company)

    _po_priced_row(db_session, project, warehouse, unit_cost=Decimal("12.50"), quantity=4, age_days=3)
    _row_priced_row(db_session, project, warehouse, unit_cost=Decimal("7.25"), quantity=3, age_days=1)
    # Picks all 4 of the older row and 1 of the newer: (4 x 12.50 + 1 x 7.25) / 5 = 11.50 a unit.
    _stage_by_picking(db_session, project, quantity=5, ship=2)

    value = _value(db_session, company)

    # Shelf: the older row is empty, the newer holds 2 at 7.25. Staged: 3 left at 11.50.
    assert value["non_ossa"]["hardware_value"] == Decimal("48.50")


def test_a_pull_with_no_pick_lines_falls_back_to_the_projects_average_cost(db_session):
    """Hardware staged before the pick sheet existed has no row named against it. The project's own
    average for that product is the best answer there is, and zero-quantity rows count toward it -
    a row emptied by the very pick being priced is the most relevant evidence, not the least."""
    company = _company()
    warehouse = _warehouse(db_session, company)
    project = _project(db_session, company)

    # 8.00 and 4.00 average to 6.00. The 8.00 row is emptied so it contributes nothing to the shelf.
    emptied = _row_priced_row(db_session, project, warehouse, unit_cost=Decimal("8.00"), quantity=2)
    emptied.quantity = 0
    _row_priced_row(db_session, project, warehouse, unit_cost=Decimal("4.00"), quantity=1)
    _stage_without_picking(db_session, project, quantity=5)
    db_session.flush()

    value = _value(db_session, company)

    # Shelf 1 x 4.00 = 4.00, staged 5 x 6.00 = 30.00.
    assert value["non_ossa"]["hardware_value"] == Decimal("34.00")


def test_staged_hardware_nothing_can_price_counts_zero(db_session):
    """No pick line, no inventory row, no cost anywhere. Zero rather than an invented number: this
    figure gets reported upward, and a guess in it is worse than a gap."""
    company = _company()
    _warehouse(db_session, company)
    project = _project(db_session, company)
    _stage_without_picking(db_session, project, quantity=9, code="XX-999")
    db_session.flush()

    value = _value(db_session, company)

    assert value["non_ossa"]["hardware_value"] == Decimal("0.00")
    assert value["non_ossa"]["total_value"] == Decimal("0.00")


def test_another_companys_rows_never_reach_this_companys_figures(db_session):
    """Every half of the page scopes through its own root - projects for shelf, staged and doors,
    warehouses for the pool (#637). A single unscoped half would show one tenant another's money."""
    mine = _company()
    theirs = _company()
    my_warehouse = _warehouse(db_session, mine)
    their_warehouse = _warehouse(db_session, theirs)
    my_project = _project(db_session, mine)
    their_project = _project(db_session, theirs, ossa=True)

    _row_priced_row(db_session, my_project, my_warehouse, unit_cost=Decimal("2.00"), quantity=5)
    _stock_row(db_session, my_warehouse, quantity=1, unit_cost=Decimal("1.00"))
    inventory_value_repository.save_doors_on_hand(db_session, mine, my_project.id, 1)

    _row_priced_row(db_session, their_project, their_warehouse, unit_cost=Decimal("500.00"), quantity=9)
    _stock_row(db_session, their_warehouse, quantity=9, unit_cost=Decimal("500.00"))
    inventory_value_repository.set_average_door_cost(db_session, theirs, Decimal("999.00"), "them")
    inventory_value_repository.save_doors_on_hand(db_session, theirs, their_project.id, 7)
    db_session.flush()

    value = _value(db_session, mine)

    assert value["non_ossa"]["hardware_value"] == Decimal("10.00")
    assert value["ossa"]["hardware_value"] == Decimal("0.00")
    assert value["general_stock"]["hardware_value"] == Decimal("1.00")
    assert value["average_door_cost"] == Decimal("0.00")
    assert value["total_door_count"] == 1
    assert [r["project_id"] for r in value["doors_on_hand"]] == [None, my_project.id]


def test_the_general_row_and_the_cost_row_are_created_on_first_read(db_session):
    """A company nobody has opened the page for still renders a table with its general row in it and
    a cost of zero - the page has no create step for either."""
    company = _company()
    _project(db_session, company)

    value = _value(db_session, company)
    db_session.flush()

    assert value["average_door_cost"] == Decimal("0.00")
    assert len(value["doors_on_hand"]) == 1
    general = value["doors_on_hand"][0]
    assert general["project_id"] is None
    assert general["quantity"] == 0
    assert general["project_number"] is None

    # Idempotent: a second read reuses the rows rather than making another pair.
    again = _value(db_session, company)
    assert [r["id"] for r in again["doors_on_hand"]] == [general["id"]]


def test_the_general_row_cannot_be_removed(db_session):
    company = _company()
    value = _value(db_session, company)
    db_session.flush()
    general_id = value["doors_on_hand"][0]["id"]

    with pytest.raises(ValidationError):
        inventory_value_repository.remove_doors_on_hand(db_session, general_id)


def test_a_project_of_another_company_cannot_be_given_doors(db_session):
    mine = _company()
    theirs = _company()
    their_project = _project(db_session, theirs)

    with pytest.raises(NotFoundError):
        inventory_value_repository.save_doors_on_hand(db_session, mine, their_project.id, 4)


def test_a_negative_average_door_cost_is_refused(db_session):
    company = _company()
    with pytest.raises(ValidationError):
        inventory_value_repository.set_average_door_cost(db_session, company, Decimal("-1.00"), "Greg")


def test_companies_are_listed_from_projects_and_scoped(db_session):
    company = _company()
    other = _company()
    _project(db_session, company)
    _project(db_session, other)
    db_session.flush()

    unscoped = inventory_value_repository.list_companies_with_projects(db_session, None)
    assert company in unscoped and other in unscoped

    assert inventory_value_repository.list_companies_with_projects(db_session, company) == [company]


# --- through the schema ---------------------------------------------------------------------------


INVENTORY_VALUE_FIELDS = """
  company
  ossa { hardwareValue doorCount doorValue totalValue }
  nonOssa { hardwareValue doorCount doorValue totalValue }
  generalStock { hardwareValue doorCount doorValue totalValue }
  averageDoorCost
  averageDoorCostUpdatedBy
  doorsOnHand { id projectId projectNumber projectName isOssa quantity }
  generalDoorCount
  ossaDoorCount
  nonOssaDoorCount
  totalDoorCount
"""


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(
        schema.execute(query, variable_values=variables or {}, context_value={"request": _FakeRequest()})
    )


# This file's own Clerk subject: `resolve_display_name` memoises name-by-user-id in a module-level
# TTL cache, so two files stubbing `get_user` for the SAME id would race and stamp each other's names.
_MANAGER_ID = "u_inventory_value_manager"


@pytest.fixture
def as_manager(monkeypatch, db_session):
    """A Shop Assembly Manager scoped to TUBC, whose resolvers run against the test's own session."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": _MANAGER_ID})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [SHOP_ASSEMBLY_MANAGER_ROLE])
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

    monkeypatch.setattr(inventory_value_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    yield db_session
    auth.invalidate_display_name(_MANAGER_ID)


def test_the_shop_assembly_manager_can_read_and_write_the_whole_page(as_manager, db_session):
    project = _project(db_session, "TUBC")

    read = _execute(
        f'query{{ inventoryValue(company:"TUBC"){{ {INVENTORY_VALUE_FIELDS} }} }}',
    )
    assert read.errors is None, read.errors
    page = read.data["inventoryValue"]
    assert page["company"] == "TUBC"
    # The general row and the cost row were created by the read itself.
    assert [r["projectId"] for r in page["doorsOnHand"]] == [None]
    assert page["averageDoorCost"] == 0.0

    companies = _execute("{ inventoryValueCompanies }")
    assert companies.errors is None, companies.errors
    assert companies.data["inventoryValueCompanies"] == ["TUBC"]

    saved = _execute(
        f"""mutation($input: SaveDoorsOnHandInput!){{
              saveDoorsOnHand(input:$input){{ {INVENTORY_VALUE_FIELDS} }}
            }}""",
        {"input": {"company": "TUBC", "projectId": str(project.id), "quantity": 4}},
    )
    assert saved.errors is None, saved.errors
    assert saved.data["saveDoorsOnHand"]["totalDoorCount"] == 4

    costed = _execute(
        f'mutation{{ setAverageDoorCost(company:"TUBC", amount: 125.5){{ {INVENTORY_VALUE_FIELDS} }} }}',
    )
    assert costed.errors is None, costed.errors
    page = costed.data["setAverageDoorCost"]
    assert page["averageDoorCost"] == 125.5
    # The actor is the Clerk-authenticated caller, never a name the client sent (#427).
    assert page["averageDoorCostUpdatedBy"] == "Morgan Shop"
    assert page["nonOssa"]["doorValue"] == 502.0

    row_id = next(r["id"] for r in page["doorsOnHand"] if r["projectId"] == str(project.id))
    removed = _execute(
        f"mutation($id: ID!){{ removeDoorsOnHand(id:$id){{ {INVENTORY_VALUE_FIELDS} }} }}",
        {"id": row_id},
    )
    assert removed.errors is None, removed.errors
    assert removed.data["removeDoorsOnHand"]["totalDoorCount"] == 0


def test_removing_the_general_row_is_refused_through_the_schema(as_manager, db_session):
    read = _execute('query{ inventoryValue(company:"TUBC"){ doorsOnHand { id projectId } } }')
    assert read.errors is None, read.errors
    general_id = next(r["id"] for r in read.data["inventoryValue"]["doorsOnHand"] if r["projectId"] is None)

    result = _execute(
        "mutation($id: ID!){ removeDoorsOnHand(id:$id){ totalDoorCount } }",
        {"id": general_id},
    )

    assert result.errors
    assert result.errors[0].extensions["code"] == "VALIDATION_ERROR"


def test_a_scoped_caller_cannot_name_another_companys_figures(as_manager, db_session):
    """The policy table says WHO may call; it cannot say WHICH company, because the tenant is an
    argument rather than a row. `tenancy.require_company_in_scope` is what closes that."""
    result = _execute('query{ inventoryValue(company:"UCSH"){ company } }')

    assert result.errors
    assert result.errors[0].extensions["code"] == "VALIDATION_ERROR"
    assert "TUBC" in result.errors[0].message


@pytest.mark.parametrize(
    "query",
    [
        'query{ inventoryValue(company:"TUBC"){ company } }',
        "query{ inventoryValueCompanies }",
        'mutation{ saveDoorsOnHand(input:{company:"TUBC", quantity:1}){ totalDoorCount } }',
        'mutation{ removeDoorsOnHand(id:"00000000-0000-0000-0000-000000000000"){ totalDoorCount } }',
        'mutation{ setAverageDoorCost(company:"TUBC", amount: 1.0){ averageDoorCost } }',
    ],
)
def test_a_roleless_signed_in_caller_is_refused(query, monkeypatch):
    """No `db_session`: the gate runs in the schema extension BEFORE the resolver, so a refusal that
    needed a database would mean the resolver had already started."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: ["Shop Assembly User"])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    result = _execute(query)

    assert result.errors
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
    assert result.errors[0].message == f"{ADMIN_ROLE} or {SHOP_ASSEMBLY_MANAGER_ROLE} role required"
