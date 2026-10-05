"""A stock fold or an inventory split keeps its history on every row it touched (#1574).

A move, put-away, unlocate or merge onto a shelf that already holds the row's key folds the units into
that row and usually deletes the emptied one. The audit entry went on the deleted row alone, and the
company scope kept a project-less stock entry only while its row existed - so the fold, and the deleted
row's whole past, vanished from every scoped view while the surviving row never showed the units it gained.
"""

import uuid

from app.models.enums import AuditAction
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def _aisle() -> str:
    return f"AUD{uuid.uuid4().hex[:6].upper()}"


def _company(session) -> str:
    return session.get(Warehouse, wh_id(session)).company


def test_a_move_that_folds_leaves_history_on_the_surviving_row(db_session):
    first, second = _aisle(), _aisle()
    define_location(db_session, None, first, "1", "1")
    define_location(db_session, None, second, "1", "1")
    moving = make_stock_item(db_session, quantity=3, code="HG-FOLD", aisle=first, row="1", bay="1")
    staying = make_stock_item(db_session, quantity=4, code="HG-FOLD", aisle=second, row="1", bay="1")
    moving_id = moving.id

    stock_repository.move_stock_location(
        db_session, stock_item_id=moving_id, new_aisle=second, new_row="1", new_bay="1", performed_by="wh"
    )
    db_session.flush()

    assert db_session.get(StockItem, moving_id) is None, "the emptied row folded away"
    company = _company(db_session)
    on_target = warehouse_repository.get_audit_log(db_session, entity_id=staying.id, company=company)
    assert [e.action for e in on_target] == [AuditAction.MOVE]
    assert on_target[0].detail["foldedFromStockItemId"] == str(moving_id)
    assert on_target[0].detail["quantity"] == 3


def test_a_folded_away_rows_history_stays_visible_to_its_company(db_session):
    first, second = _aisle(), _aisle()
    define_location(db_session, None, first, "1", "1")
    define_location(db_session, None, second, "1", "1")
    unlocated = make_stock_item(db_session, quantity=2, code="HG-PAST")
    make_stock_item(db_session, quantity=5, code="HG-PAST", aisle=second, row="1", bay="1")
    row_id = unlocated.id

    # Its past: put away on one shelf, then moved onto a shelf already holding its key, where it folds.
    stock_repository.assign_stock_item_location(
        db_session, stock_item_id=row_id, aisle=first, row="1", bay="1", performed_by="wh"
    )
    stock_repository.move_stock_location(
        db_session, stock_item_id=row_id, new_aisle=second, new_row="1", new_bay="1", performed_by="wh"
    )
    db_session.flush()

    assert db_session.get(StockItem, row_id) is None
    history = warehouse_repository.get_audit_log(db_session, entity_id=row_id, company=_company(db_session))
    assert {e.action for e in history} == {AuditAction.PUT_AWAY, AuditAction.MOVE}
    assert warehouse_repository.get_audit_log(db_session, entity_id=row_id, company="NOT-A-COMPANY") == []


def test_a_split_is_audited_on_both_rows(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle=None, row=None, bay=None)

    kept, remainder = warehouse_repository.split_inventory_location(db_session, il.id, 4, performed_by="wh")
    db_session.flush()

    on_source = warehouse_repository.get_audit_log(db_session, entity_id=kept.id)
    assert [(e.action, e.detail["oldQuantity"], e.detail["newQuantity"]) for e in on_source] == [
        (AuditAction.ADJUSTMENT, 10, 6)
    ]
    assert on_source[0].detail["splitInto"] == str(remainder.id)
    on_remainder = warehouse_repository.get_audit_log(db_session, entity_id=remainder.id)
    assert [e.detail["reason"] for e in on_remainder] == ["split"]
