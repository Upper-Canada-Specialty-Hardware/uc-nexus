"""Splitting an unlocated inventory row at put-away (#501).

Put-away moved after the warehouse manager's approval, so a receive books ONE row per PO line and
the warehouse decides afterwards where the units go. Ten hinges rarely land in one bin, and a row
carries exactly one aisle/row/bay - so the queue needs a way to break a row in two.

What the split must not do is launder provenance. The origin FKs and `received_at` are what tie the
units back to the receipt that booked them and what FIFO orders picks by; a split is a change of
shelf, not of history.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository


def _row(session, *, quantity=10, deficient=0):
    project = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Split", company="TUBC")
    session.add(project)
    session.flush()
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    received_at = datetime.utcnow() - timedelta(days=3)
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        stock_item_id=stock.id,
        warehouse_id=warehouse_id,
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=quantity,
        deficient_quantity=deficient,
        aisle=None,
        row=None,
        bay=None,
        received_at=received_at,
    )
    session.add(il)
    session.flush()
    return project, il


def test_a_split_conserves_quantity_and_copies_the_origin(db_session):
    project, il = _row(db_session, quantity=10)
    original_received_at = il.received_at

    kept, moved = warehouse_repository.split_inventory_location(db_session, il.id, 4, performed_by="picker")
    db_session.flush()

    assert kept.id == il.id
    assert kept.quantity == 6
    assert moved.quantity == 4
    assert kept.quantity + moved.quantity == 10

    # A split is a change of shelf, not of history: FIFO and the audit trail both key off these.
    assert moved.stock_item_id == il.stock_item_id
    assert moved.po_line_item_id == il.po_line_item_id
    assert moved.receive_line_item_id == il.receive_line_item_id
    assert moved.warehouse_id == il.warehouse_id
    assert moved.project_id == project.id
    assert moved.received_at == original_received_at

    # The new row is what the caller then assigns, so it starts unlocated.
    assert moved.aisle is None and moved.row is None and moved.bay is None


def test_the_split_writes_a_put_away_audit_row_naming_the_caller(db_session):
    project, il = _row(db_session, quantity=10)

    _kept, moved = warehouse_repository.split_inventory_location(db_session, il.id, 3, performed_by="Wendy Warehouse")
    db_session.flush()

    logs = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.project_id == project.id,
                InventoryAuditLog.entity_id == moved.id,
            )
        ).all()
    )
    assert len(logs) == 1
    assert logs[0].action == AuditAction.PUT_AWAY
    assert logs[0].performed_by == "Wendy Warehouse"
    assert logs[0].detail["splitFrom"] == str(il.id)
    assert logs[0].detail["quantity"] == 3


def test_deficient_units_stay_with_the_original_row(db_session):
    """They are not on a shelf - they are a claim against the vendor. Moving a fraction of them to a
    bin nobody put them in would be a lie."""
    _project, il = _row(db_session, quantity=10, deficient=2)

    kept, moved = warehouse_repository.split_inventory_location(db_session, il.id, 4, performed_by="picker")
    db_session.flush()

    assert kept.deficient_quantity == 2
    assert moved.deficient_quantity == 0


@pytest.mark.parametrize("bad", [0, -1, 10, 11])
def test_a_split_that_would_empty_or_overdraw_the_row_is_refused(db_session, bad):
    _project, il = _row(db_session, quantity=10)

    with pytest.raises(ValidationError):
        warehouse_repository.split_inventory_location(db_session, il.id, bad, performed_by="picker")


def test_splitting_twice_leaves_three_rows_that_still_sum(db_session):
    """The normal case is more than two bins: 5 here, 3 there, 2 left."""
    _project, il = _row(db_session, quantity=10)

    _kept, first = warehouse_repository.split_inventory_location(db_session, il.id, 5, performed_by="picker")
    _kept2, second = warehouse_repository.split_inventory_location(db_session, il.id, 3, performed_by="picker")
    db_session.flush()

    assert il.quantity == 2
    assert first.quantity == 5
    assert second.quantity == 3
    assert il.quantity + first.quantity + second.quantity == 10
