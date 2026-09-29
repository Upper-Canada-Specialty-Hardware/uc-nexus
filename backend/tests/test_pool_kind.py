"""Stock and Overhead: one no-project pool, two kinds of row (#832).

Overhead is a flag on rows of the same pool, never a second system. What has to hold:

- the kind is part of a pool row's merge key, so stock and overhead units on one shelf never merge;
- a receive off a no-project PO lands in the pool under that PO's kind, and every other route STOCK;
- moving an existing row (transfer, reclassify) keeps its kind;
- `set_stock_item_kind` re-flags part or all of a row, merging into the other kind's row where one
  exists, and never touches deficient units;
- INVENTORY VALUE prices the two halves as separate figures.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, PoolKind, POStatus
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories import inventory_value_repository, po_repository
from app.repositories import stock as stock_repository
from app.repositories.stock.common import _find_or_create_stock_row
from app.repositories.warehouse.receiving import create_receive

from .inventory_fixtures import define_location, make_stock_item, wh_id


def _code() -> str:
    return f"PK-{uuid.uuid4().hex[:8]}"


# --- the merge key --------------------------------------------------------------------------------


def test_stock_and_overhead_rows_on_one_shelf_never_merge(db_session):
    code = _code()
    kwargs = dict(
        warehouse_id=wh_id(db_session),
        hardware_category="HINGE",
        product_code=code,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    stock = _find_or_create_stock_row(db_session, **kwargs)
    overhead = _find_or_create_stock_row(db_session, **kwargs, kind=PoolKind.OVERHEAD)
    stock_again = _find_or_create_stock_row(db_session, **kwargs, kind=PoolKind.STOCK)
    overhead_again = _find_or_create_stock_row(db_session, **kwargs, kind=PoolKind.OVERHEAD)

    assert stock.id != overhead.id
    assert stock.kind == PoolKind.STOCK
    assert overhead.kind == PoolKind.OVERHEAD
    assert stock_again.id == stock.id
    assert overhead_again.id == overhead.id


def test_a_new_pool_row_defaults_to_stock(db_session):
    si = make_stock_item(db_session, quantity=3, code=_code())
    db_session.refresh(si)
    assert si.kind == PoolKind.STOCK


def test_off_po_receive_lands_as_stock_and_overhead_receive_keeps_its_own_row(db_session):
    code = _code()
    common = dict(
        warehouse_id=wh_id(db_session),
        hardware_category="HINGE",
        product_code=code,
        deficient_quantity=0,
        aisle=None,
        row=None,
        bay=None,
        received_at=datetime.utcnow(),
        received_by="warehouse",
        po_number=None,
    )
    stock = stock_repository.receive_into_stock(db_session, quantity=2, **common)
    overhead = stock_repository.receive_into_stock(db_session, quantity=5, kind=PoolKind.OVERHEAD, **common)

    assert stock.kind == PoolKind.STOCK
    assert overhead.kind == PoolKind.OVERHEAD
    assert stock.id != overhead.id
    assert (stock.quantity, overhead.quantity) == (2, 5)


def test_transfer_and_reclassify_keep_the_rows_kind(db_session):
    define_location(db_session, aisle="PK", row="9", bay="9")
    code = _code()
    si = make_stock_item(db_session, quantity=6, code=code)
    si.kind = PoolKind.OVERHEAD
    db_session.flush()

    stock_repository.transfer_inventory(
        db_session,
        source_type="STOCK_ITEM",
        source_id=si.id,
        quantity=2,
        dest_warehouse_id=si.warehouse_id,
        dest_aisle="PK",
        dest_row="9",
        dest_bay="9",
        performed_by="warehouse",
    )
    moved = (
        db_session.query(StockItem)
        .filter(StockItem.product_code == code, StockItem.aisle == "PK", StockItem.row == "9")
        .one()
    )
    assert moved.kind == PoolKind.OVERHEAD

    new_row, original = stock_repository.reclassify_stock_item(
        db_session,
        stock_item_id=si.id,
        new_hardware_category="HINGE",
        new_product_code=_code(),
        quantity=1,
        reason_text=None,
        performed_by="warehouse",
    )
    assert original is not None
    assert new_row.kind == PoolKind.OVERHEAD


# --- receive off a no-project PO -----------------------------------------------------------------


def _registered_stock_po(session, *, pool_kind: PoolKind, code: str) -> tuple[PurchaseOrder, POLineItem]:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=None,
        pool_kind=pool_kind,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        company="TUBC",
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code=code,
        ordered_quantity=10,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=1,
    )
    session.add(line)
    session.flush()
    return po, line


@pytest.mark.parametrize("pool_kind", [PoolKind.STOCK, PoolKind.OVERHEAD])
def test_receiving_a_no_project_po_lands_in_the_pool_under_the_pos_kind(db_session, pool_kind):
    code = _code()
    po, line = _registered_stock_po(db_session, pool_kind=pool_kind, code=code)
    warehouse_id = wh_id(db_session)

    create_receive(
        db_session,
        po.id,
        "warehouse",
        [{"po_line_item_id": line.id, "quantity_received": 4, "locations": []}],
        warehouse_id=warehouse_id,
    )

    rows = db_session.query(StockItem).filter(StockItem.product_code == code).all()
    assert len(rows) == 1
    assert rows[0].kind == pool_kind
    assert rows[0].quantity == 4


# --- the PO's own choice --------------------------------------------------------------------------


def _line() -> dict:
    return {"hardware_category": "HINGE", "product_code": _code(), "ordered_quantity": 1, "unit_cost": 1.0}


def test_create_po_takes_the_pool_kind_only_without_a_project(db_session):
    stock_default = po_repository.create_po(db_session, line_items=[_line()], company="TUBC")
    overhead = po_repository.create_po(db_session, line_items=[_line()], company="TUBC", pool_kind=PoolKind.OVERHEAD)
    assert stock_default.pool_kind == PoolKind.STOCK
    assert overhead.pool_kind == PoolKind.OVERHEAD


def test_update_po_changes_the_pool_kind_on_a_draft_only(db_session):
    po = po_repository.create_po(db_session, line_items=[_line()], company="TUBC")
    po_repository.update_po(db_session, po.id, pool_kind=PoolKind.OVERHEAD)
    assert po.pool_kind == PoolKind.OVERHEAD

    po.status = POStatus.GP_REGISTERED
    db_session.flush()
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, pool_kind=PoolKind.STOCK)
    # Sending the value it already has is not a change, so it is not refused.
    po_repository.update_po(db_session, po.id, pool_kind=PoolKind.OVERHEAD)


# --- re-flagging ----------------------------------------------------------------------------------


def test_marking_part_of_a_row_as_overhead_splits_it(db_session):
    si = make_stock_item(db_session, quantity=10, code=_code(), unit_cost=Decimal("2.00"))

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=4, performed_by="warehouse"
    )

    assert original is not None and original.id == si.id
    assert si.quantity == 6
    assert si.kind == PoolKind.STOCK
    assert target.id != si.id
    assert target.kind == PoolKind.OVERHEAD
    assert target.quantity == 4
    assert target.unit_cost == Decimal("2.00")
    assert (target.aisle, target.row, target.bay) == (si.aisle, si.row, si.bay)
    audits = db_session.query(InventoryAuditLog).filter(InventoryAuditLog.action == AuditAction.POOL_KIND_CHANGE)
    assert {a.entity_id for a in audits if a.entity_id in (si.id, target.id)} == {si.id, target.id}


def test_marking_a_whole_row_flips_it_in_place(db_session):
    si = make_stock_item(db_session, quantity=3, code=_code())

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=3, performed_by="warehouse"
    )

    assert original is None
    assert target.id == si.id
    assert si.kind == PoolKind.OVERHEAD
    assert si.quantity == 3


def test_marking_merges_into_the_other_kinds_row_on_the_same_shelf(db_session):
    code = _code()
    stock = make_stock_item(db_session, quantity=5, code=code)
    overhead = make_stock_item(db_session, quantity=2, code=code)
    overhead.kind = PoolKind.OVERHEAD
    db_session.flush()

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=stock.id, kind=PoolKind.OVERHEAD, quantity=5, performed_by="warehouse"
    )

    assert target.id == overhead.id
    assert overhead.quantity == 7
    assert original is not None and stock.quantity == 0


def test_marking_refuses_deficient_units_and_bad_quantities(db_session):
    si = make_stock_item(db_session, quantity=5, deficient=2, code=_code())

    with pytest.raises(ValidationError):
        stock_repository.set_stock_item_kind(
            db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=4, performed_by="warehouse"
        )
    with pytest.raises(ValidationError):
        stock_repository.set_stock_item_kind(
            db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=0, performed_by="warehouse"
        )
    with pytest.raises(ValidationError):
        stock_repository.set_stock_item_kind(
            db_session, stock_item_id=si.id, kind=PoolKind.STOCK, quantity=1, performed_by="warehouse"
        )

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=3, performed_by="warehouse"
    )
    # The deficient units stay behind on the stock row.
    assert original is not None
    assert (si.quantity, si.deficient_quantity) == (2, 2)
    assert (target.quantity, target.deficient_quantity) == (3, 0)


def test_the_pool_read_filters_by_kind(db_session):
    code = _code()
    make_stock_item(db_session, quantity=1, code=code)
    overhead = make_stock_item(db_session, quantity=1, code=code, aisle="Z")
    overhead.kind = PoolKind.OVERHEAD
    db_session.flush()

    only_overhead = stock_repository.get_stock_items(db_session, product_code_contains=code, kind=PoolKind.OVERHEAD)
    both = stock_repository.get_stock_items(db_session, product_code_contains=code)

    assert [r.id for r in only_overhead] == [overhead.id]
    assert len(both) == 2


# --- INVENTORY VALUE -----------------------------------------------------------------------------


def test_inventory_value_prices_stock_and_overhead_apart(db_session):
    company = f"T{uuid.uuid4().hex[:8].upper()}"
    tag = uuid.uuid4().hex[:8]
    warehouse = Warehouse(
        id=uuid.uuid4(),
        company=company,
        name=f"Building {tag}",
        code=tag.upper()[:10],
        is_primary=False,
        is_active=True,
    )
    db_session.add(warehouse)
    db_session.flush()

    make_stock_item(db_session, quantity=10, code=_code(), unit_cost=Decimal("2.50"), warehouse_id=warehouse.id)
    overhead = make_stock_item(
        db_session, quantity=4, code=_code(), unit_cost=Decimal("3.00"), warehouse_id=warehouse.id
    )
    overhead.kind = PoolKind.OVERHEAD
    inventory_value_repository.set_average_door_cost(db_session, company, Decimal("100.00"), "Greg")
    inventory_value_repository.save_doors_on_hand(db_session, company, None, 2)
    db_session.flush()

    value = inventory_value_repository.get_inventory_value(db_session, company)

    assert value["general_stock"]["hardware_value"] == Decimal("25.00")
    # The general doors stay with Stock; Overhead is hardware only.
    assert value["general_stock"]["door_count"] == 2
    assert value["general_stock"]["total_value"] == Decimal("225.00")
    assert value["overhead"]["hardware_value"] == Decimal("12.00")
    assert value["overhead"]["door_count"] == 0
    assert value["overhead"]["total_value"] == Decimal("12.00")
