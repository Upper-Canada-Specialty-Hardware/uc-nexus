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


def _enqueue_committed(
    op: str = "create_receive", company: str = "TUBC", payload: dict | None = None
) -> tuple[uuid.UUID, str]:
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
            payload=payload if payload is not None else {"po_number": "0000123"},
            persist_context={"po_id": str(uuid.uuid4())},
            entity_key=f"po:{uuid.uuid4()}",
            label="Receive against PO 0000123" if op == "create_receive" else "Register PO 0000123 in GP",
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


def _stub_relay_features(monkeypatch, *features):
    """What the connected relay advertised on its hello frame. A create_po row is only pushed to a
    relay that recognises the attempt's key, so the tests that get as far as the push have to say so.
    Spelled as the literal wire string the relay puts on that frame, not as the backend's constant."""
    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "_features", frozenset(features))


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
    # A GP RECEIVE ENTRY that was already on the wire: GP may hold the receipt, nothing on it carries
    # the attempt's key, so an automatic retry could post a second one.
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
    # Again the receipt: the relay took the job and said nothing, and nobody can tell from here
    # whether GP wrote it.
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, raises=RelayTimeoutError("relay did not answer"))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        assert _read(row_id)["failure_kind"] == "ambiguous"
    finally:
        _delete(row_id)


# --- PO REGISTRATION is the exception ------------------------------------------------------------
# The relay stamps the attempt's key on the PO it creates in GP and answers a repeat of that key with
# the PO it already made, so the two failures that are ambiguous for a receipt are merely unanswered
# for a create_po: ask again. The attempt budget still bounds a GP that never answers at all.


