"""The warehouseDashboard rollup feeds the Warehouse landing cards.

The Receiving card shows `back_ordered_po_count` - the number of active POs still owed anything -
rather than the old `back_ordered_count` sum of undelivered PO-line units: a PO count answers "how
many orders still need chasing" where a unit sum did not.

The Deficient Items card `deficient_count` counts deficient units across project inventory and the
stock pool - what the review screen for damaged/short-shipped units actually lists.

The resolver-level test exists because this file used to stop at the repository, and that gap
shipped a broken dashboard (#474): the repository grew `pending_receive_draft_count`, the Strawberry
type declared it required, and the resolver's constructor never passed it - so every
warehouseDashboard call raised, and no test noticed.
"""

import asyncio
import uuid
from datetime import datetime
from decimal import Decimal

from app import auth
from app.models.enums import POStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.stock_item import StockItem
from app.repositories import user_repository, warehouse_admin_repository
from app.repositories.warehouse import progress
from app.schemas import warehouse as warehouse_schema_module
from main import schema

from .inventory_fixtures import make_stock_item


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _po(session, project, status, lines):
    """A PO with the given (ordered, received) lines. `lines` is a list of (ordered, received)."""
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=status,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    for i, (ordered, received) in enumerate(lines):
        session.add(
            POLineItem(
                id=uuid.uuid4(),
                po_id=po.id,
                hardware_category="HINGE",
                product_code=f"HG-{i}",
                ordered_quantity=ordered,
                received_quantity=received,
                unit_cost=Decimal("10.00"),
            )
        )
    session.flush()
    return po


def test_back_ordered_po_count_counts_distinct_owed_active_pos(db_session):
    """One count per active PO with any owed line, regardless of how many lines are owed; a fully
    received PO, a wrong-status PO, and a DRAFT are all excluded."""
    session = db_session
    baseline = progress.get_warehouse_dashboard(session)["back_ordered_po_count"]
    project = _make_project(session)

    # Owed, active → counts. PO with two owed lines still counts once (distinct PO).
    _po(session, project, POStatus.PARTIALLY_RECEIVED, [(5, 2)])
    _po(session, project, POStatus.GP_REGISTERED, [(3, 3), (4, 1)])
    # Fully received active PO → nothing owed → excluded.
    _po(session, project, POStatus.VENDOR_CONFIRMED, [(2, 2)])
    # Owed but not an active/received status → excluded.
    _po(session, project, POStatus.DRAFT, [(5, 0)])

    dashboard = progress.get_warehouse_dashboard(session)
    assert dashboard["back_ordered_po_count"] == baseline + 2


def test_deficient_count_sums_project_inventory_and_stock_pool(db_session):
    session = db_session
    baseline = progress.get_warehouse_dashboard(session)["deficient_count"]

    project = _make_project(session)
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    now = datetime.utcnow()

    # Stock-pool item with 2 deficient units, plus a clean one that must not count.
    session.add(
        StockItem(
            id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            hardware_category="HINGE",
            product_code="HG-DEF",
            quantity=5,
            deficient_quantity=2,
            received_at=now,
        )
    )
    session.add(
        StockItem(
            id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            hardware_category="HINGE",
            product_code="HG-OK",
            quantity=5,
            deficient_quantity=0,
            received_at=now,
        )
    )
    # Project inventory row with 3 deficient units. Rows need an origin
    # (ck_inventory_locations_has_origin), so back it with a stock item the way allocation does.
    origin = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category="LOCK",
        product_code="LK-DEF",
        quantity=4,
        deficient_quantity=0,
        received_at=now,
    )
    session.add(origin)
    session.flush()
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=origin.id,
            warehouse_id=warehouse_id,
            hardware_category="LOCK",
            product_code="LK-DEF",
            quantity=4,
            deficient_quantity=3,
            aisle="A",
            row="1",
            bay="1",
            received_at=now,
        )
    )
    session.flush()

    dashboard = progress.get_warehouse_dashboard(session)
    assert dashboard["deficient_count"] == baseline + 5


def test_stock_tiles_count_units_on_hand_and_unlocated_rows(db_session):
    """stock_item_count sums StockItem.quantity (units, like total_item_count); stock_unlocated_count
    counts rows with no aisle and quantity > 0 (rows, like unlocated_count on the project side)."""
    session = db_session
    baseline = progress.get_warehouse_dashboard(session)

    # One located row and two unlocated rows: 5 + 3 + 4 = 12 units, 2 of them unlocated.
    make_stock_item(session, quantity=5, code="ST-LOC", aisle="A", row="1", bay="1")
    make_stock_item(session, quantity=3, code="ST-U1")
    make_stock_item(session, quantity=4, code="ST-U2")

    dashboard = progress.get_warehouse_dashboard(session)
    assert dashboard["stock_item_count"] == baseline["stock_item_count"] + 12
    assert dashboard["stock_unlocated_count"] == baseline["stock_unlocated_count"] + 2


class _FakeRequest:
    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(w.capitalize() for w in rest)


def test_the_resolver_carries_every_field_the_repository_returns(db_session, monkeypatch):
    """Runs the real query through the real schema and compares against the repository dict, field
    for field. The selection set is built from the schema's own WarehouseDashboard fields, so a
    future field added to the type but dropped from the resolver's constructor fails here without
    this test ever being edited - which is exactly how #474 got out."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_dashboard"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])

    class _BorrowedSession:
        """Hands the resolver the test's transaction-bound session instead of a fresh one, so it
        reads the same uncommitted state and the rollback teardown still owns everything."""

        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(warehouse_schema_module, "SessionLocal", _BorrowedSession)

    field_names = list(schema._schema.type_map["WarehouseDashboard"].fields)
    query = f"query {{ warehouseDashboard {{ {' '.join(field_names)} }} }}"
    result = asyncio.run(schema.execute(query, context_value={"request": _FakeRequest("tok")}))

    assert result.errors is None, result.errors
    expected = progress.get_warehouse_dashboard(db_session)
    assert result.data["warehouseDashboard"] == {_camel(k): v for k, v in expected.items()}
