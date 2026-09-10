"""The one-time SharePoint inventory migration.

The interesting cases are all about the origin constraint and the all-or-nothing promise: migrated
hardware has no purchase order in Nexus, so every row has to reach `inventory_locations` through the
stock pool, and a batch that fails validation anywhere must leave nothing behind.
"""

import uuid
from decimal import Decimal

import pytest

from app.auth import ADMIN_ROLE
from app.errors import ValidationError
from app.models.enums import Classification, DestockSource, HardwareItemState, POOrigin, POStatus
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.stock_item import StockItem
from app.repositories import sharepoint_migration_repository as migration_repo
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository

from .inventory_fixtures import define_location

ACTOR = "Migration Tester"

# The default _entry's identity, so schedule rows built for marking/classification match it exactly.
CAT = "Surface Closer"
CODE = "1431 CPS TB EN"


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _make_opening(session, project_id: uuid.UUID, opening_number: str) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project_id, opening_number=opening_number)
    session.add(o)
    session.flush()
    return o


def _make_hi(
    session,
    project,
    opening,
    *,
    quantity=1,
    classification=None,
    state=HardwareItemState.AVAILABLE,
    code=CODE,
    category=CAT,
):
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=category,
        product_code=code,
        item_quantity=quantity,
        classification=classification,
        state=state,
    )
    session.add(hi)
    session.flush()
    return hi


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


@pytest.fixture(autouse=True)
def _default_shelf_is_defined(request):
    """#632: a PROJECT-destination entry allocates onto the shelf it carries, and an allocate target
    has to be a defined location. Every entry in this file uses `_entry`'s default triple, so it is
    defined once here rather than 17 times. Skipped for the handful of pure tests in this module -
    they take no db_session and must not start needing a database.
    """
    if "db_session" not in request.fixturenames:
        return
    session = request.getfixturevalue("db_session")
    define_location(session, warehouse_admin_repository.get_primary_warehouse_id(session), "A", "62", "R")


def test_stock_destination_creates_a_visible_stock_row(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    result = migration_repo.migrate_inventory(db_session, [_entry(wh)], ACTOR)

    assert result == {"stock_items": 1, "project_locations": 0, "total_units": 4, "linked_entries": 0}
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

    assert result == {"stock_items": 0, "project_locations": 1, "total_units": 7, "linked_entries": 0}
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

    assert result == {"stock_items": 1, "project_locations": 1, "total_units": 8, "linked_entries": 0}


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


def test_has_migration_run_tracks_the_rerun_warning(db_session):
    # Both sides: a helper that returned True unconditionally would pass on the second assert alone.
    assert migration_repo.has_migration_run(db_session) is False
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(db_session, [_entry(wh)], ACTOR)
    db_session.flush()
    assert migration_repo.has_migration_run(db_session) is True


def test_run_marker_records_the_counts(db_session):
    """The marker is definitive because it is the migration itself that writes it, with its counts."""
    from app.models.sharepoint_migration_run import SharepointMigrationRun

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, quantity=3), _entry(wh, product_code="OTHER-1", quantity=5)],
        ACTOR,
    )
    run = db_session.query(SharepointMigrationRun).one()
    assert run.performed_by == ACTOR
    assert run.entry_count == 2
    assert run.unit_count == 8


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


# --- non-schedule entity types (#454) ----------------------------------------------------------


def _specialty_type(session):
    from app.repositories import custom_items_repository

    return custom_items_repository.get_item_types(session, active_only=True)[0]


def test_catalog_items_are_created_with_their_attribute_values(db_session):
    """The descriptive half of the migration: without it the quantities arrive and the words do not."""
    from app.repositories import custom_items_repository

    t = _specialty_type(db_session)
    result = migration_repo.migrate_catalog_items(
        db_session,
        [
            {
                "type_id": t.id,
                "product_code": "GRAB-42",
                "description": "Bariatric Grab Bar, 42in",
                "values": [
                    {"attribute_name": "Finish", "value": "Satin"},
                    {"attribute_name": "Rating", "value": "80A"},
                ],
            }
        ],
    )
    db_session.flush()

    assert result["items_created"] == 1
    # The seeded types carry no attributes, so the source's columns become them.
    assert result["attributes_created"] == 2
    item = custom_items_repository.get_items(db_session, type_id=t.id)[0]
    assert item.product_code == "GRAB-42"
    assert {v.attribute.name: v.value for v in item.values} == {"Finish": "Satin", "Rating": "80A"}


