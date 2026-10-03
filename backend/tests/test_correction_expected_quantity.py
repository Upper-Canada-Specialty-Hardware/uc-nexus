"""Correction writes refuse a row that moved since the dialog showed it (#1315, #1316, #1318).

The spot check, pool adjust and override dialogs all build their write from the count they
displayed. Each now sends that count as `expected_quantity`; under the row lock the repository
compares it with the row's current count and refuses with a ConflictError naming both, instead of
applying a delta to a moved count or writing back units a concurrent write took off.
"""

import pytest
from sqlalchemy import select, update

from app.errors import ConflictError
from app.models.audit_log import InventoryAuditLog
from app.models.inventory import InventoryLocation
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories.warehouse.inventory import check_expected_quantity

from .inventory_fixtures import make_il, make_project, make_stock_item

# --- the shared check (no database) ------------------------------------------------------------


def test_check_passes_when_the_count_is_unchanged():
    check_expected_quantity(10, 10)


def test_check_is_skipped_for_an_older_client():
    check_expected_quantity(10, None)


def test_check_refuses_a_moved_count_naming_both_values():
    with pytest.raises(ConflictError) as exc:
        check_expected_quantity(6, 10)
    assert "from 10 to 6" in str(exc.value)
    assert exc.value.field == "expected_quantity"


# --- spot check (#1315) ------------------------------------------------------------------------


def _move_row_behind_the_session(session, model, row_id, quantity):
    """A concurrent write: the row changes in the database, the session's copy does not."""
    session.execute(update(model).where(model.id == row_id).values(quantity=quantity))


def test_spot_check_on_a_row_that_moved_is_refused(db_session):
    """Shown 10, a pick takes it to 6, the counter counts 7: the -3 delta must not land on 6."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _move_row_behind_the_session(db_session, InventoryLocation, il.id, 6)

    with pytest.raises(ConflictError):
        warehouse_repository.adjust_inventory_quantity(
            db_session, il.id, -3, "spot check", performed_by="warehouse", spot_check=True, expected_quantity=10
        )

    db_session.refresh(il)
    assert il.quantity == 6


def test_spot_check_records_the_count_the_counter_entered(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    warehouse_repository.adjust_inventory_quantity(
        db_session, il.id, -3, "spot check", performed_by="warehouse", spot_check=True, expected_quantity=10
    )

    assert il.quantity == 7
    audit = db_session.scalars(select(InventoryAuditLog).where(InventoryAuditLog.entity_id == il.id)).one()
    assert audit.detail["systemQuantity"] == 10
    assert audit.detail["physicalQuantity"] == 7


# --- override (#1318) --------------------------------------------------------------------------


def test_override_on_a_row_that_moved_is_refused(db_session):
    """Shown 10, a pick takes it to 6, the user overrides to 8 meaning a decrease: refused as changed,
    not as an increase missing destinations."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _move_row_behind_the_session(db_session, InventoryLocation, il.id, 6)

    with pytest.raises(ConflictError) as exc:
        warehouse_repository.override_inventory_quantity(
            db_session,
            inv_id=il.id,
            new_quantity=8,
            reason="recount",
            destinations=[],
            performed_by="warehouse",
            expected_quantity=10,
        )
    assert "from 10 to 6" in str(exc.value)


def test_override_with_the_shown_count_still_applies(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=8,
        reason="recount",
        destinations=[],
        performed_by="warehouse",
        expected_quantity=10,
    )

    assert il.quantity == 8


# --- pool adjust (#1316) -----------------------------------------------------------------------


def test_pool_adjust_on_a_row_that_moved_is_refused(db_session):
    """Shown 10, 3 allocated away (7), the user takes 2 off: writing 8 would bring a unit back."""
    si = make_stock_item(db_session, quantity=10)
    _move_row_behind_the_session(db_session, StockItem, si.id, 7)

    with pytest.raises(ConflictError):
        stock_repository.adjust_stock_quantity(
            db_session,
            stock_item_id=si.id,
            new_quantity=8,
            reason_text="recount",
            performed_by="warehouse",
            expected_quantity=10,
        )

    db_session.refresh(si)
    assert si.quantity == 7


def test_pool_adjust_with_the_shown_count_still_applies(db_session):
    si = make_stock_item(db_session, quantity=10)

    stock_repository.adjust_stock_quantity(
        db_session,
        stock_item_id=si.id,
        new_quantity=8,
        reason_text="recount",
        performed_by="warehouse",
        expected_quantity=10,
    )

    assert si.quantity == 8
