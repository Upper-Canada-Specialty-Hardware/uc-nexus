"""The warehouseDashboard rollup feeds the Warehouse landing cards.

The Deficient Items card showed `back_ordered_count` (undelivered PO-line units, a deliveries
concept) while linking to the review screen for damaged/short-shipped units. `deficient_count`
counts what that screen actually lists: deficient units across project inventory and the stock
pool.
"""

import uuid
from datetime import datetime

from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import warehouse_admin_repository
from app.repositories.warehouse import progress


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
