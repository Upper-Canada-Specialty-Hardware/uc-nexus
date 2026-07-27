"""The GP write outbox table and its claim rules (#353 PR E).

The claim query is the part with real consequences: per-entity FIFO is what stops a queued receipt
being drained ahead of the registration of the PO it is against (which would fail, because the PO is
not in GP yet), and not counting a relay-down retry against the attempt budget is what stops a long
outage from failing every queued write the moment it becomes deliverable again."""

import uuid
from datetime import datetime, timedelta

from app.repositories import gp_outbox_repository


def _enqueue(session, *, key=None, entity_key="po:1", company="TUBC", op="create_receive", label="Receive"):
    return gp_outbox_repository.enqueue(
        session,
        idempotency_key=key or str(uuid.uuid4()),
        op=op,
        relay_op="create_receipt" if op == "create_receive" else "create_po",
        company=company,
        payload={"po_number": "0000123"},
        persist_context={"po_id": str(uuid.uuid4())},
        entity_key=entity_key,
        label=label,
    )


def test_enqueue_twice_under_one_key_returns_the_same_row(db_session):
    # This is what makes a resubmit-while-queued a no-op instead of a second GP write.
    key = str(uuid.uuid4())
    first = _enqueue(db_session, key=key)
    second = _enqueue(db_session, key=key)
    assert first.id == second.id


def test_claim_next_takes_the_oldest_due_row_and_marks_it_in_flight(db_session):
    older = _enqueue(db_session, entity_key="po:a")
    older.created_at = datetime.utcnow() - timedelta(minutes=5)
    newer = _enqueue(db_session, entity_key="po:b")
    newer.created_at = datetime.utcnow()
    db_session.flush()

    claimed = gp_outbox_repository.claim_next(db_session, "TUBC")
    assert claimed is not None
    assert claimed.id == older.id
    assert claimed.status == "IN_FLIGHT"


def test_claim_next_respects_per_entity_fifo(db_session):
    # Two writes against the SAME PO: the second must not be claimable while the first is unfinished.
    first = _enqueue(db_session, entity_key="po:same", op="register_po_in_gp", label="Register")
    first.created_at = datetime.utcnow() - timedelta(minutes=5)
    second = _enqueue(db_session, entity_key="po:same", label="Receive")
    second.created_at = datetime.utcnow()
    db_session.flush()

    claimed = gp_outbox_repository.claim_next(db_session, "TUBC")
    assert claimed is not None and claimed.id == first.id

    # first is now IN_FLIGHT, so the receipt behind it is still blocked.
    assert gp_outbox_repository.claim_next(db_session, "TUBC") is None

    gp_outbox_repository.mark_succeeded(db_session, first)
    unblocked = gp_outbox_repository.claim_next(db_session, "TUBC")
    assert unblocked is not None and unblocked.id == second.id


def test_claim_next_skips_another_companys_rows(db_session):
    _enqueue(db_session, company="TUCSH", entity_key="po:other")
    assert gp_outbox_repository.claim_next(db_session, "TUBC") is None


def test_claim_next_respects_next_attempt_at(db_session):
    row = _enqueue(db_session, entity_key="po:later")
    row.next_attempt_at = datetime.utcnow() + timedelta(minutes=10)
    db_session.flush()
    assert gp_outbox_repository.claim_next(db_session, "TUBC") is None


def test_mark_retry_without_bumping_attempts_leaves_the_budget_alone(db_session):
    # "The relay is still down" is not a failure of this row. Counting it would let a week-long
    # outage exhaust every queued write's budget.
    row = _enqueue(db_session, entity_key="po:retry")
    gp_outbox_repository.mark_retry(db_session, row, error="relay down", bump_attempts=False)
    assert row.attempts == 0
    assert row.status == "PENDING"

    gp_outbox_repository.mark_retry(db_session, row, error="transient", bump_attempts=True)
    assert row.attempts == 1


def test_mark_failed_removes_the_row_from_the_claimable_set(db_session):
    row = _enqueue(db_session, entity_key="po:dead")
    gp_outbox_repository.mark_failed(db_session, row, kind="gp_rejected", error="eConnect said no")
    assert row.status == "FAILED"
    assert gp_outbox_repository.claim_next(db_session, "TUBC") is None


def test_summary_counts_by_status(db_session):
    pending = _enqueue(db_session, entity_key="po:s1")
    failed = _enqueue(db_session, entity_key="po:s2")
    gp_outbox_repository.mark_failed(db_session, failed, kind="gp_rejected", error="no")
    done = _enqueue(db_session, entity_key="po:s3")
    gp_outbox_repository.mark_succeeded(db_session, done)

    data = gp_outbox_repository.summary(db_session)
    assert data["pending"] >= 1
    assert data["failed"] >= 1
    assert data["oldest_pending_at"] is not None
    assert data["last_drained_at"] is not None
    assert pending.status == "PENDING"


def test_retry_entry_resets_the_attempt_budget_and_requeues(db_session):
    row = _enqueue(db_session, entity_key="po:manual")
    row.attempts = 5
    gp_outbox_repository.mark_failed(db_session, row, kind="exhausted", error="gave up")

    requeued = gp_outbox_repository.retry_entry(db_session, row.id)
    assert requeued is not None
    assert requeued.status == "PENDING"
    assert requeued.attempts == 0
    assert requeued.failure_kind is None


def test_cancel_entry_refuses_a_row_that_is_on_the_wire(db_session):
    # Cancelling an IN_FLIGHT row would leave the worker writing to a row a human believes is dead.
    row = _enqueue(db_session, entity_key="po:inflight")
    claimed = gp_outbox_repository.claim_next(db_session, "TUBC")
    assert claimed is not None and claimed.id == row.id
    assert gp_outbox_repository.cancel_entry(db_session, row.id) is None


def test_cancel_entry_abandons_a_pending_row(db_session):
    row = _enqueue(db_session, entity_key="po:abandon")
    cancelled = gp_outbox_repository.cancel_entry(db_session, row.id)
    assert cancelled is not None and cancelled.status == "CANCELLED"
    assert gp_outbox_repository.claim_next(db_session, "TUBC") is None
