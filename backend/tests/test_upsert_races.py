"""First saves that used to race into a masked unique-constraint error (#1475).

PO document data was read and inserted when missing, so two buyers saving one PO's document for the
first time both inserted. Two real sessions on separate connections, the first holding its insert
uncommitted while the second arrives.
"""

import threading
import time
import uuid

import pytest

from app.database import SessionLocal
from app.models.enums import POStatus
from app.models.purchase_order import PODocumentData, PurchaseOrder
from app.repositories import po_repository


@pytest.fixture
def po_id(_migrate_database):
    with SessionLocal() as s:
        po = PurchaseOrder(
            id=uuid.uuid4(),
            request_number=f"REQ-{uuid.uuid4().hex[:8]}",
            status=POStatus.GP_REGISTERED,
            company="TUBC",
        )
        s.add(po)
        s.commit()
        pid = po.id
    yield pid
    with SessionLocal() as s:
        s.query(PODocumentData).filter(PODocumentData.po_id == pid).delete()
        s.query(PurchaseOrder).filter(PurchaseOrder.id == pid).delete()
        s.commit()


def _save(pid, *, buyer: str, hold: float, start_after: float, errors: list):
    time.sleep(start_after)
    try:
        with SessionLocal() as s:
            po_repository.upsert_po_document_data(s, pid, buyer_name=buyer)
            time.sleep(hold)  # the other save arrives while this insert is uncommitted
            s.commit()
    except BaseException as e:  # noqa: BLE001 - the test reports whatever the race raised
        errors.append(e)


def test_two_first_document_saves_on_one_po_keep_one_row_and_the_later_values(po_id):
    errors: list = []
    threads = [
        threading.Thread(
            target=_save, args=(po_id,), kwargs={"buyer": "First", "hold": 1.0, "start_after": 0.0, "errors": errors}
        ),
        threading.Thread(
            target=_save, args=(po_id,), kwargs={"buyer": "Second", "hold": 0.0, "start_after": 0.3, "errors": errors}
        ),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert errors == []
    with SessionLocal() as s:
        rows = s.query(PODocumentData).filter(PODocumentData.po_id == po_id).all()
        assert [r.buyer_name for r in rows] == ["Second"]
