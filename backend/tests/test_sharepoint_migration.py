"""The one-time SharePoint inventory migration.

The interesting cases are all about the origin constraint and the all-or-nothing promise: migrated
hardware has no purchase order in Nexus, so every row has to reach `inventory_locations` through the
stock pool, and a batch that fails validation anywhere must leave nothing behind.
"""

import uuid

import pytest

from app.errors import ValidationError
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import sharepoint_migration_repository as migration_repo
from app.repositories import warehouse_admin_repository

ACTOR = "Migration Tester"


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _entry(warehouse_id, **overrides) -> dict:
    entry = {
        "destination": "STOCK",
        "warehouse_id": warehouse_id,
        "hardware_category": "Surface Closer",
        "product_code": "1431 CPS TB EN",
        "quantity": 4,
        "aisle": "A",
        "row": "62",
        "bay": "R",
        "project_id": None,
    }
    entry.update(overrides)
    return entry


def test_stock_destination_creates_a_visible_stock_row(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    result = migration_repo.migrate_inventory(db_session, [_entry(wh)], ACTOR)

    assert result == {"stock_items": 1, "project_locations": 0, "total_units": 4}
    row = db_session.query(StockItem).filter_by(product_code="1431 CPS TB EN").one()
    assert row.quantity == 4
    assert (row.aisle, row.row, row.bay) == ("A", "62", "R")


def test_project_destination_creates_an_inventory_location_with_a_stock_origin(db_session):
    """The whole reason both paths go through the stock pool.

    `ck_inventory_locations_has_origin` accepts a PO origin, a stock origin, or a return origin.
    Migrated hardware has no PO, so the stock row is what makes the location row legal - and the row
    is drained to 0 so it does not also show up as shelf stock the warehouse can pull from.
    """
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)

    result = migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=7)],
        ACTOR,
    )
    db_session.flush()

    assert result == {"stock_items": 0, "project_locations": 1, "total_units": 7}
    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    assert il.quantity == 7
    assert il.stock_item_id is not None
    assert il.po_line_item_id is None
    assert il.receive_line_item_id is None
    assert db_session.get(StockItem, il.stock_item_id).quantity == 0


def test_a_row_with_both_quantities_migrates_as_two_entries(db_session):
    """SharePoint lets one part carry both project and shelf quantity; Nexus keeps them apart."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)

    result = migration_repo.migrate_inventory(
        db_session,
        [
            _entry(wh, destination="PROJECT", project_id=project.id, quantity=3),
            _entry(wh, destination="STOCK", quantity=5),
        ],
        ACTOR,
    )

    assert result == {"stock_items": 1, "project_locations": 1, "total_units": 8}


def test_locations_are_optional(db_session):
    """340 SharePoint rows have no location string at all; they still hold real hardware."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(
        db_session, [_entry(wh, aisle=None, row=None, bay=None, product_code="NOLOC-1")], ACTOR
    )

    row = db_session.query(StockItem).filter_by(product_code="NOLOC-1").one()
    assert (row.aisle, row.row, row.bay) == (None, None, None)


@pytest.mark.parametrize(
    "overrides, expected",
    [
        ({"quantity": 0}, "positive integer"),
        ({"quantity": -1}, "positive integer"),
        ({"hardware_category": "  "}, "hardware_category is required"),
        ({"product_code": ""}, "product_code is required"),
        ({"destination": "ELSEWHERE"}, "PROJECT or STOCK"),
        ({"destination": "PROJECT", "project_id": None}, "project_id is required"),
    ],
)
def test_invalid_entries_are_refused(db_session, overrides, expected):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, **overrides)], ACTOR)
    assert expected in e.value.message


def test_unknown_project_is_refused(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(
            db_session, [_entry(wh, destination="PROJECT", project_id=uuid.uuid4())], ACTOR
        )
    assert "Unknown project" in e.value.message


def test_unknown_warehouse_is_refused(db_session):
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(uuid.uuid4())], ACTOR)
    assert "Unknown warehouse" in e.value.message


def test_empty_batch_is_refused(db_session):
    with pytest.raises(ValidationError):
        migration_repo.migrate_inventory(db_session, [], ACTOR)


def test_a_bad_entry_writes_nothing_at_all(db_session):
    """Validation runs over the whole batch first, so a bad row 3 does not half-apply rows 1 and 2."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    before = db_session.query(StockItem).count()

    with pytest.raises(ValidationError):
        migration_repo.migrate_inventory(
            db_session,
            [
                _entry(wh, product_code="GOOD-1"),
                _entry(wh, product_code="GOOD-2"),
                _entry(wh, product_code="BAD-3", quantity=0),
            ],
            ACTOR,
        )

    assert db_session.query(StockItem).count() == before
    assert db_session.query(StockItem).filter_by(product_code="GOOD-1").count() == 0


def test_validation_failure_names_the_offending_entry(db_session):
    """A 2000-row batch failing on "aisle must be 1-20 characters" is unactionable without this."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh), _entry(wh, quantity=0, product_code="BAD")], ACTOR)
    assert "Entry 2" in e.value.message


def test_has_any_inventory_tracks_the_rerun_warning(db_session):
    # Both sides: a helper that returned True unconditionally would pass on the second assert alone.
    assert migration_repo.has_any_inventory(db_session) is False
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(db_session, [_entry(wh)], ACTOR)
    db_session.flush()
    assert migration_repo.has_any_inventory(db_session) is True


def test_an_over_long_location_is_a_named_validation_error(db_session):
    """aisle/row/bay are String(20); without an explicit check this dies as a raw 500 mid-batch."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, aisle="Warehouse Overflow Rack")], ACTOR)
    assert "aisle" in e.value.message and "20 characters" in e.value.message


def test_identity_fields_are_written_stripped(db_session):
    """A trailing space is a distinct identity that could never match a schedule pair."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(
        db_session, [_entry(wh, hardware_category=" Hinge ", product_code=" BB1279 ")], ACTOR
    )
    row = db_session.query(StockItem).filter_by(product_code="BB1279").one()
    assert row.hardware_category == "Hinge"


def test_stock_items_counts_rows_not_entries(db_session):
    """Two entries for one part on one shelf merge into a single StockItem, and must report as one."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    result = migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, product_code="SAME-1", quantity=3), _entry(wh, product_code="SAME-1", quantity=4)],
        ACTOR,
    )
    assert result["stock_items"] == 1
    assert result["total_units"] == 7
    assert db_session.query(StockItem).filter_by(product_code="SAME-1").one().quantity == 7


def test_both_migration_fields_are_admin_only():
    """Bulk inventory writes and a read of another system on company credentials. Not SIGNED_IN."""
    from app.auth import ADMIN_ROLE
    from app.auth_policy import ROOT_FIELD_POLICY

    assert ROOT_FIELD_POLICY["sharepointInventorySnapshot"] == ADMIN_ROLE
    assert ROOT_FIELD_POLICY["migrateSharepointInventory"] == ADMIN_ROLE
