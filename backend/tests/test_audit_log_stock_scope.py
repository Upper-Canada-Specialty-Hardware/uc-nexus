"""Company-scoped audit reads keep stock rows (#1045).

A stock event is written with no project, so scoping by project company alone dropped every one of
them and the stock pool's history was always empty. Stock rows now scope through the stock item's
warehouse company.
"""

import uuid

from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.models.warehouse import Warehouse
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_project, make_stock_item


def _warehouse(session, company: str) -> Warehouse:
    wh = Warehouse(id=uuid.uuid4(), company=company, name=f"{company} wh", code=uuid.uuid4().hex[:8])
    session.add(wh)
    session.flush()
    return wh


def _log(session, *, entity_type, entity_id, project_id=None, detail=None) -> InventoryAuditLog:
    row = InventoryAuditLog(
        id=uuid.uuid4(),
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=AuditAction.MOVE,
        detail=detail,
        performed_by="tester",
    )
    session.add(row)
    session.flush()
    return row


def test_scoped_caller_sees_own_company_stock_history(db_session):
    stock = make_stock_item(db_session, warehouse_id=_warehouse(db_session, "TUBC").id)
    row = _log(db_session, entity_type=AuditEntityType.STOCK_ITEM, entity_id=stock.id)

    entries = warehouse_repository.get_audit_log(db_session, entity_id=stock.id, company="TUBC")

    assert [e.id for e in entries] == [row.id]


def test_scoped_caller_does_not_see_another_company_stock_history(db_session):
    stock = make_stock_item(db_session, warehouse_id=_warehouse(db_session, "TUCSH").id)
    _log(db_session, entity_type=AuditEntityType.STOCK_ITEM, entity_id=stock.id)

    assert warehouse_repository.get_audit_log(db_session, entity_id=stock.id, company="TUBC") == []


def test_project_rows_still_scope_by_project_company(db_session):
    project = make_project(db_session)  # TUBC
    entity = uuid.uuid4()
    row = _log(db_session, entity_type=AuditEntityType.INVENTORY_LOCATION, entity_id=entity, project_id=project.id)

    assert [e.id for e in warehouse_repository.get_audit_log(db_session, entity_id=entity, company="TUBC")] == [row.id]
    assert warehouse_repository.get_audit_log(db_session, entity_id=entity, company="TUCSH") == []


def test_location_history_keeps_own_company_stock_moves(db_session):
    aisle = f"Z{uuid.uuid4().hex[:6]}"
    mine = make_stock_item(db_session, warehouse_id=_warehouse(db_session, "TUBC").id)
    theirs = make_stock_item(db_session, warehouse_id=_warehouse(db_session, "TUCSH").id)
    detail = {"toLocation": {"aisle": aisle, "row": "1", "bay": "1"}}
    kept = _log(db_session, entity_type=AuditEntityType.STOCK_ITEM, entity_id=mine.id, detail=detail)
    _log(db_session, entity_type=AuditEntityType.STOCK_ITEM, entity_id=theirs.id, detail=detail)

    entries = warehouse_repository.get_location_audit_history(db_session, aisle, company="TUBC")

    assert [e.id for e in entries] == [kept.id]
