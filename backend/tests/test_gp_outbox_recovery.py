"""The outbox never strands a row in flight, and nobody's write overtakes another's (#1156).

#1192: the claim commits IN_FLIGHT before the relay call, so a worker stopped mid-call (every deploy)
or an exception nobody planned for left the row there for good, holding every later write for its PO.
#1193: cancel, retry and the worker's own finish wrote a row's status without re-reading it.
#1194: email to vendor only for a PO that is still a live order. Never touches GP."""

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import update

from app import auth
from app.database import SessionLocal
from app.models.gp_outbox import GpWriteOutbox
from app.models.purchase_order import PODocument, PurchaseOrder
from app.repositories import gp_outbox_repository, user_repository
from app.schemas import po as po_module
from app.services import gp_outbox_worker
from main import schema


def _row(op="register_po_in_gp", status="IN_FLIGHT", age_seconds=0, payload=None) -> uuid.UUID:
    """`age_seconds` backdates the claim, the way a row a stopped worker left behind looks. `payload`
    is the stored relay payload; a receipt's carries the approval's key only since #1389."""
    with SessionLocal() as session:
        row = gp_outbox_repository.enqueue(
            session,
            idempotency_key=str(uuid.uuid4()),
            op=op,
            relay_op="create_po" if op == "register_po_in_gp" else "create_receipt",
            company="TUBC",
            payload=payload if payload is not None else {"header": {}},
            persist_context={"po_id": str(uuid.uuid4())},
            entity_key=f"po:{uuid.uuid4()}",
            label="Outbox recovery test",
        )
        row.status = status
        session.flush()
        if age_seconds:
            session.execute(
                update(GpWriteOutbox)
                .where(GpWriteOutbox.id == row.id)
                .values(updated_at=datetime.utcnow() - timedelta(seconds=age_seconds))
            )
        session.commit()
        return row.id


STALE = gp_outbox_repository.STALE_IN_FLIGHT_SECONDS + 60

_KEYED_RECEIPT = {"po_number": "0000123", "idempotency_key": "a1b2c3d4-key"}


def _read(row_id):
    with SessionLocal() as session:
        row = gp_outbox_repository.get_entry(session, row_id)
        return {"status": row.status, "failure_kind": row.failure_kind, "attempts": row.attempts}


def _delete(*row_ids):
    with SessionLocal() as session:
        for row_id in row_ids:
            row = session.get(GpWriteOutbox, row_id)
            if row is not None:
                session.delete(row)
        session.commit()


# --- #1192: nothing stays in flight ---


def test_the_sweep_puts_a_stale_registration_back_and_fails_a_stale_receipt_as_ambiguous(
    _migrate_database, monkeypatch
):
    notified = []
    monkeypatch.setattr(gp_outbox_worker, "_notify_failure", lambda row_id: notified.append(row_id))
    registration = _row(age_seconds=STALE)
    receipt = _row(op="create_receive", age_seconds=STALE)
    keyed_receipt = _row(op="create_receive", age_seconds=STALE, payload=_KEYED_RECEIPT)
    pending = _row(status="PENDING", age_seconds=STALE)
    try:
        gp_outbox_worker._recover_in_flight()
        assert _read(registration)["status"] == "PENDING"  # the relay's key makes asking again safe
        # #1389: so does a receipt that carries the approval's key; one queued before it does not.
        assert _read(keyed_receipt)["status"] == "PENDING"
        assert _read(receipt) == {"status": "FAILED", "failure_kind": "ambiguous", "attempts": 0}
        assert _read(pending)["status"] == "PENDING"
        assert receipt in notified
        assert keyed_receipt not in notified
    finally:
        _delete(registration, receipt, keyed_receipt, pending)


def test_the_sweep_leaves_a_drain_that_may_still_be_running_alone(_migrate_database, monkeypatch):
    """A deploy: the new instance sweeps while the old one is still mid relay call. Its claim is
    fresh, so the sweep must not touch it - failing a receipt the old worker is about to post would
    invite a duplicate."""
    monkeypatch.setattr(gp_outbox_worker, "_notify_failure", lambda row_id: None)
    receipt = _row(op="create_receive", age_seconds=30)
    registration = _row(age_seconds=30)
    try:
        gp_outbox_worker._recover_in_flight()
        assert _read(receipt)["status"] == "IN_FLIGHT"
        assert _read(registration)["status"] == "IN_FLIGHT"
    finally:
        _delete(receipt, registration)


