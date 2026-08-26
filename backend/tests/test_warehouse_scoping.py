"""Warehouse-scoping of the location reads/writes that used to be warehouse-blind.

A location string (aisle/row/bay) names one physical place only WITHIN a warehouse. Before this
work a merge rewrote matching rows in every warehouse, the duplicate finder collapsed the same
string across warehouses into one group, and the audit-history and put-away reads could not be
scoped. These tests pin the warehouse boundary on each of those four paths.

The merge-scoping case is the merge test deferred from PR 1's plan.
"""

import uuid

from app.models.enums import AuditAction, AuditEntityType
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def _second_warehouse(session) -> uuid.UUID:
    """A non-primary second warehouse so a row can share a location string across two buildings."""
    wh = warehouse_admin_repository.create_warehouse(
        session,
        name=f"WH-{uuid.uuid4().hex[:8]}",
        code=f"C{uuid.uuid4().hex[:6]}",
        is_primary=False,
    )
    session.flush()
    return wh.id


def test_merge_rewrites_only_the_given_warehouse(db_session):
    """The deferred merge-scoping test: a merge in warehouse A leaves the identical location in
    warehouse B untouched, across both inventory_locations and stock_items."""
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    project = make_project(db_session)

    il_a = make_il(db_session, project, aisle="ZONE1", row="R7", bay="B9", warehouse_id=wh_a)
    il_b = make_il(db_session, project, aisle="ZONE1", row="R7", bay="B9", warehouse_id=wh_b)
    si_a = make_stock_item(db_session, aisle="ZONE1", row="R7", bay="B9", warehouse_id=wh_a, code="SI-A")
    si_b = make_stock_item(db_session, aisle="ZONE1", row="R7", bay="B9", warehouse_id=wh_b, code="SI-B")
    # A merge target is a location the user chose, so it has to be defined in that warehouse (#632).
    define_location(db_session, wh_a, "ZONE2", "R8", "B0")

    counts = warehouse_repository.merge_locations(
        db_session,
        warehouse_id=wh_a,
        from_aisle="ZONE1",
        from_row="R7",
        from_bay="B9",
        to_aisle="ZONE2",
        to_row="R8",
        to_bay="B0",
        performed_by="admin",
    )
    db_session.flush()
    for row in (il_a, il_b, si_a, si_b):
        db_session.refresh(row)

    assert counts == {"inventory_locations": 1, "stock_items": 1}
    # Warehouse A moved.
    assert (il_a.aisle, il_a.row, il_a.bay) == ("ZONE2", "R8", "B0")
    assert (si_a.aisle, si_a.row, si_a.bay) == ("ZONE2", "R8", "B0")
    # Warehouse B, sharing the identical string, is left exactly where it was.
    assert (il_b.aisle, il_b.row, il_b.bay) == ("ZONE1", "R7", "B9")
    assert (si_b.aisle, si_b.row, si_b.bay) == ("ZONE1", "R7", "B9")


def test_merge_audit_rows_stamp_the_warehouse(db_session):
    """Each MOVE row a merge writes carries the warehouse in its location objects, which is what
    makes the merge findable by a warehouse-scoped history query."""
    wh_a = wh_id(db_session)
    project = make_project(db_session)
    make_il(db_session, project, aisle="MERGE", row="R1", bay="B1", warehouse_id=wh_a)
    define_location(db_session, wh_a, "MERGED", "R2", "B2")

    warehouse_repository.merge_locations(
        db_session,
        warehouse_id=wh_a,
        from_aisle="MERGE",
        from_row="R1",
        from_bay="B1",
        to_aisle="MERGED",
        to_row="R2",
        to_bay="B2",
        performed_by="admin",
    )
    db_session.flush()

    scoped = warehouse_repository.get_location_audit_history(
        db_session, "MERGED", "R2", "B2", limit=50, warehouse_id=wh_a
    )
    assert any(e.action == AuditAction.MOVE and e.detail.get("reason") == "location_merge" for e in scoped)


