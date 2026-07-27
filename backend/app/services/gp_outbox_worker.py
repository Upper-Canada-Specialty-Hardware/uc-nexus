"""Background drainer for the GP write outbox (#353 PR E).

Runs as a single asyncio task started from the FastAPI lifespan. Per row it runs the SAME pipeline
the online resolver runs - idempotency short-circuit, relay_call, record the relay result in its own
commit, persist - by rehydrating `persist_context` and calling the very `_persist_*` helper the
resolver calls. There is deliberately no second persist implementation to drift.

The handler imports those helpers INSIDE the function body: `app.schemas.*` imports services, so a
module-level import here would create a services <-> schemas cycle."""

import asyncio
import logging
import os
import uuid
from collections.abc import Callable

from app.database import SessionLocal
from app.errors import (
    AppError,
    RelayCallError,
    RelayOpUnsupportedError,
    RelayTimeoutError,
    RelayUnavailableError,
)
from app.repositories import gp_outbox_repository
from app.services import gp_idempotency
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0

_wake_event: asyncio.Event | None = None


def enabled() -> bool:
    """Env kill switch, default on, so the worker can be stopped without a code deploy."""
    return os.getenv("GP_OUTBOX_ENABLED", "true").lower() not in ("false", "0", "no")


def wake() -> None:
    """Nudge the loop out of its sleep. Called by /relay-link right after a successful try_register,
    so a reconnect drains within milliseconds instead of up to POLL_SECONDS later."""
    if _wake_event is not None:
        try:
            _wake_event.set()
        except Exception:  # noqa: BLE001 - never let a wake-up break the caller's request path
            logger.exception("gp outbox: failed to signal the worker")


def _persist_register_po_from_context(context: dict, relay_result: dict, key: str) -> None:
    from app.schemas.po import _persist_register_po

    _persist_register_po(
        key=key,
        po_id=uuid.UUID(context["po_id"]),
        gp_vendor_id=context["gp_vendor_id"],
        vendor_name_snapshot=context.get("vendor_name_snapshot"),
        gp_result=relay_result,
        line_items_data=context["line_items_data"],
        vendor_id=uuid.UUID(context["vendor_id"]) if context.get("vendor_id") else None,
        cost_code=context.get("cost_code"),
        buyer_id=context.get("buyer_id"),
        shipping_cost=context.get("shipping_cost"),
        tariff_amount=context.get("tariff_amount"),
        # #316. .get() so rows queued before this key existed replay as "no project override", which is
        # the pre-#316 behaviour.
        project_id=uuid.UUID(context["project_id"]) if context.get("project_id") else None,
    )


def _persist_create_receive_from_context(context: dict, relay_result: dict, key: str) -> None:
    from app.schemas.warehouse import _persist_create_receive

    line_items_data = [
        {
            "po_line_item_id": uuid.UUID(li["po_line_item_id"]),
            "quantity_received": li["quantity_received"],
            "locations": li["locations"],
        }
        for li in context["line_items_data"]
    ]
    _persist_create_receive(
        key=key,
        po_id=uuid.UUID(context["po_id"]),
        received_by=context["received_by"],
        line_items_data=line_items_data,
        warehouse_id=uuid.UUID(context["warehouse_id"]) if context.get("warehouse_id") else None,
        relay_result=relay_result,
    )


# op -> adapter. The adapters return the resolver's Strawberry DTO; the worker discards it.
_HANDLERS: dict[str, Callable[[dict, dict, str], None]] = {
    "register_po_in_gp": _persist_register_po_from_context,
    "create_receive": _persist_create_receive_from_context,
}


def _notify_failure(row_id: uuid.UUID) -> None:
    """Tell somebody a queued GP write has died for good.

    `Notification.project_id` is NOT NULL, so a row without a project (a PO with no project attached)
    gets no notification - deliberately, because inventing a placeholder project would put the signal
    in front of the wrong people. Those rows are still visible in the queue UI and still counted on
    the failed chip, which is the backstop."""
    from app.models.enums import NotificationType
    from app.services import notification_service

    with SessionLocal() as session:
        row = gp_outbox_repository.get_entry(session, row_id)
        if row is None or row.project_id is None:
            return
        recipient = (
            notification_service.PO_RECIPIENT_ROLE
            if row.op == "register_po_in_gp"
            else notification_service.WAREHOUSE_RECIPIENT_ROLE
        )
        notification_service.create_notification(
            session,
            project_id=row.project_id,
            recipient_role=recipient,
            notification_type=NotificationType.GP_WRITE_FAILED,
            message=f"{row.label} could not be posted to GP: {row.last_error or 'unknown error'}",
        )
        session.commit()


def _load_row(row_id: uuid.UUID):
    with SessionLocal() as session:
        return gp_outbox_repository.get_entry(session, row_id)


def _finish(row_id: uuid.UUID, action: str, **kwargs) -> None:
    with SessionLocal() as session:
        row = gp_outbox_repository.get_entry(session, row_id)
        if row is None:
            return
        getattr(gp_outbox_repository, action)(session, row, **kwargs)
        session.commit()