def test_an_attribute_is_reused_across_items_rather_than_duplicated(db_session):
    t = _specialty_type(db_session)
    result = migration_repo.migrate_catalog_items(
        db_session,
        [
            {"type_id": t.id, "product_code": "A-1", "values": [{"attribute_name": "Finish", "value": "Satin"}]},
            {"type_id": t.id, "product_code": "A-2", "values": [{"attribute_name": "Finish", "value": "Bronze"}]},
        ],
    )
    assert result["items_created"] == 2
    assert result["attributes_created"] == 1


def test_a_product_code_already_catalogued_is_skipped_not_refused(db_session):
    """Re-running, or migrating a code the warehouse already entered by hand, is not an error."""
    t = _specialty_type(db_session)
    migration_repo.migrate_catalog_items(db_session, [{"type_id": t.id, "product_code": "GRAB-42"}])
    db_session.flush()
    result = migration_repo.migrate_catalog_items(db_session, [{"type_id": t.id, "product_code": "GRAB-42"}])

    assert result == {"items_created": 0, "items_skipped": 1, "attributes_created": 0}


def test_blank_attribute_values_are_not_recorded(db_session):
    t = _specialty_type(db_session)
    result = migration_repo.migrate_catalog_items(
        db_session,
        [{"type_id": t.id, "product_code": "A-1", "values": [{"attribute_name": "Finish", "value": "  "}]}],
    )
    assert result["attributes_created"] == 0


# --- unit cost carried onto the rows (no PO line to hang it on) ----------------------------------


def test_clean_unit_cost_normalizes_the_source_value():
    """Pure: blank / zero / negative / unparseable all read as no cost, a real number becomes Decimal."""
    assert migration_repo._clean_unit_cost(None) is None
    assert migration_repo._clean_unit_cost(0) is None
    assert migration_repo._clean_unit_cost(-3) is None
    assert migration_repo._clean_unit_cost("nope") is None
    assert migration_repo._clean_unit_cost("12.50") == Decimal("12.50")
    assert migration_repo._clean_unit_cost(4) == Decimal("4")


def test_clone_origin_fields_carries_unit_cost():
    """The one change that propagates cost through every derived row (transfer, split, override)."""
    from app.repositories.warehouse import clone_origin_fields

    il = InventoryLocation(
        po_line_item_id=None,
        receive_line_item_id=None,
        stock_item_id=uuid.uuid4(),
        shipment_return_item_id=None,
        unit_cost=Decimal("5.5"),
    )
    fields = clone_origin_fields(il)
    assert fields["unit_cost"] == Decimal("5.5")
    assert set(fields) == {
        "po_line_item_id",
        "receive_line_item_id",
        "stock_item_id",
        "shipment_return_item_id",
        "unit_cost",
    }


def test_unit_cost_lands_on_the_stock_row(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    migration_repo.migrate_inventory(db_session, [_entry(wh, unit_cost=7.25)], ACTOR)
    row = db_session.query(StockItem).filter_by(product_code=CODE).one()
    assert row.unit_cost == Decimal("7.2500")


def test_unit_cost_travels_onto_the_project_row(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4, unit_cost=6)],
        ACTOR,
    )
    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    assert il.unit_cost == Decimal("6")


