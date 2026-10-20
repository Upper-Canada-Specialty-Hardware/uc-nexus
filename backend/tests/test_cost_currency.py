"""A unit cost carries its currency wherever it goes (#1557).

A PO is kept in GP in CAD or USD, and inventory value shows what was bought in US dollars beside the
Canadian figure. A pool row has no PO link to read the currency from, and unit_cost is copied from row to
row by every move, so the currency travels with it as `cost_currency` (null for CAD). What has to hold:

- a receipt off a USD PO lands its rows in US dollars, and a CAD one leaves the currency null;
- the currency is part of a pool row's merge key: US$5 and C$5 on one shelf are two rows;
- a destock that keeps its cost keeps its PO's currency, even off a row received before cost_currency
  existed; a destock at $0 has no currency;
- an allocation and a transfer carry the pool row's currency.
"""

from datetime import datetime
from decimal import Decimal

from app.models.enums import DestockCost
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import stock as stock_repository
from app.repositories.stock.common import _find_or_create_stock_row
from app.repositories.warehouse.receiving import create_receive

from .inventory_fixtures import define_location, make_project, make_stock_item, wh_id
from .test_pool_price import _code, _destock, _no_project_po, _po_origin_row, _pool_rows


def _set_po_currency(session, line_id, currency: str | None) -> None:
    line = session.get(POLineItem, line_id)
    session.get(PurchaseOrder, line.po_id).currency = currency
    session.flush()


def test_currency_is_part_of_the_pool_merge_key_and_cad_is_null(db_session):
    code = _code()
    kwargs = dict(
        warehouse_id=wh_id(db_session),
        hardware_category="HINGE",
        product_code=code,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
        unit_cost=Decimal("5.00"),
    )
    cad = _find_or_create_stock_row(db_session, **kwargs)
    usd = _find_or_create_stock_row(db_session, **kwargs, cost_currency="USD")

    assert cad.id != usd.id
    assert (cad.cost_currency, usd.cost_currency) == (None, "USD")
    # CAD named outright is the same as no currency: one row, not two.
    assert _find_or_create_stock_row(db_session, **kwargs, cost_currency="CAD").id == cad.id
    assert _find_or_create_stock_row(db_session, **kwargs, cost_currency="usd").id == usd.id


def test_a_receipt_off_a_usd_po_lands_in_us_dollars(db_session):
    code = _code()
    warehouse_id = wh_id(db_session)
    for currency in ("USD", "CAD"):
        po, line = _no_project_po(db_session, code=code, unit_cost=Decimal("4.00"))
        po.currency = currency
        db_session.flush()
        create_receive(
            db_session,
            po.id,
            "warehouse",
            [{"po_line_item_id": line.id, "quantity_received": 2, "locations": []}],
            warehouse_id=warehouse_id,
        )

    rows = _pool_rows(db_session, code)
    # Same product, same price, same shelf - and still two rows, one per currency.
    assert sorted((r.cost_currency or "", r.quantity) for r in rows) == [("", 2), ("USD", 2)]


def test_a_destock_that_keeps_its_cost_keeps_its_pos_currency(db_session):
    code = _code()
    project = make_project(db_session)
    # Received before cost_currency existed: the row says nothing, its PO says USD.
    il = _po_origin_row(db_session, project, code=code, unit_cost=Decimal("9.50"))
    _set_po_currency(db_session, il.po_line_item_id, "USD")

    kept = _destock(db_session, il, 3, DestockCost.KEEP)
    left_behind = _destock(db_session, il, 2, DestockCost.ZERO)

    assert (kept.unit_cost, kept.cost_currency) == (Decimal("9.50"), "USD")
    assert (left_behind.unit_cost, left_behind.cost_currency) == (Decimal("0"), None)


def test_an_allocation_and_a_transfer_carry_the_pool_rows_currency(db_session):
    code = _code()
    warehouse_id = wh_id(db_session)
    define_location(db_session, warehouse_id, "B", "2", "2")
    usd = make_stock_item(
        db_session, quantity=10, code=code, aisle="A", row="1", bay="1", unit_cost=Decimal("8"), cost_currency="USD"
    )
    cad_at_dest = make_stock_item(
        db_session, quantity=1, code=code, aisle="B", row="2", bay="2", unit_cost=Decimal("8")
    )

    stock_repository.transfer_inventory(
        db_session,
        source_type="STOCK_ITEM",
        source_id=usd.id,
        quantity=4,
        dest_warehouse_id=warehouse_id,
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert cad_at_dest.quantity == 1
    moved = [r for r in _pool_rows(db_session, code) if (r.aisle, r.row, r.bay) == ("B", "2", "2")]
    assert sorted((r.cost_currency or "", r.quantity) for r in moved) == [("", 1), ("USD", 4)]

    project = make_project(db_session)
    allocated = stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=usd.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code=code,
        quantity=2,
        target_aisle="B",
        target_row="2",
        target_bay="2",
        performed_by="warehouse",
    )
    assert (allocated.unit_cost, allocated.cost_currency) == (Decimal("8"), "USD")
