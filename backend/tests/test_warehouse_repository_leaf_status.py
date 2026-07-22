"""Tests for warehouse_repository.get_opening_leaf_status - the per-opening door-leaf rollup (#313)."""

import uuid
from datetime import datetime

from app.models.enums import OpeningItemState
from app.models.opening_item import OpeningItem
from app.models.project import Opening, Project
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository


def _make_project(session, description: str = "Test") -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description=description)
    session.add(p)
    session.flush()
    return p


def _make_opening(session, project_id, opening_number: str, leaf_count: int | None) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project_id, opening_number=opening_number, leaf_count=leaf_count)
    session.add(o)
    session.flush()
    return o


def _make_opening_item(session, *, project_id, opening_number: str, leaf: int | None, state: OpeningItemState):
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project_id,
        opening_id=uuid.uuid4(),
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=opening_number,
        leaf=leaf,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=state,
    )
    session.add(oi)
    session.flush()
    return oi


def _statuses(row: dict) -> dict[int, str]:
    return {leaf["leaf"]: leaf["status"] for leaf in row["leaves"]}


def test_pair_reports_per_leaf_status(db_session):
    """A pair with leaf 1 shipped and leaf 2 still in inventory reports both, at their own status."""
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "101", leaf_count=2)
    _make_opening_item(
        db_session, project_id=project.id, opening_number="101", leaf=1, state=OpeningItemState.SHIPPED_OUT
    )
    _make_opening_item(
        db_session, project_id=project.id, opening_number="101", leaf=2, state=OpeningItemState.IN_INVENTORY
    )

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert len(rows) == 1
    row = rows[0]
    assert row["opening_number"] == "101"
    assert row["leaf_count"] == 2
    assert row["project_id"] == project.id
    assert _statuses(row) == {1: "SHIPPED_OUT", 2: "IN_INVENTORY"}


def test_not_yet_assembled_leaf_shows(db_session):
    """A pair whose leaf 2 has no OpeningItem yet still enumerates leaf 2 as NOT_ASSEMBLED."""
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "102", leaf_count=2)
    _make_opening_item(
        db_session, project_id=project.id, opening_number="102", leaf=1, state=OpeningItemState.SHIP_READY
    )

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert len(rows) == 1
    assert _statuses(rows[0]) == {1: "SHIP_READY", 2: "NOT_ASSEMBLED"}


def test_pair_with_no_opening_items_is_all_not_assembled(db_session):
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "103", leaf_count=2)

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert len(rows) == 1
    assert _statuses(rows[0]) == {1: "NOT_ASSEMBLED", 2: "NOT_ASSEMBLED"}


def test_single_leaf_opening_excluded(db_session):
    """leaf_count 1 (single) is just its own row elsewhere - not part of the rollup."""
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "single", leaf_count=1)
    _make_opening_item(
        db_session, project_id=project.id, opening_number="single", leaf=1, state=OpeningItemState.IN_INVENTORY
    )

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert rows == []


def test_legacy_null_leaf_count_excluded(db_session):
    """A legacy opening with a NULL leaf_count is not a known pair, so it drops out."""
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "legacy", leaf_count=None)

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert rows == []


def test_furthest_along_state_wins_for_duplicate_leaf(db_session):
    """If a leaf has more than one OpeningItem, the most-advanced state is reported."""
    project = _make_project(db_session)
    _make_opening(db_session, project.id, "104", leaf_count=2)
    _make_opening_item(
        db_session, project_id=project.id, opening_number="104", leaf=1, state=OpeningItemState.IN_INVENTORY
    )
    _make_opening_item(
        db_session, project_id=project.id, opening_number="104", leaf=1, state=OpeningItemState.SHIPPED_OUT
    )

    rows = warehouse_repository.get_opening_leaf_status(db_session, project.id)
    assert _statuses(rows[0])[1] == "SHIPPED_OUT"


def test_scoped_by_project(db_session):
    """Passing a project_id must not bleed openings from another project."""
    p1 = _make_project(db_session)
    p2 = _make_project(db_session)
    _make_opening(db_session, p1.id, "101", leaf_count=2)
    _make_opening(db_session, p2.id, "999", leaf_count=2)

    rows = warehouse_repository.get_opening_leaf_status(db_session, p1.id)
    assert [r["opening_number"] for r in rows] == ["101"]


def test_global_spans_projects_and_disambiguates_colliding_openings(db_session):
    """No project_id -> all projects; a shared opening number stays distinct via project identity."""
    p1 = _make_project(db_session, description="Alpha")
    p2 = _make_project(db_session, description="Bravo")
    _make_opening(db_session, p1.id, "101", leaf_count=2)
    _make_opening(db_session, p2.id, "101", leaf_count=2)
    _make_opening_item(db_session, project_id=p1.id, opening_number="101", leaf=1, state=OpeningItemState.SHIPPED_OUT)

    rows = warehouse_repository.get_opening_leaf_status(db_session, None)
    by_project = {r["project_id"]: r for r in rows}
    assert set(by_project) == {p1.id, p2.id}
    assert _statuses(by_project[p1.id])[1] == "SHIPPED_OUT"
    assert _statuses(by_project[p2.id])[1] == "NOT_ASSEMBLED"
    # Sorted by project name then opening number: Alpha before Bravo.
    assert [r["project_name"] for r in rows] == ["Alpha", "Bravo"]