def test_project_entries_price_by_their_own_cost_not_the_pool_first_cost(db_session):
    """Two same-shelf entries merge into ONE pool row that keeps the first cost; each project's
    units must still carry their own entry's cost, whichever landed first."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    p1 = _make_project(db_session)
    p2 = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [
            _entry(wh, destination="PROJECT", project_id=p1.id, quantity=2, unit_cost=4),
            _entry(wh, destination="PROJECT", project_id=p2.id, quantity=3, unit_cost=9),
        ],
        ACTOR,
    )
    il1 = db_session.query(InventoryLocation).filter_by(project_id=p1.id).one()
    il2 = db_session.query(InventoryLocation).filter_by(project_id=p2.id).one()
    assert il1.unit_cost == Decimal("4")
    assert il2.unit_cost == Decimal("9")


def test_an_empty_pool_row_forgets_its_migration_cost(db_session):
    """A drained pool row's cost describes units that are gone. The next receipt into that shelf
    (a stock PO passes no cost) must not inherit the stale migration price."""
    from datetime import datetime

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=2, unit_cost=4)],
        ACTOR,
    )
    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    drained = db_session.get(StockItem, il.stock_item_id)
    assert drained.quantity == 0

    refilled = stock_repository.receive_into_stock(
        db_session,
        warehouse_id=wh,
        hardware_category=CAT,
        product_code=CODE,
        quantity=5,
        deficient_quantity=0,
        aisle="A",
        row="62",
        bay="R",
        received_at=datetime.utcnow(),
        received_by=ACTOR,
        po_number="PO-1",
    )
    assert refilled.id == drained.id
    assert refilled.unit_cost is None


def test_an_over_large_unit_cost_is_a_named_validation_error(db_session):
    """The cost columns are Numeric(19, 5); without the check this dies at flush as a raw 500."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, unit_cost="123456789012345.67")], ACTOR)
    assert "Entry 1" in e.value.message and "unit_cost" in e.value.message


def test_clean_unit_cost_rejects_non_finite_values():
    """Decimal('nan') parses; comparing it raises. The finite check has to come first."""
    assert migration_repo._clean_unit_cost("nan") is None
    assert migration_repo._clean_unit_cost("inf") is None


def test_cost_carries_back_through_destock(db_session):
    """A destocked migrated unit keeps its value: the pool row it lands on picks up the row's cost."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4, unit_cost=6)],
        ACTOR,
    )
    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    stock = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=2,
        source=DestockSource.OVERAGE,
        reason_text="count",
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by=ACTOR,
    )
    assert stock.unit_cost == Decimal("6")


def test_cost_carries_through_a_transfer(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4, unit_cost=6)],
        ACTOR,
    )
    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    # A transfer destination is a location the user chose, so it has to be defined first (#632).
    define_location(db_session, wh, "Z", "9", "Q")
    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=2,
        dest_warehouse_id=wh,
        dest_aisle="Z",
        dest_row="9",
        dest_bay="Q",
        performed_by=ACTOR,
    )
    moved = db_session.query(InventoryLocation).filter_by(project_id=project.id, aisle="Z", row="9", bay="Q").one()
    assert moved.unit_cost == Decimal("6")


def test_migrated_stock_values_by_its_own_unit_cost(db_session):
    """The valuation coalesce: with no PO line, a migrated row values off its own cost, not zero."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4, unit_cost=5)],
        ACTOR,
    )
    dashboard = warehouse_repository.get_warehouse_dashboard(db_session)
    assert dashboard["total_value"] == 20.0

    rows = warehouse_repository.get_inventory_rows(db_session, project.id)
    assert rows[0]["unit_cost"] == 5.0
    assert rows[0]["line_value"] == 20.0


