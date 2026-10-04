"""Two writers onto an empty shelf share one pool row (#1464).

`_find_or_create_stock_row` finds the key's row FOR UPDATE and inserts one when there is none. A FOR UPDATE
that matches nothing locks nothing and stock_items has no unique key, so two transactions that both missed
both inserted: one product shown twice in the pool. These run two real sessions on separate connections,
the first holding its transaction open over the insert while the second arrives.
"""

import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories.stock.common import _find_or_create_stock_row


@pytest.fixture
def warehouse(_migrate_database):
    with SessionLocal() as s:
        wh = Warehouse(id=uuid.uuid4(), company="TUBC", name=f"Pool {uuid.uuid4().hex[:8]}", code=uuid.uuid4().hex[:8])
        s.add(wh)
        s.commit()
        warehouse_id = wh.id
    yield warehouse_id
    with SessionLocal() as s:
        s.query(StockItem).filter(StockItem.warehouse_id == warehouse_id).delete()
        s.query(Warehouse).filter(Warehouse.id == warehouse_id).delete()
        s.commit()


def _put(warehouse_id, *, code: str, qty: int, hold: float, start_after: float, errors: list):
    """Find-or-create the key's row and add `qty`, keeping the transaction open for `hold` seconds."""
    time.sleep(start_after)
    try:
        with SessionLocal() as s:
            row = _find_or_create_stock_row(
                s,
                warehouse_id=warehouse_id,
                hardware_category="HINGE",
                product_code=code,
                aisle="A",
                row="1",
                bay="1",
                received_at=datetime.utcnow(),
                unit_cost=Decimal("12.5"),
            )
            row.quantity += qty
            s.flush()
            time.sleep(hold)  # the other writer arrives while this insert is uncommitted
            s.commit()
    except BaseException as e:  # noqa: BLE001 - the test reports whatever the race raised
        errors.append(e)


def _run(*writers):
    threads = [threading.Thread(target=_put, args=args, kwargs=kw) for args, kw in writers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)


def test_two_writers_onto_an_empty_shelf_share_one_pool_row(warehouse):
    errors: list = []
    _run(
        ((warehouse,), {"code": "HG-1464", "qty": 3, "hold": 1.0, "start_after": 0.0, "errors": errors}),
        ((warehouse,), {"code": "HG-1464", "qty": 4, "hold": 0.0, "start_after": 0.3, "errors": errors}),
    )
    assert errors == []
    with SessionLocal() as s:
        rows = s.query(StockItem).filter(StockItem.warehouse_id == warehouse).all()
        assert [r.quantity for r in rows] == [7]


def test_writers_to_different_keys_do_not_wait_on_each_other(warehouse):
    errors: list = []
    started = time.monotonic()
    _run(
        ((warehouse,), {"code": "HG-A", "qty": 1, "hold": 1.0, "start_after": 0.0, "errors": errors}),
        ((warehouse,), {"code": "HG-B", "qty": 1, "hold": 1.0, "start_after": 0.1, "errors": errors}),
    )
    assert errors == []
    # Serialized they would take two holds; side by side, about one.
    assert time.monotonic() - started < 1.8
    with SessionLocal() as s:
        assert s.query(StockItem).filter(StockItem.warehouse_id == warehouse).count() == 2
