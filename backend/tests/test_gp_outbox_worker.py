"""The outbox drainer's failure taxonomy (#353 PR E).

**Never touches GP.** `relay_gateway.relay_call` is stubbed in every test here, which is the same
rule the online GP tests follow.

The classification is the whole point of the worker: which failures may be retried automatically,
which must stop and wait for a human, and which must never count against the retry budget. Getting
`ambiguous` wrong means an automatic retry posts a second GP receipt."""

import asyncio
import uuid

import pytest

from app.errors import RelayCallError, RelayTimeoutError, RelayUnavailableError
from app.repositories import gp_outbox_repository
from app.services import gp_outbox_worker


def _enqueue_committed(op: str = "create_receive", company: str = "TUBC") -> tuple[uuid.UUID, str]:
    """The worker opens its own sessions, so the row has to be committed, not just flushed."""
    from app.database import SessionLocal

    key = str(uuid.uuid4())
    with SessionLocal() as session:
        row = gp_outbox_repository.enqueue(
            session,
            idempotency_key=key,
            op=op,
            relay_op="create_receipt" if op == "create_receive" else "create_po",
            company=company,
            payload={"po_number": "0000123"},
            persist_context={"po_id": str(uuid.uuid4())},
            entity_key=f"po:{uuid.uuid4()}",
            label="Receive against PO 0000123",
        )
        row_id = row.id
        session.commit()
    return row_id, key


def _delete(row_id: uuid.UUID) -> None:
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    with SessionLocal() as session:
        row = session.get(GpWriteOutbox, row_id)
        if row is not None:
            session.delete(row)
            session.commit()


def _read(row_id: uuid.UUID):
    from app.database import SessionLocal

    with SessionLocal() as session:
        row = gp_outbox_repository.get_entry(session, row_id)
        if row is None:
            return None
        return {
            "status": row.status,
            "attempts": row.attempts,
            "failure_kind": row.failure_kind,
            "last_error": row.last_error,
        }


def _stub_relay(monkeypatch, result=None, raises=None, calls=None):
    async def _call(company, op, payload=None, timeout=30.0):
        if calls is not None:
            calls.append((company, op))
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "relay_call", _call)


def _stub_persist(monkeypatch, raises=None, seen=None):
    def _handler(context, relay_result, key):
        if seen is not None:
            seen.append((context, relay_result, key))
        if raises is not None:
            raise raises

    monkeypatch.setitem(gp_outbox_worker._HANDLERS, "create_receive", _handler)


def test_a_relay_down_row_stays_pending_and_does_not_burn_an_attempt(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, raises=RelayUnavailableError("no relay", dispatched=False))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "PENDING"
        assert state["attempts"] == 0  # a week-long outage must not poison the queue
    finally:
        _delete(row_id)


def test_a_dispatched_disconnect_fails_as_ambiguous_and_is_never_retried(_migrate_database, monkeypatch):
    # The job was already on the wire: GP may hold the write, so an automatic retry could double-post.
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, raises=RelayUnavailableError("relay disconnected", dispatched=True))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "FAILED"
        assert state["failure_kind"] == "ambiguous"
    finally:
        _delete(row_id)


def test_a_timeout_fails_as_ambiguous(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, raises=RelayTimeoutError("relay did not answer"))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        assert _read(row_id)["failure_kind"] == "ambiguous"
    finally:
        _delete(row_id)


def test_a_gp_rejection_fails_as_gp_rejected(_migrate_database, monkeypatch):
    # eConnect said no. Deterministic: retrying never helps.
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, raises=RelayCallError("eConnect rejected the receipt", detail={"error": "x"}))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "FAILED"
        assert state["failure_kind"] == "gp_rejected"
    finally:
        _delete(row_id)


def test_a_successful_drain_calls_the_persist_helper_and_marks_succeeded(_migrate_database, monkeypatch):
    row_id, key = _enqueue_committed()
    try:
        seen: list = []
        _stub_relay(monkeypatch, result={"receipt": "R1"})
        _stub_persist(monkeypatch, seen=seen)
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        assert _read(row_id)["status"] == "SUCCEEDED"
        # The worker rehydrates persist_context and hands it to the SAME helper the resolver uses.
        assert len(seen) == 1
        assert seen[0][1] == {"receipt": "R1"}
        assert seen[0][2] == key
    finally:
        _delete(row_id)


def test_a_ledger_that_already_holds_a_relay_result_skips_the_relay_call(_migrate_database, monkeypatch):
    # GP has already run for this key. Calling again would post a second receipt.
    row_id, key = _enqueue_committed()
    try:
        from app.services import gp_idempotency

        gp_idempotency.record_relay_result(key, "create_receive", {"receipt": "already"})
        calls: list = []
        _stub_relay(monkeypatch, result={"receipt": "should-not-happen"}, calls=calls)
        _stub_persist(monkeypatch)
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        assert calls == []
        assert _read(row_id)["status"] == "SUCCEEDED"
    finally:
        _delete(row_id)


def test_a_persist_that_raises_an_app_error_fails_as_persist_failed(_migrate_database, monkeypatch):
    # GP committed but UC Nexus will not take it (the PO left DRAFT, the receive is no longer
    # eligible). No retry can fix a state disagreement.
    from app.errors import InvalidStateTransitionError

    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, result={"receipt": "R1"})
        _stub_persist(monkeypatch, raises=InvalidStateTransitionError("PO is no longer a draft"))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "FAILED"
        assert state["failure_kind"] == "persist_failed"
    finally:
        _delete(row_id)


def test_a_transient_persist_error_is_retried(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, result={"receipt": "R1"})
        _stub_persist(monkeypatch, raises=RuntimeError("connection reset"))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "PENDING"
        assert state["attempts"] == 1
    finally:
        _delete(row_id)


@pytest.mark.parametrize(
    "env, expected",
    [("true", True), ("1", True), ("", True), ("false", False), ("0", False), ("no", False)],
)
def test_the_worker_can_be_disabled_without_a_deploy(monkeypatch, env, expected):
    if env:
        monkeypatch.setenv("GP_OUTBOX_ENABLED", env)
    else:
        monkeypatch.delenv("GP_OUTBOX_ENABLED", raising=False)
    assert gp_outbox_worker.enabled() is expected
