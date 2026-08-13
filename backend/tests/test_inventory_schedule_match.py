"""The schedule-match flag on project inventory.

Inventory that entered outside a hardware-schedule import - the SharePoint migration, a stock
allocation, a reclassify - can carry a category or code spelled differently from the schedule. Both
pull-request builders start from the schedule and match on the exact (category, code) pair, so those
units are unclaimable until someone reconciles the two. This flag is what surfaces that.
"""

import uuid
from datetime import datetime

from app.models.enums import Classification, HardwareItemState
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.stock_item import StockItem
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _add_schedule_item(session, project, *, category, code, classification=None, quantity=1):
    opening = Opening(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_number=f"OP-{uuid.uuid4().hex[:6]}",
    )
    session.add(opening)
    session.flush()
    session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category=category,
            product_code=code,
            item_quantity=quantity,
            classification=classification,
            state=HardwareItemState.AVAILABLE,
        )
    )
    session.flush()


def _add_inventory(session, project, *, category, code, quantity=5):
    wh = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=wh,
        hardware_category=category,
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=si.id,
            warehouse_id=wh,
            hardware_category=category,
            product_code=code,
            quantity=quantity,
            deficient_quantity=0,
            received_at=datetime.utcnow(),
        )
    )
    session.flush()


def test_scheduled_pairs_returns_the_exact_pairs(db_session):
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Surface Closer", code="1431 CPS TB EN")
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")

    pairs = warehouse_repository.get_scheduled_pairs(db_session, project.id)

    assert ("Surface Closer", "1431 CPS TB EN") in pairs
    assert ("Hinge", "BB1279") in pairs


def test_a_code_absent_from_the_schedule_is_not_matched(db_session):
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Surface Closer", code="1431 CPS TB EN")
    pairs = warehouse_repository.get_scheduled_pairs(db_session, project.id)

    # The SharePoint part-number spelling of the same physical closer.
    assert ("Surface Closer", "TB-1431-CPS-EN") not in pairs


def test_matching_is_on_the_pair_not_the_code_alone(db_session):
    """The same code under a different category is a different claim, and must not match."""
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Surface Closer", code="1431 CPS TB EN")
    pairs = warehouse_repository.get_scheduled_pairs(db_session, project.id)

    assert ("Closer", "1431 CPS TB EN") not in pairs


def test_pairs_are_scoped_to_one_project(db_session):
    a, b = _make_project(db_session), _make_project(db_session)
    _add_schedule_item(db_session, a, category="Hinge", code="BB1279")

    assert ("Hinge", "BB1279") not in warehouse_repository.get_scheduled_pairs(db_session, b.id)


def test_a_project_with_no_schedule_matches_nothing(db_session):
    project = _make_project(db_session)
    _add_inventory(db_session, project, category="Hinge", code="BB1279")

    assert warehouse_repository.get_scheduled_pairs(db_session, project.id) == set()


# --- the resolver wiring, which is the behaviour the flag actually exists for -------------------


def _borrow(monkeypatch, db_session):
    """Hand the resolver the test's transaction-bound session instead of a fresh SessionLocal.

    Without this the resolver opens its own connection and cannot see the fixture's uncommitted
    rows, so every assertion reads an empty table. Same pattern as test_warehouse_dashboard.
    """
    from app.schemas import warehouse as warehouse_schema_module

    class _BorrowedSession:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(warehouse_schema_module, "SessionLocal", _BorrowedSession)


def _flat(rows):
    return {
        (r.inventory_location.hardware_category, r.inventory_location.product_code): r.matches_schedule for r in rows
    }


def test_resolver_flags_a_pair_absent_from_the_schedule(db_session, monkeypatch):
    from app.schemas.warehouse import WarehouseQueries

    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")
    _add_inventory(db_session, project, category="Washroom", code="GRAB-BAR-42")
    _borrow(monkeypatch, db_session)

    flat = _flat(WarehouseQueries().inventory_rows(None, project_id=str(project.id)))
    assert flat[("Washroom", "GRAB-BAR-42")] is False


def test_resolver_does_not_flag_a_pair_the_schedule_names(db_session, monkeypatch):
    from app.schemas.warehouse import WarehouseQueries

    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")
    _add_inventory(db_session, project, category="Hinge", code="BB1279")
    _borrow(monkeypatch, db_session)

    flat = _flat(WarehouseQueries().inventory_rows(None, project_id=str(project.id)))
    assert flat[("Hinge", "BB1279")] is True