def test_a_migrated_row_with_no_cost_values_at_zero(db_session):
    """The final fallback in coalesce(po_line, row, 0): a row with neither cost is 0, not an error."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4)],
        ACTOR,
    )
    assert warehouse_repository.get_warehouse_dashboard(db_session)["total_value"] == 0.0


# --- classification written onto matching schedule rows (inherit never overwrites) --------------


def test_classification_written_only_where_null(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    o2 = _make_opening(db_session, project.id, "A02")
    unclassified = _make_hi(db_session, project, o1, quantity=1, classification=None)
    already = _make_hi(db_session, project, o2, quantity=1, classification=Classification.SHOP_HARDWARE)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh)],  # a STOCK entry; the classification write is independent of what is migrated
        ACTOR,
        classifications=[
            {
                "project_id": project.id,
                "hardware_category": CAT,
                "product_code": CODE,
                "classification": Classification.SITE_HARDWARE,
            }
        ],
    )
    db_session.refresh(unclassified)
    db_session.refresh(already)
    assert unclassified.classification == Classification.SITE_HARDWARE
    assert already.classification == Classification.SHOP_HARDWARE


# --- covered schedule rows flip to IN_PO, greedy floor ------------------------------------------


def test_marking_flips_available_rows_greedy_floor(db_session):
    """N=5 covers the first opening (3) but not the second (would be 6), which stays AVAILABLE."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    o2 = _make_opening(db_session, project.id, "A02")
    hi1 = _make_hi(db_session, project, o1, quantity=3)
    hi2 = _make_hi(db_session, project, o2, quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=5)],
        ACTOR,
    )
    db_session.refresh(hi1)
    db_session.refresh(hi2)
    assert hi1.state == HardwareItemState.IN_PO
    assert hi1.po_line_item_id is None  # marked, but linked to no PO Nexus holds
    assert hi2.state == HardwareItemState.AVAILABLE


def test_marking_covers_every_row_when_the_quantity_fits(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    o2 = _make_opening(db_session, project.id, "A02")
    hi1 = _make_hi(db_session, project, o1, quantity=3)
    hi2 = _make_hi(db_session, project, o2, quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=6)],
        ACTOR,
    )
    db_session.refresh(hi1)
    db_session.refresh(hi2)
    assert hi1.state == HardwareItemState.IN_PO
    assert hi2.state == HardwareItemState.IN_PO


def test_marking_skips_an_overflowing_row_and_marks_the_later_fit(db_session):
    """Quantities 3, 3, 1 against N=4: the second row overflows and is skipped, the third still fits.
    A `break` there under-marked coverage whenever a large row preceded small ones."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    rows = [
        _make_hi(db_session, project, _make_opening(db_session, project.id, number), quantity=qty)
        for number, qty in (("A01", 3), ("A02", 3), ("A03", 1))
    ]

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4)],
        ACTOR,
    )
    states = [db_session.get(HardwareItem, hi.id).state for hi in rows]
    assert states == [HardwareItemState.IN_PO, HardwareItemState.AVAILABLE, HardwareItemState.IN_PO]


def test_marks_record_the_coverage_targets(db_session):
    """The marking would be wiped by a schedule replace; the marks are what lets finalize re-apply it."""
    from app.models.sharepoint_migration_run import SharepointMigrationMark

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    _make_hi(db_session, project, _make_opening(db_session, project.id, "A01"), quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=5)],
        ACTOR,
    )
    mark = db_session.query(SharepointMigrationMark).one()
    assert (mark.project_id, mark.hardware_category, mark.product_code) == (project.id, CAT, CODE)
    # The TARGET (what landed on the shelf), not the 3 units the greedy pass happened to cover.
    assert mark.quantity == 5
    assert mark.run_id is not None


def test_reapply_marks_after_a_schedule_replace(db_session):
    """replace_schedule wipes every HardwareItem, marking included; the recorded target re-marks the
    regenerated rows so the project does not read as never-purchased again."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    old = _make_hi(db_session, project, o1, quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=3)],
        ACTOR,
    )
    assert db_session.get(HardwareItem, old.id).state == HardwareItemState.IN_PO

    # The replace: every row wiped, the new schedule's rows arrive AVAILABLE.
    db_session.delete(old)
    db_session.flush()
    new = _make_hi(db_session, project, o1, quantity=3)

    remarked = migration_repo.reapply_migration_marks(db_session, project.id)
    assert remarked == 1
    assert db_session.get(HardwareItem, new.id).state == HardwareItemState.IN_PO
    # Idempotent: the surviving marked rows already cover the target, so a second pass marks nothing.
    assert migration_repo.reapply_migration_marks(db_session, project.id) == 0


