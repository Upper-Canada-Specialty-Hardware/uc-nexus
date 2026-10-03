"""Enqueue-side helper shared by the two GP-first resolvers (#353 PR E).

Kept out of `gp_outbox_worker` so the resolvers do not import the worker (and its lazy schema
imports) just to queue a row, and out of the repository so the "which failures may be queued" rule
lives in exactly one place rather than being restated at each call site."""

import logging
import uuid

from sqlalchemy.orm import Session

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


def _guard_registration(session, persist_context: dict, idempotency_key: str) -> None:
    """Queue a registration only for a live Draft with no other registration waiting (#1165, #1166).

    The register pre-flight checks the same thing, but in its own short session, and the relay call
    sits between it and this one. Two tabs could both pass it and both queue. Taken here under the PO's
    row lock, in the transaction that queues, so the second waits for the first, then sees its row; a
    cancel takes the same lock, so a cancel and a queue cannot cross either."""
    from sqlalchemy import select

    from app.errors import InvalidStateTransitionError
    from app.models.enums import POStatus
    from app.models.purchase_order import PurchaseOrder

    po_id = uuid.UUID(str(persist_context["po_id"]))
    po = session.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if po is None or po.deleted_at is not None or po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError("This PO is no longer a Draft, so its registration was not queued")
    if gp_outbox_repository.queued_po_registration(session, po_id, exclude_key=idempotency_key) is not None:
        raise InvalidStateTransitionError(
            "This PO's registration is already queued and will post to GP when the relay is back"
        )


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
    session: Session | None = None,
) -> str:
    """Queue the write and return the outbox entry id (as a string).

    With no `session` it runs in its own and commits. Given a caller's `session` it only flushes, so
    the caller can save its own state in the same transaction and commit once (#1365); the caller
    then wakes the worker after its commit.

    Idempotent by `idempotency_key`: re-submitting the same user action while it is queued returns
    the existing entry, so the user sees one queued item and GP will see one write."""
    if session is not None:
        return _enqueue_in(
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
    with SessionLocal() as own:
        entry_id = _enqueue_in(
            own,
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
        own.commit()
    logger.info("gp outbox: queued", extra={"op": op, "label": label, "entry_id": entry_id})
    # The relay may have come back between the failure and this commit; a nudge costs nothing.
    gp_outbox_worker.wake()
    return entry_id


def _enqueue_in(session: Session, **kwargs) -> str:
    if kwargs["op"] == "register_po_in_gp":
        _guard_registration(session, kwargs["persist_context"], kwargs["idempotency_key"])
    row = gp_outbox_repository.enqueue(session, **kwargs)
    return str(row.id)
