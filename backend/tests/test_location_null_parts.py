"""An aisle-only shelf (row and bay null) is a place of its own (#1251).

The locations panel asks for the selected utilization entry's contents and history with its row and
bay as given - null for an aisle-only entry. Null used to mean "any", so the panel listed every item in
the aisle and its select-all actions reached other shelves. Null now matches NULL; only an omitted
part still matches anything.
"""

import uuid

from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_il, make_project, make_stock_item


def _aisle() -> str:
    return f"N{uuid.uuid4().hex[:6].upper()}"


def test_null_row_and_bay_list_only_the_aisle_only_rows(db_session):
    aisle = _aisle()
    project = make_project(db_session)
    bare_il = make_il(db_session, project, quantity=2, aisle=aisle, row=None, bay=None)
    make_il(db_session, project, quantity=3, aisle=aisle, row="1", bay="1")
    bare_si = make_stock_item(db_session, quantity=4, aisle=aisle, row=None, bay=None)
    make_stock_item(db_session, quantity=5, code="HG-555", aisle=aisle, row="2", bay="2")

    data = warehouse_repository.get_location_contents(db_session, aisle, None, None)

    assert [i["inventory_location"].id for i in data["inventory_items"]] == [bare_il.id]
    assert [s.id for s in data["stock_items"]] == [bare_si.id]


def test_an_omitted_row_and_bay_still_list_the_whole_aisle(db_session):
    aisle = _aisle()
    project = make_project(db_session)
    make_il(db_session, project, quantity=2, aisle=aisle, row=None, bay=None)
    make_il(db_session, project, quantity=3, aisle=aisle, row="1", bay="1")

    data = warehouse_repository.get_location_contents(db_session, aisle)

    assert len(data["inventory_items"]) == 2


def _log(session, location: dict) -> InventoryAuditLog:
    entry = InventoryAuditLog(
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=uuid.uuid4(),
        action=AuditAction.MOVE,
        detail={"toLocation": location},
        performed_by="warehouse",
    )
    session.add(entry)
    session.flush()
    return entry


def test_history_with_null_row_and_bay_keeps_only_aisle_only_moves(db_session):
    aisle = _aisle()
    bare = _log(db_session, {"aisle": aisle, "row": None, "bay": None, "warehouseId": None})
    shelf = _log(db_session, {"aisle": aisle, "row": "1", "bay": "1", "warehouseId": None})

    assert [e.id for e in warehouse_repository.get_location_audit_history(db_session, aisle, None, None)] == [bare.id]
    assert {e.id for e in warehouse_repository.get_location_audit_history(db_session, aisle)} == {bare.id, shelf.id}