def test_reapply_is_a_no_op_without_marks(db_session):
    project = _make_project(db_session)
    assert migration_repo.reapply_migration_marks(db_session, project.id) == 0


def test_reconcile_counts_marked_rows_as_received(db_session):
    """The recon inner join through po_line_item_id never sees a null-linked IN_PO row, so migrated
    coverage read as NOT_COVERED, got auto-selected on a PO re-import, and a real PO was drafted for
    units already on the shelf."""
    from app.repositories import import_repository

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    _make_hi(db_session, project, _make_opening(db_session, project.id, "A01"), quantity=4)
    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=4)],
        ACTOR,
    )

    results = import_repository.reconcile_schedule(
        db_session,
        project.id,
        [{"opening_number": "A01", "hardware_category": CAT, "product_code": CODE, "quantity_needed": 4}],
    )
    by_status = {r["status"]: r["quantity"] for r in results}
    assert by_status == {"RECEIVED": 4}


def test_marking_is_ordered_by_opening_number(db_session):
    """Deterministic order (opening_number, id): the lower opening is the one that gets covered."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    # Insert the higher opening first, so a naive insertion-order mark would pick the wrong row.
    o_high = _make_opening(db_session, project.id, "B99")
    o_low = _make_opening(db_session, project.id, "A01")
    hi_high = _make_hi(db_session, project, o_high, quantity=3)
    hi_low = _make_hi(db_session, project, o_low, quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=3)],
        ACTOR,
    )
    db_session.refresh(hi_high)
    db_session.refresh(hi_low)
    assert hi_low.state == HardwareItemState.IN_PO
    assert hi_high.state == HardwareItemState.AVAILABLE


# --- the light schedule-products query the wizard snaps + classifies from ------------------------


def test_project_schedule_products_returns_every_category_pair(db_session):
    """A code split across categories is EVERY pair, not one dominant winner - collapsing left the
    minority pair's rows unmarked and unclassified. Classification is dominant WITHIN each pair, and
    required_quantity is the pair's units (the wizard's split budget), largest pair first."""
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    o2 = _make_opening(db_session, project.id, "A02")
    o3 = _make_opening(db_session, project.id, "A03")
    _make_hi(
        db_session, project, o1, code="X-1", category="Hinge", quantity=5, classification=Classification.SITE_HARDWARE
    )
    _make_hi(db_session, project, o2, code="X-1", category="Hinge", quantity=1, classification=None)
    _make_hi(
        db_session, project, o3, code="X-1", category="Lock", quantity=2, classification=Classification.SHOP_HARDWARE
    )

    rows = warehouse_repository.get_project_schedule_products(db_session, [project.id])
    pairs = [(r["hardware_category"], r["classification"], r["required_quantity"]) for r in rows]
    assert pairs == [
        ("Hinge", Classification.SITE_HARDWARE, 6),  # SITE covers 5 of the 6 Hinge units
        ("Lock", Classification.SHOP_HARDWARE, 2),
    ]


def test_project_schedule_products_is_empty_for_no_projects(db_session):
    assert warehouse_repository.get_project_schedule_products(db_session, []) == []


def test_no_catalog_items_is_a_no_op(db_session):
    assert migration_repo.migrate_catalog_items(db_session, []) == {
        "items_created": 0,
        "items_skipped": 0,
        "attributes_created": 0,
    }


# --- attaching migrated stock to the GP PO LINE ITEM it was bought on ----------------------------


def _mirrored_po(
    session,
    *,
    project=None,
    origin=POOrigin.GP,
    status=POStatus.CLOSED,
    ordered=10,
    received=10,
    po_number=None,
    company="TUBC",
):
    """A mirrored PO with one line that is not a NEXUS REGISTERED LINE.

    What the FIRST TIME GP COMPANY NEXUS INITIALIZATION leaves behind on a PO nobody raised in Nexus:
    GP's cost bucket as the item number (product_code) and the part number as GP's item description
    (hardware_category). CLOSED by default, because UBC's shelf stock was received years ago.
    """
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=company,
        gp_company=company,
        po_number=po_number or f"PO{uuid.uuid4().hex[:6].upper()}",
        origin=origin,
        project_id=project.id if project is not None else None,
        status=status,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        gp_line_ord=16384,
        hardware_category=f"{CODE} SURFACE CLOSER",
        product_code="HD 001",
        ordered_quantity=ordered,
        received_quantity=received,
        unit_cost=Decimal("120.00"),
        nexus_registered=False,
    )
    session.add(line)
    session.flush()
    return po, line


def test_a_linked_project_entry_lands_as_a_receipt_against_the_line(db_session):
    """The whole point of the link: the units stop being off-PO stock and become PO'd hardware.

    The receipt is Nexus-side history only - GP counted these units when they were received years
    ago, so the line's received quantity must not move and no GP RECEIVE ENTRY is made.
    """
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    po, line = _mirrored_po(db_session, project=project)

    result = migration_repo.migrate_inventory(
        db_session,
        [
            _entry(
                wh,
                destination="PROJECT",
                project_id=project.id,
                quantity=4,
                unit_cost=9.5,
                po_line_item_id=line.id,
            )
        ],
        ACTOR,
    )

    assert result == {"stock_items": 0, "project_locations": 1, "total_units": 4, "linked_entries": 1}
    # No stock pool row at all: a linked entry takes the other branch of the origin constraint.
    assert db_session.query(StockItem).count() == 0

    receipt = db_session.query(ReceiveRecord).filter_by(po_id=po.id).one()
    assert receipt.received_by == ACTOR
    assert receipt.receipt_number is None
    assert receipt.batch_number is None
    assert receipt.notes == "SharePoint migration"

    receive_line = db_session.query(ReceiveLineItem).filter_by(receive_record_id=receipt.id).one()
    assert receive_line.po_line_item_id == line.id
    assert receive_line.quantity_received == 4
    assert (receive_line.hardware_category, receive_line.product_code) == (CAT, CODE)

    il = db_session.query(InventoryLocation).filter_by(project_id=project.id).one()
    assert il.po_line_item_id == line.id
    assert il.receive_line_item_id == receive_line.id
    assert il.stock_item_id is None
    assert il.quantity == 4
    # Null so valuation reads the line's GP cost, which is a better number than the SharePoint one.
    assert il.unit_cost is None

    db_session.refresh(line)
    assert line.received_quantity == 10
    assert line.nexus_registered is True
    assert (line.hardware_category, line.product_code) == (CAT, CODE)


def test_entries_on_one_po_share_a_single_receipt(db_session):
    """One migration run is one historical delivery per PO, not one per row."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    po, line = _mirrored_po(db_session, project=project)

    migration_repo.migrate_inventory(
        db_session,
        [
            _entry(wh, destination="PROJECT", project_id=project.id, quantity=2, po_line_item_id=line.id),
            _entry(wh, destination="PROJECT", project_id=project.id, quantity=3, po_line_item_id=line.id),
        ],
        ACTOR,
    )

    assert db_session.query(ReceiveRecord).filter_by(po_id=po.id).count() == 1
    assert db_session.query(ReceiveLineItem).count() == 2