def test_a_success_that_lands_after_the_sweep_is_still_recorded(_migrate_database, monkeypatch):
    """A drain that outlived the threshold: the sweep failed the row, then GP took the write and the
    Nexus side persisted it. The success is recorded rather than left as a failure someone retries."""
    monkeypatch.setattr(gp_outbox_worker, "_notify_failure", lambda row_id: None)
    receipt = _row(op="create_receive", age_seconds=STALE)
    try:
        gp_outbox_worker._recover_in_flight()
        assert _read(receipt)["status"] == "FAILED"
        assert gp_outbox_worker._finish(receipt, "mark_succeeded") is True
        assert _read(receipt)["status"] == "SUCCEEDED"
        # A failure from that late drain is still refused.
        assert gp_outbox_worker._finish(receipt, "mark_failed", kind="ambiguous", error="late") is False
    finally:
        _delete(receipt)


@pytest.mark.parametrize(
    ("op", "payload", "expected"),
    [
        ("register_po_in_gp", None, ("PENDING", None)),
        ("create_receive", None, ("FAILED", "ambiguous")),
        ("create_receive", {"po_number": "0000123", "idempotency_key": "a1b2c3d4-key"}, ("PENDING", None)),
    ],
    ids=["registration", "unkeyed-receipt", "keyed-receipt"],
)
def test_an_unexpected_error_never_leaves_the_row_in_flight(_migrate_database, monkeypatch, op, payload, expected):
    async def _boom(row_id):
        raise RuntimeError("something nobody planned for")

    monkeypatch.setattr(gp_outbox_worker, "_drain_one_claimed", _boom)
    monkeypatch.setattr(gp_outbox_worker, "_notify_failure", lambda row_id: None)
    row_id = _row(op=op, payload=payload)
    try:
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert (state["status"], state["failure_kind"]) == expected
    finally:
        _delete(row_id)


# --- #1193: cancelled is final, a claimed row cannot be cancelled ---


def test_a_retry_or_failure_never_revives_a_cancelled_row(_migrate_database):
    row_id = _row(status="CANCELLED")
    try:
        assert gp_outbox_worker._finish(row_id, "mark_retry", error="relay down", bump_attempts=False) is False
        assert gp_outbox_worker._finish(row_id, "mark_failed", kind="gp_rejected", error="no") is False
        assert _read(row_id)["status"] == "CANCELLED"
    finally:
        _delete(row_id)


def test_cancel_refuses_a_row_the_worker_holds_and_retry_brings_back_a_failed_one(_migrate_database):
    held, failed = _row(), _row(status="FAILED")
    try:
        with SessionLocal() as session:
            assert gp_outbox_repository.cancel_entry(session, held) is None
            assert gp_outbox_repository.retry_entry(session, failed).status == "PENDING"
            session.commit()
        assert _read(held)["status"] == "IN_FLIGHT"
    finally:
        _delete(held, failed)


def test_cancel_reads_the_status_from_the_database_not_a_stale_copy(_migrate_database):
    row_id = _row(status="PENDING")
    try:
        with SessionLocal() as session:
            stale = session.get(GpWriteOutbox, row_id)
            assert stale.status == "PENDING"
            # The worker claims it in its own transaction meanwhile.
            with SessionLocal() as worker:
                worker.get(GpWriteOutbox, row_id).status = "IN_FLIGHT"
                worker.commit()
            assert gp_outbox_repository.cancel_entry(session, row_id) is None
            session.commit()
        assert _read(row_id)["status"] == "IN_FLIGHT"
    finally:
        _delete(row_id)


# --- #1194: email to vendor ---


class _FakeRequest:
    headers = {"authorization": "Bearer tok"}


@pytest.mark.parametrize("status", ["CANCELLED", "CLOSED"])
def test_a_cancelled_or_closed_po_is_not_emailed(db_session, monkeypatch, status):
    from app.models.enums import PODocumentType, POStatus

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    sent = []
    monkeypatch.setattr(po_module.email_service, "is_configured", lambda: sent.append("asked") or True)

    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        po_number=f"P{uuid.uuid4().hex[:6]}",
        status=POStatus(status),
        company="TUBC",
        gp_company="TUBC",
        gp_vendor_id="ACME",
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        PODocument(
            id=uuid.uuid4(),
            po_id=po.id,
            file_name="po.pdf",
            content_type="application/pdf",
            file_size=10,
            document_type=PODocumentType.GENERATED_PO,
            s3_key=f"po/{po.id}/po.pdf",
        )
    )
    db_session.flush()

    result = asyncio.run(
        schema.execute(
            "mutation($id: ID!) { emailPoToVendor(poId: $id) { sent message } }",
            variable_values={"id": str(po.id)},
            context_value={
                "request": _FakeRequest(),
                "_auth_user_id": "u_test",
                "_auth_roles": [],
                "_auth_company": "TUBC",
            },
        )
    )
    assert result.errors is None, result.errors
    assert result.data["emailPoToVendor"]["sent"] is False
    assert status.lower() in result.data["emailPoToVendor"]["message"]
    assert sent == []  # refused before anything about sending was asked
