"""All data access for the GP write outbox (#353 PR E).

The claim query is the interesting part; everything else is bookkeeping. See `claim_next`."""

import random
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.errors import ConflictError
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
    maybe_in_gp: bool = False,
) -> GpWriteOutbox:
    """Queue a GP write, or return the row that is already queued under this idempotency key.

    Returning the existing row rather than raising is what makes a resubmit-while-queued a no-op: the
    user pressing the button again gets the same entry, not a second GP write.

    `maybe_in_gp` (#1849) is for a write queued after an online attempt that may have reached GP."""
    existing = session.scalars(select(GpWriteOutbox).where(GpWriteOutbox.idempotency_key == idempotency_key)).first()
    if existing is not None:
        if maybe_in_gp:
            existing.maybe_in_gp = True
            session.flush()
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
        maybe_in_gp=maybe_in_gp,
    )
    session.add(row)
    session.flush()
    return row


# #1948: what a draft held by a failed registration is refused with - the held write's Retry finishes it.
HELD_REGISTRATION_REFUSAL = (
    "GP took this PO's registration, or may have, but it was not recorded here, so the draft is held. "
    "Finish it with Retry on the held GP writes panel."
)


def _registration_holds_draft(row: GpWriteOutbox, ledger) -> bool:
    """Whether a registration row still holds its draft, given its key's ledger row (or None).

    A waiting one does. So, since #1948, does a FAILED one GP took - the ledger holds the relay's answer
    and no record (a persist that failed after GP made the PO) - or may have: maybe_in_gp, unless GP
    refused it, which the relay only does after looking the key up and finding no PO under it. Freed, such
    a draft was cancelled (a GP PO Nexus has no row for) or registered again (a second GP PO)."""
    if row.status in ("PENDING", "IN_FLIGHT"):
        return True
    if row.status != "FAILED":
        return False
    if ledger is not None and ledger.result_id is not None:
        return False  # registered: the draft is gone
    if ledger is not None and ledger.relay_result is not None:
        return True
    return bool(row.maybe_in_gp) and row.failure_kind != "gp_rejected"


def registration_holds_draft(session: Session, row: GpWriteOutbox) -> bool:
    from app.models.gp_write import GpWriteIdempotency

    if row.op != "register_po_in_gp":
        return False
    if row.status != "FAILED":
        return _registration_holds_draft(row, None)
    return _registration_holds_draft(row, session.get(GpWriteIdempotency, row.idempotency_key))


def registrations_holding_drafts(session: Session, rows: list[GpWriteOutbox]) -> set[uuid.UUID]:
    """The ids of `rows` that are registrations holding their draft, with one ledger read for the lot."""
    from app.models.gp_write import GpWriteIdempotency

    registrations = [r for r in rows if r.op == "register_po_in_gp"]
    keys = [r.idempotency_key for r in registrations if r.status == "FAILED"]
    ledgers = (
        {
            row.key: row
            for row in session.scalars(select(GpWriteIdempotency).where(GpWriteIdempotency.key.in_(keys))).all()
        }
        if keys
        else {}
    )
    return {r.id for r in registrations if _registration_holds_draft(r, ledgers.get(r.idempotency_key))}


def queued_po_registration(
    session: Session, po_id: uuid.UUID, *, exclude_key: str | None = None
) -> GpWriteOutbox | None:
    """The PO's registration that still holds its draft, if there is one: waiting for GP (PENDING or
    IN_FLIGHT), or FAILED after GP took it or may have (#1948, see `_registration_holds_draft`). A FAILED
    one comes back FAILED, so a caller can say to finish it with Retry rather than wait for it.

    While it waits the PO is still a Draft, so the Draft check alone let a second registration through
    under a fresh key (a second GP PO on drain) and let a cancel drop a PO the queue then created in GP.
    `exclude_key` leaves out the caller's own attempt: a resubmit under the same key is the no-op
    `enqueue` already makes it, not a second registration."""
    stmt = select(GpWriteOutbox).where(
        GpWriteOutbox.entity_key == f"po:{po_id}",
        GpWriteOutbox.op == "register_po_in_gp",
        GpWriteOutbox.status.in_(("PENDING", "IN_FLIGHT", "FAILED")),
    )
    if exclude_key is not None:
        stmt = stmt.where(GpWriteOutbox.idempotency_key != exclude_key)
    # A waiting row first, so a caller's "queued" wording is the one a waiting registration gets.
    rows = session.scalars(stmt.order_by((GpWriteOutbox.status == "FAILED").asc(), GpWriteOutbox.created_at)).all()
    return next((row for row in rows if registration_holds_draft(session, row)), None)