def test_a_linked_project_entry_ties_the_marked_schedule_rows_to_the_line(db_session):
    """Marked AND linked: the coverage reads through the PO instead of as an unattributed marking."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    _po, line = _mirrored_po(db_session, project=project)
    hi = _make_hi(db_session, project, _make_opening(db_session, project.id, "A01"), quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=3, po_line_item_id=line.id)],
        ACTOR,
    )

    db_session.refresh(hi)
    assert hi.state == HardwareItemState.IN_PO
    assert hi.po_line_item_id == line.id


def test_the_mark_records_the_line_the_units_came_off(db_session):
    from app.models.sharepoint_migration_run import SharepointMigrationMark

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    _po, line = _mirrored_po(db_session, project=project)
    _make_hi(db_session, project, _make_opening(db_session, project.id, "A01"), quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=3, po_line_item_id=line.id)],
        ACTOR,
    )

    mark = db_session.query(SharepointMigrationMark).one()
    assert mark.po_line_item_id == line.id
    assert mark.quantity == 3


def test_reapply_re_ties_a_linked_mark_after_a_schedule_replace(db_session):
    """A re-import wipes the tie with the rows; the mark is what puts it back on the same line."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    project = _make_project(db_session)
    _po, line = _mirrored_po(db_session, project=project)
    o1 = _make_opening(db_session, project.id, "A01")
    old = _make_hi(db_session, project, o1, quantity=3)

    migration_repo.migrate_inventory(
        db_session,
        [_entry(wh, destination="PROJECT", project_id=project.id, quantity=3, po_line_item_id=line.id)],
        ACTOR,
    )
    assert db_session.get(HardwareItem, old.id).po_line_item_id == line.id

    db_session.delete(old)
    db_session.flush()
    new = _make_hi(db_session, project, o1, quantity=3)

    assert migration_repo.reapply_migration_marks(db_session, project.id) == 1
    db_session.refresh(new)
    assert new.state == HardwareItemState.IN_PO
    assert new.po_line_item_id == line.id
    # Idempotent: the re-tied rows already cover the target, so a second pass marks nothing.
    assert migration_repo.reapply_migration_marks(db_session, project.id) == 0


