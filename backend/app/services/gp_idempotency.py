"""Ledger access for the GP-first write idempotency key (issue #202 follow-up #1).

The three GP-first resolvers (create_po / register_po_in_gp / create_receive) push to GP via the relay
before persisting, so the two systems are not atomic. A client generates one key per user action and
re-sends it on retry; these helpers key the gp_write_idempotency ledger by it so a retry is a no-op in
GP. See models/gp_write.py for the full flow and its one residual window."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.errors import ValidationError
from app.models.gp_write import GpWriteIdempotency


@dataclass
class IdempotencyState:
    op: str
    relay_result: dict | None
    result_id: str | None


def load(key: str) -> IdempotencyState | None:
    """Read the ledger row for key in its own short-lived session (None if never seen)."""
    with SessionLocal() as session:
        row = session.get(GpWriteIdempotency, key)
        if row is None:
            return None
        return IdempotencyState(op=row.op, relay_result=row.relay_result, result_id=row.result_id)


def validate_key(key: str) -> str:
    cleaned = (key or "").strip()
    if not cleaned:
        raise ValidationError("idempotency_key is required", field="idempotency_key")
    if len(cleaned) > 100:
        raise ValidationError("idempotency_key must be at most 100 characters", field="idempotency_key")
    return cleaned


def record_relay_result(key: str, op: str, relay_result: dict | None) -> None:
    """Commit the relay's result under key in its own transaction, right after the GP write succeeds -
    so a later persist failure (which rolls back the persist transaction) does not discard the proof
    that GP already ran. A retry then reuses this instead of hitting GP a second time."""
    with SessionLocal() as session:
        _upsert(session, key, op=op, relay_result=relay_result, result_id=None)
        session.commit()


def stamp_result_id(session: Session, key: str, op: str, relay_result: dict | None, result_id: str) -> None:
    """Set the created record's id on the ledger row WITHIN the caller's persist transaction, so the row
    is completed atomically with the record it points at. A retry after full success then returns that
    record without re-persisting."""
    _upsert(session, key, op=op, relay_result=relay_result, result_id=result_id)


def _upsert(session: Session, key: str, *, op: str, relay_result: dict | None, result_id: str | None) -> None:
    row = session.get(GpWriteIdempotency, key)
    if row is None:
        session.add(GpWriteIdempotency(key=key, op=op, relay_result=relay_result, result_id=result_id))
        return
    # never null out a value a prior phase already recorded.
    if relay_result is not None:
        row.relay_result = relay_result
    if result_id is not None:
        row.result_id = result_id