def registration_for_key(session: Session, key: str) -> GpWriteOutbox | None:
    """The registration queued under one attempt's key, whatever its status (#1950)."""
    return session.scalars(
        select(GpWriteOutbox).where(GpWriteOutbox.idempotency_key == key, GpWriteOutbox.op == "register_po_in_gp")
    ).first()


def queued_registration_refusal(row: GpWriteOutbox, waiting_message: str) -> str:
    """The words a guard refuses a held draft with: its own for a waiting registration, Retry for a failed one."""
    return HELD_REGISTRATION_REFUSAL if row.status == "FAILED" else waiting_message


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
    maybe_in_gp: bool = False,
) -> None:
    """Put a row back on the queue.

    `bump_attempts=False` is the load-bearing option: "the relay is still down" is not a failure of
    this row, and counting it would let a week-long outage exhaust the attempt budget of every queued
    write and fail them all the moment they became deliverable again.

    `maybe_in_gp` says this attempt may have left the write in GP (#1849); it only ever sets the flag."""
    if bump_attempts:
        row.attempts += 1
    if maybe_in_gp:
        row.maybe_in_gp = True
    delay = retry_in_seconds if retry_in_seconds is not None else _backoff_seconds(row.attempts)
    row.status = "PENDING"
    row.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
    row.last_error = error
    row.last_error_code = error_code
    session.flush()


def mark_failed(
    session: Session,
    row: GpWriteOutbox,
    *,
    kind: str,
    error: str,
    error_code: str | None = None,
    maybe_in_gp: bool = False,
) -> None:
    row.status = "FAILED"
    # #1849: set before the release below reads it, and never cleared.
    if maybe_in_gp:
        row.maybe_in_gp = True
    row.failure_kind = kind
    row.last_error = error
    row.last_error_code = error_code
    session.flush()
    _release_receive_draft(session, row)


def mark_skipped(session: Session, row: GpWriteOutbox, *, error: str) -> None:
    """Close a row the worker refused to send, because what it would write no longer applies. Nothing
    reached GP, so it is CANCELLED (an admin can still put it back with retry), not FAILED."""
    row.status = "CANCELLED"
    row.last_error = error
    row.last_error_code = None
    session.flush()


