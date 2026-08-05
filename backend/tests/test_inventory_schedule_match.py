"""The schedule-match flag on project inventory.

Inventory that entered outside a hardware-schedule import - the SharePoint migration, a stock
allocation, a reclassify - can carry a category or code spelled differently from the schedule. Both
pull-request builders start from the schedule and match on the exact (category, code) pair, so those
units are unclaimable until someone reconciles the two. This flag is what surfaces that.
"""

import uuid
from datetime import datetime

from app.models.enums import HardwareItemState
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


def _add_schedule_item(session, project, *, category, code):
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
            item_quantity=1,
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


def _hierarchy(project_id=None):
    """Call the real resolver the way the schema does."""
    from app.schemas.warehouse import WarehouseQueries

    return WarehouseQueries().inventory_hierarchy(None, project_id=project_id)


def test_resolver_flags_a_pair_absent_from_the_schedule(db_session, monkeypatch):
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")
    _add_inventory(db_session, project, category="Washroom", code="GRAB-BAR-42")
    db_session.commit()

    nodes = _hierarchy(str(project.id))
    flat = {(n.hardware_category, pc.product_code): pc.matches_schedule for n in nodes for pc in n.product_codes}
    assert flat[("Washroom", "GRAB-BAR-42")] is False


def test_resolver_does_not_flag_a_pair_the_schedule_names(db_session):
    project = _make_project(db_session)
    _add_schedule_item(db_session, project, category="Hinge", code="BB1279")
    _add_inventory(db_session, project, category="Hinge", code="BB1279")
    db_session.commit()

    nodes = _hierarchy(str(project.id))
    flat = {(n.hardware_category, pc.product_code): pc.matches_schedule for n in nodes for pc in n.product_codes}
    assert flat[("Hinge", "BB1279")] is True


def test_unscoped_hierarchy_never_flags(db_session):
    """No project, no single schedule to compare against - so the answer is unknown, not False."""
    project = _make_project(db_session)
    _add_inventory(db_session, project, category="Washroom", code="GRAB-BAR-42")
    db_session.commit()

    nodes = _hierarchy(None)
    assert nodes
    assert all(pc.matches_schedule for n in nodes for pc in n.product_codes)


def test_by_vendor_hierarchy_builds_and_never_flags(db_session):
    """It also regressions the omitted-required-argument crash: this raised TypeError on every call."""
    from app.schemas.warehouse import WarehouseQueries

    project = _make_project(db_session)
    _add_inventory(db_session, project, category="Washroom", code="GRAB-BAR-42")
    db_session.commit()

    nodes = WarehouseQueries().inventory_by_vendor(None, project_id=str(project.id))
    assert nodes
    for n in nodes:
        for pc in n.product_codes:
            assert pc.matches_schedule is True
            assert pc.total_available_quantity == 0
