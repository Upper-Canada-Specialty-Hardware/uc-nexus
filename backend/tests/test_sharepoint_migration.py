"""The one-time SharePoint inventory migration.

The interesting cases are all about the origin constraint and the all-or-nothing promise: migrated
hardware has no purchase order in Nexus, so every row has to reach `inventory_locations` through the
stock pool, and a batch that fails validation anywhere must leave nothing behind.
"""

import uuid
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.enums import Classification, DestockSource, HardwareItemState
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.stock_item import StockItem
from app.repositories import sharepoint_migration_repository as migration_repo
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository

ACTOR = "Migration Tester"

# The default _entry's identity, so schedule rows built for marking/classification match it exactly.
CAT = "Surface Closer"
CODE = "1431 CPS TB EN"


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
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


def test_project_schedule_products_returns_the_dominant_category_and_classification(db_session):
    """A code split across categories snaps to the category covering the most units, with its
    dominant classification - so the wizard's snapped (category, code) matches what the backend
    marks and classifies against."""
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
    by_code = {(r["project_id"], r["product_code"]): r for r in rows}
    row = by_code[(project.id, "X-1")]
    # Hinge covers 6 units vs Lock's 2, so it wins; SITE covers 5 of the 6 Hinge units, so it wins.
    assert row["hardware_category"] == "Hinge"
    assert row["classification"] == Classification.SITE_HARDWARE


def test_project_schedule_products_is_empty_for_no_projects(db_session):
    assert warehouse_repository.get_project_schedule_products(db_session, []) == []


def test_no_catalog_items_is_a_no_op(db_session):
    assert migration_repo.migrate_catalog_items(db_session, []) == {
        "items_created": 0,
        "items_skipped": 0,
        "attributes_created": 0,
    }
