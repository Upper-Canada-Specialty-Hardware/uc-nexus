"""Project-inventory floors and origin cloning (warehouse/inventory.py).

Two remediation fixes live here: adjust_inventory_quantity now refuses to drop a row below its own
deficient_quantity (the spot-check path only checked for negative before, so it tripped the
deficient<=quantity CHECK), and override-increase now clones shipment_return_item_id onto the rows it
creates, so a return-origin row can absorb found units without tripping the has-origin CHECK.
"""

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction
from app.models.inventory import InventoryLocation
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_il, make_project, make_return_item, wh_id

# --- adjust_inventory_quantity floor ------------------------------------------------------------


def test_adjust_below_deficient_floor_is_refused(db_session):
    """qty 10 / deficient 4, adjust -7 would leave qty 3 < deficient 4 -> CHECK -> 500."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    with pytest.raises(ValidationError):
        warehouse_repository.adjust_inventory_quantity(db_session, il.id, -7, "spot check", performed_by="warehouse")


def test_adjust_down_to_the_deficient_floor_is_allowed(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    warehouse_repository.adjust_inventory_quantity(db_session, il.id, -6, "spot check", performed_by="warehouse")

    assert il.quantity == 4
    assert il.deficient_quantity == 4


def test_adjust_into_negative_total_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.adjust_inventory_quantity(db_session, il.id, -6, "spot check", performed_by="warehouse")


def test_adjust_upward_is_allowed(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=5, deficient=2)

    warehouse_repository.adjust_inventory_quantity(db_session, il.id, 3, "found more", performed_by="warehouse")

    assert il.quantity == 8


def test_adjust_requires_a_reason(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.adjust_inventory_quantity(db_session, il.id, 1, "", performed_by="warehouse")


# --- spot check audit action --------------------------------------------------------------------


def _audit_rows(session, entity_id):
    return list(session.scalars(select(InventoryAuditLog).where(InventoryAuditLog.entity_id == entity_id)).all())


def test_spot_check_writes_a_spot_check_action_with_the_counted_pair(db_session):
    """spot_check=True files the audit row under SPOT_CHECK (the enum value existed unused) and its
    detail carries systemQuantity/physicalQuantity so the history render can show counted-vs-system."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    warehouse_repository.adjust_inventory_quantity(
        db_session, il.id, -3, "spot check", performed_by="counter", spot_check=True
    )

    assert il.quantity == 7
    rows = _audit_rows(db_session, il.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == AuditAction.SPOT_CHECK
    assert row.detail["systemQuantity"] == 10
    assert row.detail["physicalQuantity"] == 7
    assert row.detail["adjustment"] == -3


def test_adjust_without_spot_check_stays_an_adjustment(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    warehouse_repository.adjust_inventory_quantity(db_session, il.id, -3, "recount", performed_by="counter")

    rows = _audit_rows(db_session, il.id)
    assert len(rows) == 1
    assert rows[0].action == AuditAction.ADJUSTMENT
    assert "systemQuantity" not in (rows[0].detail or {})


# --- override-increase on a return-origin row ---------------------------------------------------


def _rows(session, project_id):
    return list(session.scalars(select(InventoryLocation).where(InventoryLocation.project_id == project_id)).all())


def test_override_increase_new_location_clones_the_return_origin(db_session):
    """A return-origin row's only origin FK is shipment_return_item_id; the new row must inherit it
    or the has-origin CHECK rejects the insert with a raw 500."""
    project = make_project(db_session)
    ret = make_return_item(db_session, project)
    il = make_il(db_session, project, quantity=5, shipment_return_item_id=ret.id, aisle="A", row="1", bay="1")

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=8,
        reason="found three more",
        destinations=[{"aisle": "B", "row": "2", "bay": "2", "quantity": 3}],
        performed_by="warehouse",
    )

    rows = _rows(db_session, project.id)
    assert len(rows) == 2
    new_row = next(r for r in rows if r.id != il.id)
    assert new_row.quantity == 3
    assert new_row.shipment_return_item_id == ret.id
    assert new_row.po_line_item_id is None
    assert new_row.receive_line_item_id is None
    assert new_row.stock_item_id is None


def test_override_increase_same_location_bumps_the_return_origin_row(db_session):
    project = make_project(db_session)
    ret = make_return_item(db_session, project)
    il = make_il(db_session, project, quantity=5, shipment_return_item_id=ret.id, aisle="A", row="1", bay="1")

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=8,
        reason="recount up",
        destinations=[{"aisle": "A", "row": "1", "bay": "1", "quantity": 3}],
        performed_by="warehouse",
    )

    assert il.quantity == 8
    assert len(_rows(db_session, project.id)) == 1  # no new row
    assert wh_id(db_session) == il.warehouse_id
