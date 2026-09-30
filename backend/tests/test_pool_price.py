"""One price per pool row (#942).

A pool row (stock_items) holds one unit cost, so what has to hold:

- a receive off a no-project PO carries the PO line's price onto the pool row;
- the price is part of the row's merge key: units at different prices, priced and $0 above all, never
  stack into one row - two receipts at two prices on one shelf are two rows;
- project -> pool (destock, deficiency send-to-stock) needs the person's choice, with no default:
  ZERO lands the units at $0, KEEP at their own effective price (the PO line's, else the row's own);
- a shipment return, a transfer and a Stock / Overhead re-flag keep the moved units' own price.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.enums import DeficiencyResolution, DestockCost, DestockSource, PoolKind, POStatus
from app.models.inventory import InventoryLocation
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository
from app.repositories.stock.common import _find_or_create_stock_row
from app.repositories.warehouse.receiving import create_receive

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def _code() -> str:
    return f"PP-{uuid.uuid4().hex[:8]}"


def _pool_rows(session, code: str) -> list[StockItem]:
    return list(
        session.query(StockItem)
        .filter(StockItem.product_code == code, StockItem.quantity + StockItem.deficient_quantity > 0)
        .order_by(StockItem.unit_cost)
        .all()
    )


def _no_project_po(session, *, code: str, unit_cost: Decimal) -> tuple[PurchaseOrder, POLineItem]:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=None,
        pool_kind=PoolKind.STOCK,
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
        unit_cost=unit_cost,
        gp_line_ord=1,
    )
    session.add(line)
    session.flush()
    return po, line


def _po_origin_row(session, project, *, code: str, unit_cost: Decimal, quantity: int = 10) -> InventoryLocation:
    """A project row received against a PO line; its price lives on the line, not the row."""
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        company=project.company,
        status=POStatus.CLOSED,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code=code,
        ordered_quantity=quantity,
        received_quantity=quantity,
        unit_cost=unit_cost,
    )
    session.add(line)
    session.flush()
    record = ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=datetime.utcnow(), received_by="receiver")
    session.add(record)
    session.flush()
    receive_line = ReceiveLineItem(
        id=uuid.uuid4(),
        receive_record_id=record.id,
        po_line_item_id=line.id,
        hardware_category="HINGE",
        product_code=code,
        quantity_received=quantity,
    )
    session.add(receive_line)
    session.flush()
    row = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        po_line_item_id=line.id,
        receive_line_item_id=receive_line.id,
        warehouse_id=wh_id(session),
        hardware_category="HINGE",
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def _destock(session, il, quantity, destock_cost):
    return stock_repository.destock_inventory(
        session,
        inventory_location_id=il.id,
        quantity=quantity,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=destock_cost,
    )


# --- the merge key -------------------------------------------------------------------------------


def test_price_is_part_of_the_merge_key_and_null_matches_zero(db_session):
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
    free = _find_or_create_stock_row(db_session, **kwargs)
    priced = _find_or_create_stock_row(db_session, **kwargs, unit_cost=Decimal("4.25"))

    assert free.id != priced.id
    assert priced.unit_cost == Decimal("4.25")
    assert _find_or_create_stock_row(db_session, **kwargs, unit_cost=Decimal("0")).id == free.id
    assert _find_or_create_stock_row(db_session, **kwargs, unit_cost=Decimal("4.2500")).id == priced.id


# --- bought into stock ---------------------------------------------------------------------------


def test_receiving_a_no_project_po_carries_the_line_price(db_session):
    code = _code()
    po, line = _no_project_po(db_session, code=code, unit_cost=Decimal("12.40"))

    create_receive(
        db_session,
        po.id,
        "warehouse",
        [{"po_line_item_id": line.id, "quantity_received": 4, "locations": []}],
        warehouse_id=wh_id(db_session),
    )

    rows = _pool_rows(db_session, code)
    assert len(rows) == 1
    assert rows[0].quantity == 4
    assert rows[0].unit_cost == Decimal("12.40")


def test_two_receipts_at_two_prices_on_one_shelf_are_two_rows(db_session):
    code = _code()
    warehouse_id = wh_id(db_session)
    define_location(db_session, warehouse_id, "A", "1", "1")
    for cost, qty in ((Decimal("3.00"), 2), (Decimal("5.00"), 3)):
        po, line = _no_project_po(db_session, code=code, unit_cost=cost)
        create_receive(
            db_session,
            po.id,
            "warehouse",
            [
                {
                    "po_line_item_id": line.id,
                    "quantity_received": qty,
                    "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": qty}],
                }
            ],
            warehouse_id=warehouse_id,
        )

    rows = _pool_rows(db_session, code)
    assert [(r.unit_cost, r.quantity) for r in rows] == [(Decimal("3.00"), 2), (Decimal("5.00"), 3)]
    assert {(r.aisle, r.row, r.bay) for r in rows} == {("A", "1", "1")}


def test_receipts_at_one_price_still_stack(db_session):
    code = _code()
    for _ in range(2):
        stock_repository.receive_into_stock(
            db_session,
            warehouse_id=wh_id(db_session),
            hardware_category="HINGE",
            product_code=code,
            quantity=2,
            deficient_quantity=0,
            aisle=None,
            row=None,
            bay=None,
            received_at=datetime.utcnow(),
            received_by="warehouse",
            po_number=None,
            unit_cost=Decimal("7.00"),
        )

    rows = _pool_rows(db_session, code)
    assert len(rows) == 1 and rows[0].quantity == 4


# --- project -> pool -----------------------------------------------------------------------------


def test_destock_without_a_cost_choice_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, code=_code())

    with pytest.raises(ValidationError) as e:
        _destock(db_session, il, 2, None)
    assert e.value.field == "destock_cost"
    assert il.quantity == 10


def test_destock_zero_and_keep_land_in_separate_rows(db_session):
    code = _code()
    project = make_project(db_session)
    il = _po_origin_row(db_session, project, code=code, unit_cost=Decimal("9.50"))

    left_behind = _destock(db_session, il, 2, DestockCost.ZERO)
    kept = _destock(db_session, il, 3, DestockCost.KEEP)

    assert left_behind.id != kept.id
    assert left_behind.unit_cost is None and left_behind.quantity == 2
    # A PO-origin row's price is its PO line's.
    assert kept.unit_cost == Decimal("9.50") and kept.quantity == 3
    assert (kept.aisle, kept.row, kept.bay) == (left_behind.aisle, left_behind.row, left_behind.bay)
    assert il.quantity == 5


def test_destock_keep_falls_back_to_the_rows_own_cost(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, code=_code(), unit_cost=Decimal("6.00"))

    assert _destock(db_session, il, 1, DestockCost.KEEP).unit_cost == Decimal("6.00")


def test_deficiency_send_to_stock_from_a_project_row_requires_the_choice(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4, code=_code(), unit_cost=Decimal("6.00"))

    kwargs = dict(
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=2,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )
    with pytest.raises(ValidationError) as e:
        stock_repository.resolve_deficiency(db_session, **kwargs)
    assert e.value.field == "destock_cost"
    assert (il.quantity, il.deficient_quantity) == (10, 4)

    zero = stock_repository.resolve_deficiency(db_session, **kwargs, destock_cost=DestockCost.ZERO)
    keep = stock_repository.resolve_deficiency(db_session, **kwargs, destock_cost=DestockCost.KEEP)
    zero_row = db_session.get(StockItem, zero.resulting_stock_item_id)
    keep_row = db_session.get(StockItem, keep.resulting_stock_item_id)
    assert zero_row.id != keep_row.id
    assert zero_row.unit_cost is None
    assert keep_row.unit_cost == Decimal("6.00")


def test_other_resolutions_and_pool_rows_need_no_choice(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4, code=_code())
    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SCRAP,
        quantity=1,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )
    si = make_stock_item(db_session, quantity=5, deficient=2, code=_code())
    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=2,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )
    assert si.deficient_quantity == 0


# --- moves inside the pool keep the price ---------------------------------------------------------


def test_transfer_keeps_the_price_and_never_stacks_onto_a_zero_row(db_session):
    code = _code()
    warehouse_id = wh_id(db_session)
    define_location(db_session, warehouse_id, "B", "2", "2")
    priced = make_stock_item(db_session, quantity=10, code=code, aisle="A", row="1", bay="1", unit_cost=Decimal("8"))
    free_at_dest = make_stock_item(db_session, quantity=1, code=code, aisle="B", row="2", bay="2")

    stock_repository.transfer_inventory(
        db_session,
        source_type="STOCK_ITEM",
        source_id=priced.id,
        quantity=4,
        dest_warehouse_id=warehouse_id,
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert free_at_dest.quantity == 1
    moved = [r for r in _pool_rows(db_session, code) if (r.aisle, r.row, r.bay) == ("B", "2", "2")]
    assert sorted((r.unit_cost or Decimal("0"), r.quantity) for r in moved) == [
        (Decimal("0"), 1),
        (Decimal("8"), 4),
    ]


def test_a_kind_change_keeps_the_price(db_session):
    code = _code()
    priced = make_stock_item(db_session, quantity=10, code=code, unit_cost=Decimal("2.00"))
    zero_overhead = make_stock_item(db_session, quantity=3, code=code)
    zero_overhead.kind = PoolKind.OVERHEAD
    db_session.flush()

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=priced.id, kind=PoolKind.OVERHEAD, quantity=4, performed_by="warehouse"
    )

    assert target.id != zero_overhead.id
    assert target.unit_cost == Decimal("2.00") and target.quantity == 4
    assert zero_overhead.quantity == 3


def test_a_whole_row_kind_change_flips_in_place_when_only_a_differently_priced_row_exists(db_session):
    code = _code()
    priced = make_stock_item(db_session, quantity=3, code=code, unit_cost=Decimal("2.00"))
    zero_overhead = make_stock_item(db_session, quantity=1, code=code)
    zero_overhead.kind = PoolKind.OVERHEAD
    db_session.flush()

    target, original = stock_repository.set_stock_item_kind(
        db_session, stock_item_id=priced.id, kind=PoolKind.OVERHEAD, quantity=3, performed_by="warehouse"
    )

    assert original is None and target.id == priced.id
    assert priced.kind == PoolKind.OVERHEAD and priced.unit_cost == Decimal("2.00")
    assert zero_overhead.quantity == 1