def test_duplicates_are_grouped_per_warehouse(db_session):
    """The same colliding pair of variants in two warehouses is two groups, not one - merging one
    must never offer to rewrite the other's rows."""
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)

    for i, wh in enumerate((wh_a, wh_b)):
        make_stock_item(db_session, aisle="dupaisle", row="rr", bay="bb", warehouse_id=wh, code=f"D{i}A")
        make_stock_item(db_session, aisle="DUPAISLE", row="rr", bay="bb", warehouse_id=wh, code=f"D{i}B")

    groups = warehouse_repository.get_location_duplicates(db_session)
    ours = [g for g in groups if g["canonical_aisle"] == "DUPAISLE" and g["canonical_row"] == "RR"]

    assert len(ours) == 2
    assert {g["warehouse_id"] for g in ours} == {wh_a, wh_b}
    for g in ours:
        assert len(g["variants"]) == 2


def test_audit_history_warehouse_filter_matches_only_stamped_rows(db_session):
    """A warehouse-scoped query returns only rows stamped with that warehouse; an unscoped query
    still returns everything, including pre-existing rows that carry no warehouse stamp."""
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    project = make_project(db_session)

    il_a = make_il(db_session, project, aisle=None, row=None, bay=None, warehouse_id=wh_a)
    il_b = make_il(db_session, project, aisle=None, row=None, bay=None, warehouse_id=wh_b)
    # The same string is a separate defined location in each building (#632).
    define_location(db_session, wh_a, "HIST", "R1", "B1")
    define_location(db_session, wh_b, "HIST", "R1", "B1")
    warehouse_repository.assign_inventory_location(db_session, il_a.id, "HIST", "R1", "B1", performed_by="a")
    warehouse_repository.assign_inventory_location(db_session, il_b.id, "HIST", "R1", "B1", performed_by="b")

    # A pre-existing-style row: a location object with no warehouseId, the shape old audit rows carry.
    warehouse_repository._log_audit_event(
        db_session,
        project_id=project.id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il_a.id,
        action=AuditAction.PUT_AWAY,
        performed_by="legacy",
        detail={"toLocation": {"aisle": "HIST", "row": "R1", "bay": "B1"}},
    )
    db_session.flush()

    unscoped = warehouse_repository.get_location_audit_history(db_session, "HIST", "R1", "B1", limit=50)
    performers_unscoped = {e.performed_by for e in unscoped}
    # Both warehouses' stamped assigns AND the unstamped legacy row.
    assert {"a", "b", "legacy"} <= performers_unscoped

    scoped_a = warehouse_repository.get_location_audit_history(
        db_session, "HIST", "R1", "B1", limit=50, warehouse_id=wh_a
    )
    performers_a = {e.performed_by for e in scoped_a}
    assert "a" in performers_a
    # Warehouse B's row and the unstamped legacy row both drop out of a scoped query.
    assert "b" not in performers_a
    assert "legacy" not in performers_a


def test_unlocated_inventory_warehouse_filter(db_session):
    """Put-away can scope its queue to one building; unfiltered still spans warehouses."""
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    project = make_project(db_session)

    make_il(db_session, project, aisle=None, row=None, bay=None, warehouse_id=wh_a, code="UNL-A")
    make_il(db_session, project, aisle=None, row=None, bay=None, warehouse_id=wh_b, code="UNL-B")

    a_only = warehouse_repository.get_unlocated_inventory(db_session, None, wh_a)
    codes_a = {r["inventory_location"].product_code for r in a_only}
    assert "UNL-A" in codes_a
    assert "UNL-B" not in codes_a

    both = warehouse_repository.get_unlocated_inventory(db_session)
    codes_both = {r["inventory_location"].product_code for r in both}
    assert {"UNL-A", "UNL-B"} <= codes_both
