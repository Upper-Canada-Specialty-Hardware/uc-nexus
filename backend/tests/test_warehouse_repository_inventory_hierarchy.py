"""Tests for the quantity > 0 filter on inventory list queries (issue #145).

Rows fully emptied by destock/allocation are kept in the DB for FK integrity (they remain
the origin of stock allocations) but must not show up in the project inventory view.
"""

import uuid
from datetime import datetime

from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import warehouse_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_stock_item(session) -> StockItem:
    """A stock row used purely as a valid origin for InventoryLocation rows."""
    si = StockItem(
        id=uuid.uuid4(),
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=10,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    return si


def _make_il(session, project_id, stock_item_id, *, quantity, product_code="HG-100", hardware_category="HINGE"):
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock_item_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def test_inventory_hierarchy_hides_zero_quantity_rows(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    _make_il(db_session, project.id, origin.id, quantity=3)
    _make_il(db_session, project.id, origin.id, quantity=0)

    hierarchy = warehouse_repository.get_inventory_hierarchy(db_session, project.id)

    assert len(hierarchy) == 1
    cat = hierarchy[0]
    assert cat["total_quantity"] == 3
    pcs = cat["product_codes"]
    assert len(pcs) == 1
    assert pcs[0]["product_code"] == "HG-100"
    assert pcs[0]["total_quantity"] == 3
    # only the qty=3 row survives; the destocked-to-zero row is filtered out
    assert len(pcs[0]["items"]) == 1
    assert pcs[0]["items"][0].quantity == 3


def test_inventory_hierarchy_drops_category_when_all_rows_zero(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    _make_il(db_session, project.id, origin.id, quantity=0, product_code="HG-200")

    hierarchy = warehouse_repository.get_inventory_hierarchy(db_session, project.id)
    assert hierarchy == []


def test_inventory_items_hides_zero_quantity_rows(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    _make_il(db_session, project.id, origin.id, quantity=5)
    _make_il(db_session, project.id, origin.id, quantity=0)

    items = warehouse_repository.get_inventory_items(db_session, project.id, "HINGE", "HG-100")
    assert len(items) == 1
    assert items[0]["inventory_location"].quantity == 5


def test_inventory_by_vendor_hides_zero_quantity_rows(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    _make_il(db_session, project.id, origin.id, quantity=4)
    _make_il(db_session, project.id, origin.id, quantity=0)

    groups = warehouse_repository.get_inventory_by_vendor(db_session, project.id)
    total_qty = sum(g["total_quantity"] for g in groups)
    total_items = sum(len(pc["items"]) for g in groups for pc in g["product_codes"])
    assert total_qty == 4
    assert total_items == 1