def test_unscoped_rows_never_flag(db_session, monkeypatch):
    """No project, no single schedule to compare against - so the answer is unknown, not False."""
    from app.schemas.warehouse import WarehouseQueries

    project = _make_project(db_session)
    _add_inventory(db_session, project, category="Washroom", code="GRAB-BAR-42")
    _borrow(monkeypatch, db_session)

    rows = WarehouseQueries().inventory_rows(None, project_id=None)
    assert rows
    assert all(r.matches_schedule for r in rows)


def test_non_schedule_type_codes_are_never_flagged(db_session, monkeypatch):
    """Frames, specialties and consumables (#454) are absent from every schedule by design.

    Their type code rides in hardware_category, so measuring them against a hardware schedule would
    flag all of them forever - which is what makes a warning worth ignoring.
    """
    from app.repositories import custom_items_repository
    from app.schemas.warehouse import WarehouseQueries

    item_type = custom_items_repository.get_item_types(db_session, active_only=True)[0]
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")
    _add_inventory(db_session, project, category=item_type.code, code="FR-101")
    _add_inventory(db_session, project, category="Washroom", code="GRAB-42")
    _borrow(monkeypatch, db_session)

    flat = _flat(WarehouseQueries().inventory_rows(None, project_id=str(project.id)))
    assert flat[(item_type.code, "FR-101")] is True
    # An ordinary category still off the schedule is still flagged - the rule narrowed, not vanished.
    assert flat[("Washroom", "GRAB-42")] is False


# --- the per-product dominant classification the extras lane reads (#610) -----------------------


def test_scheduled_classifications_returns_the_dominant_value_per_product(db_session):
    project = _make_project(db_session)
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SITE_HARDWARE
    )
    _add_schedule_item(db_session, project, category="Lock", code="L9080", classification=Classification.SHOP_HARDWARE)

    result = warehouse_repository.get_scheduled_classifications(db_session, project.id)

    assert result[("Hinge", "BB1279")] == Classification.SITE_HARDWARE
    assert result[("Lock", "L9080")] == Classification.SHOP_HARDWARE


def test_the_majority_of_units_wins_not_the_number_of_rows(db_session):
    """Two rows disagreeing on one product resolve by unit count, the same rule the catalog uses."""
    project = _make_project(db_session)
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SITE_HARDWARE, quantity=2
    )
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SHOP_HARDWARE, quantity=5
    )

    result = warehouse_repository.get_scheduled_classifications(db_session, project.id)

    assert result[("Hinge", "BB1279")] == Classification.SHOP_HARDWARE


def test_an_unclassified_majority_answers_none(db_session):
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279", classification=None, quantity=5)
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SITE_HARDWARE, quantity=2
    )

    result = warehouse_repository.get_scheduled_classifications(db_session, project.id)

    assert result[("Hinge", "BB1279")] is None


def test_a_product_absent_from_the_schedule_is_absent_from_the_map(db_session):
    project = _make_project(db_session)
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SITE_HARDWARE
    )

    result = warehouse_repository.get_scheduled_classifications(db_session, project.id)

    assert ("Washroom", "GRAB-BAR-42") not in result


def test_classifications_are_scoped_to_one_project(db_session):
    a, b = _make_project(db_session), _make_project(db_session)
    _add_schedule_item(db_session, a, category="Hinge", code="BB1279", classification=Classification.SITE_HARDWARE)

    assert warehouse_repository.get_scheduled_classifications(db_session, b.id) == {}


def test_availability_resolver_carries_the_classification(db_session, monkeypatch):
    """The end-to-end wiring the extras lane depends on: a stocked product shows its schedule chip."""
    from app.schemas.warehouse import WarehouseQueries

    project = _make_project(db_session)
    _add_schedule_item(
        db_session, project, category="Hinge", code="BB1279", classification=Classification.SHOP_HARDWARE
    )
    _add_inventory(db_session, project, category="Hinge", code="BB1279")
    _borrow(monkeypatch, db_session)

    rows = WarehouseQueries().project_inventory_availability(None, project_id=str(project.id))
    by_combo = {(r.hardware_category, r.product_code): r.classification for r in rows}
    assert by_combo[("Hinge", "BB1279")] == Classification.SHOP_HARDWARE
