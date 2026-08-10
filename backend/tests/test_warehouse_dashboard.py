"""The warehouseDashboard rollup feeds the Warehouse landing cards.

The Deficient Items card showed `back_ordered_count` (undelivered PO-line units, a deliveries
concept) while linking to the review screen for damaged/short-shipped units. `deficient_count`
counts what that screen actually lists: deficient units across project inventory and the stock
pool.

The resolver-level test exists because this file used to stop at the repository, and that gap
shipped a broken dashboard (#474): the repository grew `pending_receive_draft_count`, the Strawberry
type declared it required, and the resolver's constructor never passed it - so every
warehouseDashboard call raised, and no test noticed.
"""

import asyncio
import uuid
from datetime import datetime

from app import auth
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import user_repository, warehouse_admin_repository
from app.repositories.warehouse import progress
from app.schemas import warehouse as warehouse_schema_module
from main import schema

from .inventory_fixtures import make_stock_item


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


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
