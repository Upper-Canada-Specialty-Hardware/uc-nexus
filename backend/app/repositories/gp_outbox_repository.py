"""All data access for the GP write outbox (#353 PR E).

The claim query is the interesting part; everything else is bookkeeping. See `claim_next`."""

import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.gp_outbox import GpWriteOutbox

# Backoff for a retryable failure. Capped at 30 minutes so a long outage does not push the next
# attempt beyond the point where anybody is still watching; jittered so a queue that backed up behind
# one outage does not come back as a thundering herd.
_BACKOFF_BASE_SECONDS = 15
_BACKOFF_CAP_SECONDS = 1800
_BACKOFF_JITTER = 0.2

# A row that has failed this many times is not going to succeed by being tried again.
MAX_ATTEMPTS = 8


def _backoff_seconds(attempts: int, rng: random.Random | None = None) -> float:
    rng = rng or random
    base = min(_BACKOFF_BASE_SECONDS * (2**attempts), _BACKOFF_CAP_SECONDS)
    return base * (1 + rng.uniform(-_BACKOFF_JITTER, _BACKOFF_JITTER))


def enqueue(
    session: Session,
    *,
    idempotency_key: str,
    op: str,
    relay_op: str,
    company: str,
    payload: dict,
    persist_context: dict,
    entity_key: str,
    label: str,
    project_id: uuid.UUID | None = None,
    requested_by: str | None = None,
) -> GpWriteOutbox:
    """Queue a GP write, or return the row that is already queued under this idempotency key.

    Returning the existing row rather than raising is what makes a resubmit-while-queued a no-op: the
    user pressing the button again gets the same entry, not a second GP write."""
    existing = session.scalars(select(GpWriteOutbox).where(GpWriteOutbox.idempotency_key == idempotency_key)).first()
    if existing is not None:
        return existing

    row = GpWriteOutbox(
        id=uuid.uuid4(),
        idempotency_key=idempotency_key,
        op=op,
        relay_op=relay_op,
        company=company,
        payload=payload,
        persist_context=persist_context,
        entity_key=entity_key,
        project_id=project_id,
        label=label,
        requested_by=requested_by,
        status="PENDING",
        attempts=0,
        next_attempt_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def claim_next(session: Session, company: str) -> GpWriteOutbox | None:
    """Take the oldest due PENDING row for `company`, marking it IN_FLIGHT.

    Two things this query enforces that a plain ORDER BY would not:

    - **Per-entity FIFO.** The NOT EXISTS refuses a row while an OLDER unfinished row for the same
      `entity_key` is still queued. Both ops key on `po:<id>`, so a receipt can never overtake the
      registration of the PO it is against - which would fail, because the PO is not in GP yet.
    - **`FOR UPDATE SKIP LOCKED`.** There is one worker on one replica today, so this costs nothing;
      it is here so that the day a second replica exists, two workers cannot claim the same row."""
    row_id = session.execute(
        text(
            """
            SELECT o.id
              FROM gp_write_outbox o
             WHERE o.status = 'PENDING'
               AND o.company = :company
               AND o.next_attempt_at <= :now
               AND NOT EXISTS (
                   SELECT 1 FROM gp_write_outbox p
                    WHERE p.entity_key = o.entity_key
                      AND p.status IN ('PENDING', 'IN_FLIGHT')
                      AND (p.created_at, p.id) < (o.created_at, o.id)
               )
             ORDER BY o.created_at, o.id
             LIMIT 1
               FOR UPDATE SKIP LOCKED
            """
        ),
        {"company": company, "now": datetime.utcnow()},
    ).scalar()
    if row_id is None:
        return None

    row = session.get(GpWriteOutbox, row_id)
    if row is None:
        return None
    row.status = "IN_FLIGHT"
    session.flush()
    return row


def mark_succeeded(session: Session, row: GpWriteOutbox) -> None:
    row.status = "SUCCEEDED"
    row.succeeded_at = datetime.utcnow()
    row.last_error = None
    row.last_error_code = None
    row.failure_kind = None
    session.flush()


def mark_retry(
    session: Session,
    row: GpWriteOutbox,
    *,
    error: str,
    error_code: str | None = None,
    bump_attempts: bool = True,
    retry_in_seconds: float | None = None,
) -> None:
    """Put a row back on the queue.

    `bump_attempts=False` is the load-bearing option: "the relay is still down" is not a failure of
    this row, and counting it would let a week-long outage exhaust the attempt budget of every queued
    write and fail them all the moment they became deliverable again."""
    if bump_attempts:
        row.attempts += 1
    delay = retry_in_seconds if retry_in_seconds is not None else _backoff_seconds(row.attempts)
    row.status = "PENDING"
    row.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
    row.last_error = error
    row.last_error_code = error_code
    session.flush()


def mark_failed(session: Session, row: GpWriteOutbox, *, kind: str, error: str, error_code: str | None = None) -> None:
    row.status = "FAILED"
    row.failure_kind = kind
    row.last_error = error
    row.last_error_code = error_code
    session.flush()


def list_entries(session: Session, status: str | None = None, limit: int = 100) -> list[GpWriteOutbox]:
    stmt = select(GpWriteOutbox).order_by(GpWriteOutbox.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(GpWriteOutbox.status == status)
    return list(session.scalars(stmt).all())


def get_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    return session.get(GpWriteOutbox, entry_id)


def summary(session: Session) -> dict:
    """Scalar aggregates only - this is polled by every browser with the app open, so it must never
    load rows (see the GraphQL/SQLAlchemy performance rules in CLAUDE.md)."""
    counts = dict(
        session.execute(
            select(GpWriteOutbox.status, func.count())
            .where(GpWriteOutbox.status.in_(("PENDING", "IN_FLIGHT", "FAILED")))
            .group_by(GpWriteOutbox.status)
        ).all()
    )
    oldest_pending_at = session.scalar(
        select(func.min(GpWriteOutbox.created_at)).where(GpWriteOutbox.status == "PENDING")
    )
    last_drained_at = session.scalar(select(func.max(GpWriteOutbox.succeeded_at)))
    return {
        "pending": counts.get("PENDING", 0),
        "in_flight": counts.get("IN_FLIGHT", 0),
        "failed": counts.get("FAILED", 0),
        "oldest_pending_at": oldest_pending_at,
        "last_drained_at": last_drained_at,
    }


def retry_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    """Admin: put a FAILED row back on the queue immediately, with a fresh attempt budget."""
    row = session.get(GpWriteOutbox, entry_id)
    if row is None or row.status not in ("FAILED", "CANCELLED"):
        return None
    row.status = "PENDING"
    row.attempts = 0
    row.next_attempt_at = datetime.utcnow()
    row.failure_kind = None
    session.flush()
    return row


def cancel_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    """Admin: abandon a queued write. Only a row that is not currently on the wire may be cancelled -
    cancelling an IN_FLIGHT row would leave the worker writing to a row a human believes is dead."""
    row = session.get(GpWriteOutbox, entry_id)
    if row is None or row.status not in ("PENDING", "FAILED"):
        return None
    row.status = "CANCELLED"
    session.flush()
    return row
