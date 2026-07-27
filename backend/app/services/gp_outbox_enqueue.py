"""Enqueue-side helper shared by the two GP-first resolvers (#353 PR E).

Kept out of `gp_outbox_worker` so the resolvers do not import the worker (and its lazy schema
imports) just to queue a row, and out of the repository so the "which failures may be queued" rule
lives in exactly one place rather than being restated at each call site."""

import logging
import uuid

from app.database import SessionLocal
from app.errors import RelayUnavailableError
from app.repositories import gp_outbox_repository
from app.services import gp_outbox_worker

logger = logging.getLogger(__name__)


def may_enqueue(error: RelayUnavailableError) -> bool:
    """Whether this failure is safe to queue.

    Only an UNDISPATCHED RelayUnavailableError qualifies: the job never left the backend, so GP
    cannot have run it. A dispatched failure (the socket died with the job on the wire) and a timeout
    are both ambiguous - GP may hold the write - and must surface to the user instead."""
    return not error.dispatched


def enqueue(
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
) -> str:
    """Queue the write in its own session and return the outbox entry id (as a string).

    Idempotent by `idempotency_key`: re-submitting the same user action while it is queued returns
    the existing entry, so the user sees one queued item and GP will see one write."""
    with SessionLocal() as session:
        row = gp_outbox_repository.enqueue(
            session,
            idempotency_key=idempotency_key,
            op=op,
            relay_op=relay_op,
            company=company,
            payload=payload,
            persist_context=persist_context,
            entity_key=entity_key,
            label=label,
            project_id=project_id,
            requested_by=requested_by,
        )
        entry_id = str(row.id)
        session.commit()
    logger.info("gp outbox: queued", extra={"op": op, "label": label, "entry_id": entry_id})
    # The relay may have come back between the failure and this commit; a nudge costs nothing.
    gp_outbox_worker.wake()
    return entry_id