def list_entries(
    session: Session,
    status: str | None = None,
    limit: int = 100,
    ops: list[str] | None = None,
    company: str | None = None,
    statuses: list[str] | None = None,
) -> list[GpWriteOutbox]:
    """The queue, newest first.

    `ops` filters on `relay_op` - the GP-side name of the write (create_po, create_receipt,
    update_job_site) - because that is what says which module a held write belongs to, and it is
    the name that identifies a NEXUS TO GP WRITE.

    `company` is the tenant filter (#729): the row carries the GP company its write is for, so a
    scoped caller sees their own held writes and nobody else's. None means every company, which is
    the UC NEXUS ADMIN answer."""
    stmt = select(GpWriteOutbox).order_by(GpWriteOutbox.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(GpWriteOutbox.status == status)
    if statuses:
        # #854: a module's held-writes panel asks only for what still needs someone - waiting, in
        # flight, failed - so the finished history never piles up above its table.
        stmt = stmt.where(GpWriteOutbox.status.in_(statuses))
    if ops:
        stmt = stmt.where(GpWriteOutbox.relay_op.in_(ops))
    if company is not None:
        stmt = stmt.where(GpWriteOutbox.company == company)
    return list(session.scalars(stmt).all())


def get_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    return session.get(GpWriteOutbox, entry_id)


def get_entry_locked(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    """The row under FOR UPDATE, re-read from the database rather than the session's copy, so every
    writer of a row's status (cancel, retry, the worker's finish) decides on the status it will change."""
    return session.get(GpWriteOutbox, entry_id, with_for_update=True, populate_existing=True)


# A row is only taken for abandoned once it has sat IN_FLIGHT far longer than any live drain can: the
# relay call gives up at 30 seconds and the persist after it is a handful of queries. During a deploy
# the old instance can still be mid-call while the new one starts, and its claim has already committed,
# so a row lock cannot tell the two apart - only its age can.
STALE_IN_FLIGHT_SECONDS = 600


def retry_is_safe(relay_op: str, payload: dict | None) -> bool:
    """Whether a write that may already be in GP can simply be sent again.

    True when the relay recognises the attempt by its key and hands back what the first attempt made:
    every PO registration, and since #1389 every receipt whose stored payload carries the key. A
    receipt queued before the key existed carries none - the outbox replays the STORED payload - so it
    stays an ambiguous failure a person checks in GP. Everything else may duplicate."""
    if relay_op == "create_po":
        return True
    if relay_op == "create_receipt":
        return bool((payload or {}).get("idempotency_key"))
    return False


def recover_in_flight(session: Session, *, older_than_seconds: float = STALE_IN_FLIGHT_SECONDS) -> list[GpWriteOutbox]:
    """Settle rows a stopped worker left IN_FLIGHT (#1192).

    The claim commits IN_FLIGHT before the relay call, so a worker stopped mid-call (every deploy
    restarts it) left the row there for good: cancel and retry refuse IN_FLIGHT, and the per-entity
    guard holds every later write for the same PO behind it. Only a row whose claim (its last update)
    is older than `older_than_seconds` is touched, so a drain still running on another instance is left
    alone; the worker sweeps periodically, so such a row is still recovered once it is truly stuck.

    A row the relay recognises by its key (see `retry_is_safe`: a PO registration, or a keyed receipt)
    goes back on the queue: the relay hands back what the first attempt made, so asking again cannot
    write twice. Anything else may already be in GP and fails as ambiguous for a person to check there.
    Returns the rows it failed, so the caller can tell somebody."""
    rows = list(
        session.scalars(
            select(GpWriteOutbox)
            .where(
                GpWriteOutbox.status == "IN_FLIGHT",
                GpWriteOutbox.updated_at < datetime.utcnow() - timedelta(seconds=older_than_seconds),
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
    )
    failed = []
    for row in rows:
        # #1849: nothing says whether the stopped attempt got as far as GP, so it may have.
        row.maybe_in_gp = True
        if retry_is_safe(row.relay_op, row.payload):
            row.status = "PENDING"
            row.next_attempt_at = datetime.utcnow()
            row.last_error = "The worker stopped while this was being sent; it is asked again"
        else:
            row.status = "FAILED"
            row.failure_kind = "ambiguous"
            row.last_error = (
                "The worker stopped while this was being sent to GP; check GP before retrying, it may already be there"
            )
            row.last_error_code = None
            failed.append(row)
    session.flush()
    return failed


def summary(session: Session, company: str | None = None) -> dict:
    """Scalar aggregates only - this is polled by every browser with the app open, so it must never
    load rows (see the GraphQL/SQLAlchemy performance rules in CLAUDE.md).

    `company` scopes all three counts and every timestamp to one tenant (#729), so the chip a
    scoped user watches counts their own company's held writes. None means every company."""
    scope = [GpWriteOutbox.company == company] if company is not None else []
    counts = dict(
        session.execute(
            select(GpWriteOutbox.status, func.count())
            .where(GpWriteOutbox.status.in_(("PENDING", "IN_FLIGHT", "FAILED")), *scope)
            .group_by(GpWriteOutbox.status)
        ).all()
    )
    oldest_pending_at = session.scalar(
        select(func.min(GpWriteOutbox.created_at)).where(GpWriteOutbox.status == "PENDING", *scope)
    )
    last_drained_at = session.scalar(select(func.max(GpWriteOutbox.succeeded_at)).where(*scope))
    # #1410: any row reaching an end state - a failed or cancelled receipt hands its draft back for
    # review (#1298) - changes data an open page shows, not only a success. updated_at moves on every
    # transition, so over the end states its max is when the queue last settled something.
    last_settled_at = session.scalar(
        select(func.max(GpWriteOutbox.updated_at)).where(
            GpWriteOutbox.status.in_(("SUCCEEDED", "FAILED", "CANCELLED")), *scope
        )
    )
    return {
        "pending": counts.get("PENDING", 0),
        "in_flight": counts.get("IN_FLIGHT", 0),
        "failed": counts.get("FAILED", 0),
        "oldest_pending_at": oldest_pending_at,
        "last_drained_at": last_drained_at,
        "last_settled_at": last_settled_at,
    }


def retry_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    """Admin: put a FAILED row back on the queue immediately, with a fresh attempt budget.

    Locked and re-read (#1193), so the status checked is the one the worker's own locked finish sees."""
    _refuse_while_registration_claimed(session, get_entry(session, entry_id))
    row = get_entry_locked(session, entry_id)
    if row is None or row.status not in ("FAILED", "CANCELLED"):
        return None
    _assert_receive_draft_still_queued(session, row)
    row.status = "PENDING"
    row.attempts = 0
    row.next_attempt_at = datetime.utcnow()
    # maybe_in_gp stays (#1849): a fresh budget does not take back what an earlier attempt may have written.
    row.failure_kind = None
    session.flush()
    return row


def cancel_entry(session: Session, entry_id: uuid.UUID) -> GpWriteOutbox | None:
    """Admin: abandon a queued write. Only a row that is not currently on the wire may be cancelled -
    cancelling an IN_FLIGHT row would leave the worker writing to a row a human believes is dead.
    Locked and re-read (#1193): a plain read let a cancel overwrite a claim that landed in between."""
    row = get_entry_locked(session, entry_id)
    if row is None or row.status not in ("PENDING", "FAILED"):
        return None
    row.status = "CANCELLED"
    session.flush()
    _release_receive_draft(session, row)
    return row


def _refuse_while_registration_claimed(session: Session, row: GpWriteOutbox | None) -> None:
    """#1948: a registration is not put back while a window is registering its PO online. That attempt may
    be finishing this very write from the ledger (#1950), and the queue would save it a second time. The
    PO's row lock is the one the online claim is taken under, taken before the outbox row's, the order
    the queueing takes them in."""
    if row is None or row.op != "register_po_in_gp":
        return
    from app.models.purchase_order import PurchaseOrder
    from app.repositories.po_repository import _registration_claim_is_live

    try:
        po_id = uuid.UUID(row.entity_key.removeprefix("po:"))
    except ValueError:
        return
    po = session.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if po is not None and _registration_claim_is_live(po, datetime.utcnow()):
        raise ConflictError("This PO is being registered in GP from a window right now. Retry this once that finishes.")


def _release_receive_draft(session: Session, row: GpWriteOutbox) -> None:
    """#1298: a queued receipt that ends without reaching GP hands its draft back for review."""
    from app.repositories.warehouse.receive_drafts import release_draft_for_outbox_entry

    release_draft_for_outbox_entry(session, row)


def _assert_receive_draft_still_queued(session: Session, row: GpWriteOutbox) -> None:
    from app.repositories.warehouse.receive_drafts import assert_outbox_entry_retryable

    assert_outbox_entry_retryable(session, row)