async def _drain_one(row_id: uuid.UUID) -> None:
    """Run one claimed row all the way through, and record where it got to.

    Mirrors the resolver exactly: a ledger that already holds `result_id` means the whole thing was
    finished by someone else, and a ledger that already holds `relay_result` means GP has ALREADY
    run - reusing it rather than calling again is what stops a queued retry from double-posting."""
    row = await asyncio.to_thread(_load_row, row_id)
    if row is None:
        return
    key, op, relay_op, company = row.idempotency_key, row.op, row.relay_op, row.company
    payload, context, label = row.payload, row.persist_context, row.label

    state = await asyncio.to_thread(gp_idempotency.load, key)
    if state is not None and state.result_id is not None:
        await asyncio.to_thread(_finish, row_id, "mark_succeeded")
        return

    try:
        if state is not None and state.relay_result is not None:
            relay_result = state.relay_result
        else:
            relay_result = await relay_gateway.relay_call(company, relay_op, payload)
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, op, relay_result)
    except RelayUnavailableError as e:
        if e.dispatched:
            # The job was on the wire when the socket died: GP may hold the write. Retrying could
            # duplicate it, so this needs a human who can look in GP.
            await asyncio.to_thread(
                _finish, row_id, "mark_failed", kind="ambiguous", error=str(e.message), error_code=e.code
            )
            await asyncio.to_thread(_notify_failure, row_id)
            return
        # Relay simply not there. Deliberately does NOT count against the attempt budget: a week-long
        # outage must not poison the queue.
        await asyncio.to_thread(
            _finish,
            row_id,
            "mark_retry",
            error=str(e.message),
            error_code=e.code,
            bump_attempts=False,
            retry_in_seconds=POLL_SECONDS,
        )
        return
    except RelayTimeoutError as e:
        # Same ambiguity as a dispatched disconnect - the job reached the relay and we do not know
        # what GP did with it.
        await asyncio.to_thread(
            _finish, row_id, "mark_failed", kind="ambiguous", error=str(e.message), error_code=e.code
        )
        await asyncio.to_thread(_notify_failure, row_id)
        return
    except RelayOpUnsupportedError as e:
        # The relay is too old for this op. Retryable: PR D's auto-update poller will fix it.
        await asyncio.to_thread(
            _finish, row_id, "mark_retry", error=str(e.message), error_code=e.code, bump_attempts=True
        )
        await _fail_if_exhausted(row_id)
        return
    except RelayCallError as e:
        # GP itself said no. Deterministic - retrying never helps.
        await asyncio.to_thread(
            _finish, row_id, "mark_failed", kind="gp_rejected", error=str(e.message), error_code=e.code
        )
        await asyncio.to_thread(_notify_failure, row_id)
        return

    handler = _HANDLERS.get(op)
    if handler is None:
        await asyncio.to_thread(
            _finish, row_id, "mark_failed", kind="persist_failed", error=f"unknown outbox op {op!r}"
        )
        return

    try:
        await asyncio.to_thread(handler, context, relay_result, key)
    except AppError as e:
        # GP has already committed but the UC Nexus side will not take it (the PO left DRAFT, the
        # receive is no longer eligible, ...). No retry can fix a state disagreement; a human must.
        logger.exception("gp outbox: persist failed after GP committed", extra={"label": label})
        await asyncio.to_thread(
            _finish, row_id, "mark_failed", kind="persist_failed", error=str(e.message), error_code=e.code
        )
        await asyncio.to_thread(_notify_failure, row_id)
        return
    except Exception as e:  # noqa: BLE001 - a transient DB error should come back around
        logger.exception("gp outbox: persist raised; will retry", extra={"label": label})
        await asyncio.to_thread(_finish, row_id, "mark_retry", error=str(e), bump_attempts=True)
        await _fail_if_exhausted(row_id)
        return

    await asyncio.to_thread(_finish, row_id, "mark_succeeded")
    logger.info("gp outbox: drained", extra={"label": label, "op": op})


async def _fail_if_exhausted(row_id: uuid.UUID) -> None:
    row = await asyncio.to_thread(_load_row, row_id)
    if row is None or row.attempts <= gp_outbox_repository.MAX_ATTEMPTS:
        return
    await asyncio.to_thread(
        _finish,
        row_id,
        "mark_failed",
        kind="exhausted",
        error=row.last_error or "retry budget exhausted",
        error_code=row.last_error_code,
    )
    await asyncio.to_thread(_notify_failure, row_id)


def _claim(company: str) -> uuid.UUID | None:
    with SessionLocal() as session:
        row = gp_outbox_repository.claim_next(session, company)
        row_id = row.id if row is not None else None
        session.commit()
    return row_id


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it - a dead worker is a
    silently non-draining queue, which is worse than the failure it is trying to absorb."""
    global _wake_event
    _wake_event = asyncio.Event()
    logger.info("gp outbox worker started")
    while True:
        try:
            # No relay, or a relay for another company: nothing claimable, so do not even open a
            # transaction. This is the steady state during an outage and must be cheap.
            company = relay_gateway.company if relay_gateway.connected else None
            if company is not None:
                row_id = await asyncio.to_thread(_claim, company)
                if row_id is not None:
                    await _drain_one(row_id)
                    continue  # keep draining while there is work
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("gp outbox worker iteration failed")

        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass
        finally:
            _wake_event.clear()
