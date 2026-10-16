"""Where a project inventory row came from (#1699).

A row with a PO line or a shipment return says so by its own foreign key. A row with neither came out
of the stock pool, and only `entry_source` - written where the row is made - says by which path.
"""

import uuid

from app.models.enums import InventoryEntrySource, InventoryOriginKind
from app.models.inventory import InventoryLocation
from app.models.shipping import PackingSlip
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository
from app.repositories.sharepoint_migration_repository import migrate_inventory
from app.repositories.warehouse.inventory import inventory_origin
from app.repositories.warehouse.pull_requests import _return_units_to_project_inventory

from .inventory_fixtures import define_location, make_il, make_project, make_return_item, make_stock_item, wh_id

# --- the rule, on rows that never touch the database -------------------------------------------


def _row(**fields) -> InventoryLocation:
    return InventoryLocation(id=uuid.uuid4(), **fields)


def test_a_po_line_names_the_po():
    row = _row(po_line_item_id=uuid.uuid4(), receive_line_item_id=uuid.uuid4())
    assert inventory_origin(row, po_number="PO500356", packing_slip_number=None) == (
        InventoryOriginKind.PURCHASE_ORDER,
        "PO500356",
    )


def test_a_po_line_wins_over_how_a_migrated_row_came_in():
    """A migrated row matched to its PO line was received against that PO."""
    row = _row(po_line_item_id=uuid.uuid4(), entry_source=InventoryEntrySource.LEGACY_MIGRATION)
    assert inventory_origin(row, po_number="PO1", packing_slip_number=None)[0] is InventoryOriginKind.PURCHASE_ORDER


def test_a_returned_row_names_its_packing_slip():
    row = _row(shipment_return_item_id=uuid.uuid4())
    assert inventory_origin(row, po_number=None, packing_slip_number="PS-0042") == (
        InventoryOriginKind.SHIPMENT_RETURN,
        "PS-0042",
    )


def test_a_stock_origin_row_says_how_it_came_in():
    for source, kind in (
        (InventoryEntrySource.STOCK_ALLOCATION, InventoryOriginKind.STOCK_ALLOCATION),
        (InventoryEntrySource.LEGACY_MIGRATION, InventoryOriginKind.LEGACY_MIGRATION),
        (InventoryEntrySource.PULL_RESTOCK, InventoryOriginKind.PULL_RESTOCK),
    ):
        row = _row(stock_item_id=uuid.uuid4(), entry_source=source)
        assert inventory_origin(row, po_number=None, packing_slip_number=None) == (kind, None)


def test_a_stock_origin_row_nothing_recorded_is_unknown():
    row = _row(stock_item_id=uuid.uuid4())
    assert inventory_origin(row, po_number=None, packing_slip_number=None) == (InventoryOriginKind.UNKNOWN, None)


# --- the writers -------------------------------------------------------------------------------


def test_an_allocate_records_a_stock_allocation(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=5)

    il = stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code="HG-100",
        quantity=2,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )

    assert il.entry_source is InventoryEntrySource.STOCK_ALLOCATION


def test_the_legacy_migration_records_itself(db_session):
    project = make_project(db_session)
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    entry = {
        "destination": "PROJECT",
        "project_id": project.id,
        "warehouse_id": warehouse_id,
        "hardware_category": "Surface Closer",
        "product_code": "1431 CPS TB EN",
        "quantity": 3,
        "aisle": None,
        "row": None,
        "bay": None,
    }

    migrate_inventory(db_session, [entry], "migrator")
    db_session.flush()

    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    assert il.entry_source is InventoryEntrySource.LEGACY_MIGRATION


def test_a_restock_with_no_row_left_records_a_pull_restock(db_session):
    project = make_project(db_session)

    il = _return_units_to_project_inventory(db_session, project.id, "HINGE", "HG-100", 2)

    assert il.entry_source is InventoryEntrySource.PULL_RESTOCK


def test_a_transfer_keeps_how_the_units_came_in(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=6)
    il.entry_source = InventoryEntrySource.LEGACY_MIGRATION
    define_location(db_session, il.warehouse_id, "B", "2", "2")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=2,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    moved = (
        db_session.query(InventoryLocation)
        .filter(InventoryLocation.project_id == project.id, InventoryLocation.aisle == "B")
        .one()
    )
    assert moved.entry_source is InventoryEntrySource.LEGACY_MIGRATION


# --- the inventory read ------------------------------------------------------------------------


def test_inventory_rows_carry_each_rows_origin(db_session):
    project = make_project(db_session)
    allocated = make_il(db_session, project, code="HG-100")
    allocated.entry_source = InventoryEntrySource.STOCK_ALLOCATION
    returned_item = make_return_item(db_session, project, code="CL-200", category="CLOSER")
    returned = make_il(db_session, project, code="CL-200", category="CLOSER", shipment_return_item_id=returned_item.id)
    db_session.flush()

    rows = {r["inventory_location"].id: r for r in warehouse_repository.get_inventory_rows(db_session, project.id)}

    assert rows[allocated.id]["origin_kind"] is InventoryOriginKind.STOCK_ALLOCATION
    assert rows[allocated.id]["origin_reference"] is None
    slip = db_session.get(PackingSlip, returned_item.shipment_return.packing_slip_id).packing_slip_number
    assert rows[returned.id]["origin_kind"] is InventoryOriginKind.SHIPMENT_RETURN
    assert rows[returned.id]["origin_reference"] == slip
