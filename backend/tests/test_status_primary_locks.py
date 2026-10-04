"""Status steps and the primary flag decide from a locked, fresh read (#1431).

A concurrent write is simulated by changing the row in the database behind the session's back, the
session still holding its earlier copy: the state a request is in when another commits first and its
own flush is the one that waits. DB-backed: skips locally, runs in CI.
"""

import base64
import uuid

import pytest
from sqlalchemy import select, update

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import PODocumentType, POStatus
from app.models.purchase_order import PODocument, PurchaseOrder
from app.models.warehouse import Warehouse
from app.repositories import po_repository, warehouse_admin_repository
from app.services import storage


@pytest.fixture
def bucket(monkeypatch):
    deleted: list[str] = []
    monkeypatch.setattr(storage, "upload_file", lambda key, data, content_type, *, as_attachment=False: key)
    monkeypatch.setattr(storage, "delete_file", lambda key: deleted.append(key))
    return deleted


def _po(session, status: POStatus, *, quote: str | None = "Q-1", ack: bool = False) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        status=status,
        company="TUBC",
        vendor_quote_number=quote,
    )
    session.add(po)
    if ack:
        session.add(
            PODocument(
                id=uuid.uuid4(),
                po_id=po.id,
                file_name="ack.pdf",
                content_type="application/pdf",
                file_size=1,
                document_type=PODocumentType.VENDOR_ACKNOWLEDGEMENT,
                s3_key=f"po-documents/{po.id}/ack.pdf",
            )
        )
    session.flush()
    session.refresh(po)
    return po


def _receipt_moves_it_behind_the_session(session, po: PurchaseOrder, status: POStatus) -> None:
    session.execute(
        update(PurchaseOrder)
        .where(PurchaseOrder.id == po.id)
        .values(status=status)
        .execution_options(synchronize_session=False)
    )


def _stored_status(session, po: PurchaseOrder) -> POStatus:
    return session.scalar(
        select(PurchaseOrder.status).where(PurchaseOrder.id == po.id).execution_options(populate_existing=True)
    )


def test_an_ack_upload_does_not_write_vendor_confirmed_over_a_receipt(db_session, bucket):
    po = _po(db_session, POStatus.GP_REGISTERED)
    _receipt_moves_it_behind_the_session(db_session, po, POStatus.PARTIALLY_RECEIVED)

    po_repository.upload_po_document(
        db_session,
        po.id,
        "ack.pdf",
        "application/pdf",
        PODocumentType.VENDOR_ACKNOWLEDGEMENT,
        base64.b64encode(b"%PDF-1.7").decode(),
    )
    db_session.flush()

    assert _stored_status(db_session, po) == POStatus.PARTIALLY_RECEIVED


def test_an_upload_to_a_po_that_just_closed_is_refused_and_its_file_removed(db_session, bucket):
    po = _po(db_session, POStatus.GP_REGISTERED)
    _receipt_moves_it_behind_the_session(db_session, po, POStatus.CLOSED)

    with pytest.raises(InvalidStateTransitionError):
        po_repository.upload_po_document(
            db_session,
            po.id,
            "ack.pdf",
            "application/pdf",
            PODocumentType.VENDOR_ACKNOWLEDGEMENT,
            base64.b64encode(b"%PDF-1.7").decode(),
        )

    assert len(bucket) == 1
    assert _stored_status(db_session, po) == POStatus.CLOSED


def test_deleting_the_ack_does_not_write_registered_over_a_receipt(db_session):
    po = _po(db_session, POStatus.VENDOR_CONFIRMED, ack=True)
    doc_id = po.documents[0].id
    _receipt_moves_it_behind_the_session(db_session, po, POStatus.PARTIALLY_RECEIVED)

    po_repository.delete_po_document(db_session, doc_id)
    db_session.flush()

    assert _stored_status(db_session, po) == POStatus.PARTIALLY_RECEIVED


def test_an_edit_after_a_receipt_closed_the_po_is_refused_and_the_po_stays_closed(db_session):
    po = _po(db_session, POStatus.VENDOR_CONFIRMED, ack=True)
    _receipt_moves_it_behind_the_session(db_session, po, POStatus.CLOSED)

    with pytest.raises(InvalidStateTransitionError):
        # Clearing the quote number used to revert a stale VENDOR_CONFIRMED to GP_REGISTERED.
        po_repository.update_po(db_session, po.id, vendor_quote_number="")
    db_session.flush()

    assert _stored_status(db_session, po) == POStatus.CLOSED


def _company() -> str:
    return f"W{uuid.uuid4().hex[:8]}".upper()


def _make(session, company: str, *, primary: bool) -> Warehouse:
    tag = uuid.uuid4().hex[:6]
    return warehouse_admin_repository.create_warehouse(
        session, name=f"WH {tag}", code=f"C{tag}", company=company, is_primary=primary
    )


def _primaries(session, company: str) -> list[uuid.UUID]:
    return list(
        session.scalars(select(Warehouse.id).where(Warehouse.company == company, Warehouse.is_primary.is_(True)))
    )


def test_a_new_primary_clears_the_one_the_database_holds_not_the_sessions_copy(db_session):
    company = _company()
    w0 = _make(db_session, company, primary=True)
    w1 = _make(db_session, company, primary=False)
    w2 = _make(db_session, company, primary=False)
    db_session.flush()
    # Another admin made w1 primary and committed; this session still holds w0 primary, w1 not.
    db_session.execute(
        update(Warehouse)
        .where(Warehouse.id == w0.id)
        .values(is_primary=False)
        .execution_options(synchronize_session=False)
    )
    db_session.execute(
        update(Warehouse)
        .where(Warehouse.id == w1.id)
        .values(is_primary=True)
        .execution_options(synchronize_session=False)
    )

    warehouse_admin_repository.update_warehouse(db_session, w2.id, is_primary=True)
    db_session.flush()

    assert _primaries(db_session, company) == [w2.id]


def test_either_building_of_a_pair_can_become_primary(db_session):
    # The old flag is lifted before the new one is written, whatever order a flush would take them in.
    company = _company()
    a = _make(db_session, company, primary=True)
    b = _make(db_session, company, primary=False)
    db_session.flush()
    low, high = sorted([a, b], key=lambda w: w.id)

    warehouse_admin_repository.update_warehouse(db_session, low.id, is_primary=True)
    db_session.flush()
    assert _primaries(db_session, company) == [low.id]

    warehouse_admin_repository.update_warehouse(db_session, high.id, is_primary=True)
    db_session.flush()
    assert _primaries(db_session, company) == [high.id]


def test_the_database_refuses_a_second_primary_as_a_field_error(db_session, monkeypatch):
    # Two first buildings created primary at once: nothing to lock yet, so the index decides.
    company = _company()
    _make(db_session, company, primary=True)
    db_session.flush()
    monkeypatch.setattr(warehouse_admin_repository, "_clear_primary", lambda session, **kw: None)

    with pytest.raises(ValidationError) as exc:
        _make(db_session, company, primary=True)
    assert exc.value.field == "is_primary"