def test_a_linked_stock_entry_keeps_the_stock_pool_route(db_session):
    """Ruling: the pool is fungible and a StockItem holds no purchase order, so the PO number reaches
    the audit detail and nothing else. The line still learns what it was really for."""
    from app.models.audit_log import InventoryAuditLog

    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    po, line = _mirrored_po(db_session, project=None)

    result = migration_repo.migrate_inventory(db_session, [_entry(wh, po_line_item_id=line.id)], ACTOR)

    assert result == {"stock_items": 1, "project_locations": 0, "total_units": 4, "linked_entries": 1}
    stock_row = db_session.query(StockItem).filter_by(product_code=CODE).one()
    assert stock_row.quantity == 4
    # Nothing of the receipt route: no receive record, no PO-origin inventory row.
    assert db_session.query(ReceiveRecord).count() == 0
    assert db_session.query(InventoryLocation).count() == 0

    entries = db_session.query(InventoryAuditLog).filter_by(entity_id=stock_row.id).all()
    assert [e.detail["poNumber"] for e in entries] == [po.po_number]

    db_session.refresh(line)
    assert line.nexus_registered is True
    assert (line.hardware_category, line.product_code) == (CAT, CODE)


def test_two_rows_disagreeing_about_one_line_are_refused_and_both_named(db_session):
    """A line may carry exactly one identity. Naming only one of the pair leaves the user guessing
    which row to re-resolve."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    _po, line = _mirrored_po(db_session, project=None)

    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(
            db_session,
            [
                _entry(wh, po_line_item_id=line.id),
                _entry(wh, product_code="OTHER-1", po_line_item_id=line.id),
            ],
            ACTOR,
        )

    assert "Entry 1" in e.value.message and "Entry 2" in e.value.message
    assert db_session.query(StockItem).count() == 0
    db_session.refresh(line)
    assert line.nexus_registered is False


def test_a_row_repointing_an_already_registered_line_is_refused(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    _po, line = _mirrored_po(db_session, project=None)
    line.hardware_category = "Hinge"
    line.product_code = "BB1279"
    line.nexus_registered = True
    db_session.flush()

    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, po_line_item_id=line.id)], ACTOR)

    assert "already registered" in e.value.message
    db_session.refresh(line)
    assert (line.hardware_category, line.product_code) == ("Hinge", "BB1279")


def test_a_line_on_a_nexus_raised_po_is_refused(db_session):
    """A Nexus PO's lines were written from a schedule; there is nothing a shelf count can teach them."""
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    _po, line = _mirrored_po(db_session, project=None, origin=POOrigin.NEXUS)

    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, po_line_item_id=line.id)], ACTOR)

    assert "raised in Nexus" in e.value.message
    assert db_session.query(StockItem).count() == 0