def test_a_create_po_that_timed_out_is_asked_again_rather_than_failed(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed(op="register_po_in_gp")
    try:
        _stub_relay_features(monkeypatch, "create_po_idempotency")
        _stub_relay(monkeypatch, raises=RelayTimeoutError("relay did not answer"))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "PENDING"
        assert state["failure_kind"] is None
        assert state["attempts"] == 1  # unlike an outage, this one counts
    finally:
        _delete(row_id)


def test_a_create_po_whose_socket_died_mid_flight_is_asked_again(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed(op="register_po_in_gp")
    try:
        _stub_relay_features(monkeypatch, "create_po_idempotency")
        _stub_relay(monkeypatch, raises=RelayUnavailableError("relay disconnected", dispatched=True))
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert state["status"] == "PENDING"
        assert state["failure_kind"] is None
        assert state["attempts"] == 1
    finally:
        _delete(row_id)


def test_registration_carries_tax_reads_both_the_list_and_the_older_scalar():
    carries = gp_outbox_worker.registration_carries_tax
    assert carries({"header": {"tax_detail_ids": ["ON HST - P"]}}) is True
    assert carries({"header": {"tax_detail_id": "ON HST - P"}}) is True  # a row queued before #762
    assert carries({"header": {"tax_detail_ids": []}}) is False
    assert carries({"header": {"tax_detail_ids": [], "tax_detail_id": None}}) is False
    assert carries({"header": {}}) is False
    assert carries({"po_number": "0000123"}) is False
    assert carries("not a dict") is False


def test_a_taxed_create_po_waits_for_a_relay_that_writes_the_tax_rows(_migrate_database, monkeypatch):
    """A relay that recognises the key but ignores the detail list would register the PO with no tax
    (or, for a row queued before #762, with the summary-only shape GP doubles on save), so the row
    waits for the workstation to update - the same treatment as an unrecognised key."""
    row_id, _key = _enqueue_committed(op="register_po_in_gp", payload={"header": {"tax_detail_id": "ON HST - P"}})
    try:
        _stub_relay_features(monkeypatch, "create_po_idempotency")
        calls: list = []
        _stub_relay(monkeypatch, result={"po_number": "PO0000901"}, calls=calls)
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert calls == []
        assert state["status"] == "PENDING"
        assert state["attempts"] == 1
    finally:
        _delete(row_id)


def test_a_create_po_is_never_pushed_to_a_relay_that_cannot_recognise_the_key(_migrate_database, monkeypatch):
    """Retrying against an older build could reserve a second PO number, so the row waits for the
    workstation to update instead - the same treatment as an op the relay has never heard of."""
    row_id, _key = _enqueue_committed(op="register_po_in_gp")
    try:
        _stub_relay_features(monkeypatch)
        calls: list = []
        _stub_relay(monkeypatch, result={"po_number": "PO0000900"}, calls=calls)
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        state = _read(row_id)
        assert calls == []
        assert state["status"] == "PENDING"
        assert state["attempts"] == 1
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


def test_a_queued_receipt_forwards_the_draft_it_was_approved_from(_migrate_database, monkeypatch):
    """The approval that queued this row is only half done until the drain closes it.

    Both halves go through the same `_persist_create_receive`, which is what links the draft to the
    receive in the same transaction as the inventory credit. The worker's job is just to carry the id
    across, so what this pins is that it reads the key at all - a typo here would silently leave every
    queued approval unlinked, and nothing else in the pipeline would notice.
    """
    draft_id = uuid.uuid4()
    row_id, _key = _enqueue_committed()
    try:
        from app.database import SessionLocal
        from app.models.gp_outbox import GpWriteOutbox

        with SessionLocal() as session:
            row = session.get(GpWriteOutbox, row_id)
            row.persist_context = {
                "po_id": str(uuid.uuid4()),
                "received_by": "Wendy Warehouse",
                "warehouse_id": None,
                "line_items_data": [],
                "receive_draft_id": str(draft_id),
            }
            session.commit()

        captured = {}
        _stub_relay(monkeypatch, result={"receipt_number": "RCT1"})
        # The real adapter, with only the persist itself stubbed - so what is asserted is the
        # rehydration the adapter does, not a handler the test wrote.
        monkeypatch.setattr("app.schemas.warehouse._persist_create_receive", lambda **kw: captured.update(kw))
        monkeypatch.setitem(
            gp_outbox_worker._HANDLERS,
            "create_receive",
            gp_outbox_worker._persist_create_receive_from_context,
        )
        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert _read(row_id)["status"] == "SUCCEEDED"
        assert captured["receive_draft_id"] == draft_id
        assert captured["received_by"] == "Wendy Warehouse"
    finally:
        _delete(row_id)


def test_a_receipt_queued_before_drafts_existed_still_drains(_migrate_database, monkeypatch):
    """The outbox can hold rows from the previous deploy. Their context has no draft id, and reading
    it with `.get` is what keeps them replaying exactly as they used to."""
    row_id, _key = _enqueue_committed()
    try:
        from app.database import SessionLocal
        from app.models.gp_outbox import GpWriteOutbox

        with SessionLocal() as session:
            row = session.get(GpWriteOutbox, row_id)
            row.persist_context = {
                "po_id": str(uuid.uuid4()),
                "received_by": "Wendy Warehouse",
                "warehouse_id": None,
                "line_items_data": [],
            }
            session.commit()

        captured = {}
        _stub_relay(monkeypatch, result={"receipt_number": "RCT1"})
        monkeypatch.setattr("app.schemas.warehouse._persist_create_receive", lambda **kw: captured.update(kw))
        monkeypatch.setitem(
            gp_outbox_worker._HANDLERS,
            "create_receive",
            gp_outbox_worker._persist_create_receive_from_context,
        )
        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert _read(row_id)["status"] == "SUCCEEDED"
        assert captured["receive_draft_id"] is None
    finally:
        _delete(row_id)


# --- GP-PROCESSING after a drained registration (#702) --------------------------------------------
# A queued PO REGISTRATION deserves the same complete PO an online one gets, so the drain reads the PO
# back from GP too. Nobody is waiting on it, so it is a best effort: a failure is logged and the row
# still succeeds, because the registration DID post and the next sync fills the PO in regardless.


def _stub_gp_processing(monkeypatch, seen=None, raises=None):
    async def _run(company, po_id):
        if seen is not None:
            seen.append((company, po_id))
        if raises is not None:
            raise raises
        return "PO0000900"

    monkeypatch.setattr(gp_outbox_worker.gp_processing, "run_gp_processing", _run)


def _register_persist_context(row_id: uuid.UUID, po_id: uuid.UUID) -> None:
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    with SessionLocal() as session:
        row = session.get(GpWriteOutbox, row_id)
        row.persist_context = {"po_id": str(po_id)}
        session.commit()


def test_a_drained_registration_reads_its_po_back_from_gp(_migrate_database, monkeypatch):
    po_id = uuid.uuid4()
    row_id, _key = _enqueue_committed(op="register_po_in_gp")
    try:
        _register_persist_context(row_id, po_id)
        _stub_relay_features(monkeypatch, "create_po_idempotency")
        _stub_relay(monkeypatch, result={"po_number": "PO0000900", "company": "TUBC"})
        monkeypatch.setitem(gp_outbox_worker._HANDLERS, "register_po_in_gp", lambda *a: None)
        seen: list = []
        _stub_gp_processing(monkeypatch, seen=seen)

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert _read(row_id)["status"] == "SUCCEEDED"
        assert seen == [("TUBC", po_id)]
    finally:
        _delete(row_id)


def test_a_failed_read_back_never_fails_the_drained_row(_migrate_database, monkeypatch):
    row_id, _key = _enqueue_committed(op="register_po_in_gp")
    try:
        _register_persist_context(row_id, uuid.uuid4())
        _stub_relay_features(monkeypatch, "create_po_idempotency")
        _stub_relay(monkeypatch, result={"po_number": "PO0000900", "company": "TUBC"})
        monkeypatch.setitem(gp_outbox_worker._HANDLERS, "register_po_in_gp", lambda *a: None)
        _stub_gp_processing(monkeypatch, raises=RelayTimeoutError("relay did not answer"))

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        state = _read(row_id)
        assert state["status"] == "SUCCEEDED"
        assert state["attempts"] == 0  # no retry: the GP write already committed
    finally:
        _delete(row_id)


def test_a_drained_receipt_is_not_read_back(_migrate_database, monkeypatch):
    # GP RECEIVE ENTRY is not a registration; there is no newly numbered PO to complete.
    row_id, _key = _enqueue_committed()
    try:
        _stub_relay(monkeypatch, result={"receipt": "R1"})
        _stub_persist(monkeypatch)
        seen: list = []
        _stub_gp_processing(monkeypatch, seen=seen)

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert _read(row_id)["status"] == "SUCCEEDED"
        assert seen == []
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
