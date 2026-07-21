"""Tests for warehouse_repository.override_inventory_quantity (issue #138)."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_stock_item(session) -> StockItem:
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=10,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    return si


def _make_il(session, project_id, stock_item_id, *, quantity, deficient=0, aisle="A", row="1", bay="1"):
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock_item_id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=quantity,
        deficient_quantity=deficient,
        aisle=aisle,
        row=row,
        bay=bay,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _rows(session, project_id):
    return list(session.scalars(select(InventoryLocation).where(InventoryLocation.project_id == project_id)).all())


def test_override_decrease_shrinks_row(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=10)

    warehouse_repository.override_inventory_quantity(
        db_session, inv_id=il.id, new_quantity=4, reason="recount", destinations=[], performed_by="tester"
    )

    assert il.quantity == 4
    assert len(_rows(db_session, project.id)) == 1


def test_override_decrease_below_deficient_rejected(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=10, deficient=5)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session, inv_id=il.id, new_quantity=3, reason="recount", destinations=[], performed_by="tester"
        )


def test_override_increase_same_location_bumps_row(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5, aisle="A", row="1", bay="1")

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=8,
        reason="found extra",
        destinations=[{"aisle": "A", "row": "1", "bay": "1", "quantity": 3}],
        performed_by="tester",
    )

    assert il.quantity == 8
    assert len(_rows(db_session, project.id)) == 1  # no new row created


def test_override_increase_new_location_creates_row(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5, aisle="A", row="1", bay="1")

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=8,
        reason="found extra in another row",
        destinations=[{"aisle": "B", "row": "2", "bay": "2", "quantity": 3}],
        performed_by="tester",
    )

    rows = _rows(db_session, project.id)
    assert il.quantity == 5  # source row unchanged; added units landed elsewhere
    assert len(rows) == 2
    new_row = next(r for r in rows if r.id != il.id)
    assert (new_row.aisle, new_row.row, new_row.bay) == ("B", "2", "2")
    assert new_row.quantity == 3
    assert new_row.stock_item_id == origin.id  # inherits the source row's origin


def test_override_increase_requires_destinations(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session, inv_id=il.id, new_quantity=8, reason="extra", destinations=[], performed_by="tester"
        )


def test_override_increase_destinations_must_sum_to_delta(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session,
            inv_id=il.id,
            new_quantity=8,  # delta = 3
            reason="extra",
            destinations=[{"aisle": "B", "row": "2", "bay": "2", "quantity": 2}],  # sums to 2, not 3
            performed_by="tester",
        )


def test_override_requires_reason(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session, inv_id=il.id, new_quantity=3, reason="", destinations=[], performed_by="tester"
        )


def test_override_no_change_rejected(db_session):
    project = _make_project(db_session)
    origin = _make_stock_item(db_session)
    il = _make_il(db_session, project.id, origin.id, quantity=5)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session, inv_id=il.id, new_quantity=5, reason="no change", destinations=[], performed_by="tester"
        )