def test_an_unknown_po_line_is_refused(db_session):
    wh = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    with pytest.raises(ValidationError) as e:
        migration_repo.migrate_inventory(db_session, [_entry(wh, po_line_item_id=uuid.uuid4())], ACTOR)
    assert "Unknown purchase order line" in e.value.message


# --- the PO lookup the Reconcile GP PO link step reads ------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _admin_context():
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_admin",
        "_auth_roles": [ADMIN_ROLE],
        "_auth_company": "TUBC",
    }


@pytest.fixture
def signed_in_admin(monkeypatch, db_session):
    """An Admin/Manager whose migration resolvers run against the test's own session."""
    from app import auth
    from app.repositories import user_repository
    from app.schemas import sharepoint_migration as migration_module

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_admin"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [ADMIN_ROLE])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(migration_module, "SessionLocal", _Borrowed)
    return db_session


_MIRRORED_POS_QUERY = """
query($poNumbers: [String!]!) {
  mirroredPosByNumber(poNumbers: $poNumbers) {
    poNumber
    status
    origin
    projectId
    lines { gpLineOrd productCode hardwareCategory orderedQuantity receivedQuantity nexusRegistered }
  }
}
"""


def _execute(query: str, variables: dict, context: dict):
    import asyncio

    from main import schema

    return asyncio.run(schema.execute(query, variable_values=variables, context_value=context))


def test_mirrored_pos_by_number_returns_the_pos_lines(signed_in_admin, db_session):
    project = _make_project(db_session)
    _po, line = _mirrored_po(db_session, project=project, po_number="PO501788", ordered=6, received=6)

    result = _execute(_MIRRORED_POS_QUERY, {"poNumbers": ["PO501788", "PO999999"]}, _admin_context())

    assert result.errors is None, result.errors
    rows = result.data["mirroredPosByNumber"]
    assert len(rows) == 1
    assert rows[0]["poNumber"] == "PO501788"
    assert rows[0]["projectId"] == str(project.id)
    assert rows[0]["lines"] == [
        {
            "gpLineOrd": 16384,
            "productCode": "HD 001",
            "hardwareCategory": line.hardware_category,
            "orderedQuantity": 6,
            "receivedQuantity": 6,
            "nexusRegistered": False,
        }
    ]


def test_mirrored_pos_by_number_refuses_more_than_two_hundred_numbers(signed_in_admin):
    result = _execute(
        _MIRRORED_POS_QUERY,
        {"poNumbers": [f"PO{n:06d}" for n in range(201)]},
        _admin_context(),
    )

    assert result.errors is not None
    assert "200" in str(result.errors[0].message)


def test_mirrored_pos_by_number_is_scoped_to_the_callers_company(db_session, monkeypatch):
    """The resolver filters on the caller's scope. Reached directly because the field is admin-only
    and an admin is deliberately unscoped, so the schema can never exercise the scoped branch."""
    from app.schemas import sharepoint_migration as migration_module

    _mirrored_po(db_session, project=None, po_number="PO600001", company="TUBC")
    _mirrored_po(db_session, project=None, po_number="PO600002", company="TUCSH")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(migration_module, "SessionLocal", _Borrowed)
    monkeypatch.setattr(migration_module, "tenant_scope", lambda info: "TUCSH")

    rows = migration_module.SharepointMigrationQueries().mirrored_pos_by_number(None, ["PO600001", "PO600002"])

    assert [r.po_number for r in rows] == ["PO600002"]


def test_the_po_lookup_is_admin_only():
    from app.auth_policy import ROOT_FIELD_POLICY

    assert ROOT_FIELD_POLICY["mirroredPosByNumber"] == ADMIN_ROLE
