"""Outbound WS channel: the relay dials OUT to the UC Nexus backend at wss://<backend>/relay-link,
authenticates with the enrolled [auth].shared_secret on the connect handshake, and answers job
messages of the shape {id, op, company, payload} with {id, ok, result|error}.

This is a second, additive transport alongside the existing inbound HTTP server (main.py) - nothing
here changes GET /vendors etc. Op handlers call the SAME eConnect functions (and, for create_po /
create_receipt, the same ops.py orchestration) the HTTP routes use, so the GP access path is identical
either way.

Reconnects with exponential backoff on drop. The `websockets` client's default ping_interval=20s /
ping_timeout=20s already satisfies the ~20s keepalive a corporate proxy idle timeout needs, so no
separate ping loop is required here - see ChannelCfg in config.py.
"""

import asyncio
import json

import pyodbc
import websockets
from pydantic import ValidationError as PydanticValidationError

from . import db, econnect, errors, models, ops
from .config import get_settings
from .logging_setup import get_logger

logger = get_logger()


def _run_list_vendors(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_vendors(conn, active_only=payload.get("active_only", True))
    return {"company": company, "vendors": rows}


def _run_list_buyers(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        ids = econnect.list_buyers(conn)
    return {"company": company, "buyers": ids}


def _run_list_cost_codes(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    job = (payload.get("job") or "").strip()
    if not job:
        raise ops.RelayOpError("missing_job", "job is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_cost_codes(conn, job)
    return {"company": company, "job": job, "cost_codes": rows}


def _run_list_jobs(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_jobs(conn)
    return {"company": company, "jobs": rows}


def _run_create_po(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    request = models.CreatePoRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_po_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_create_receipt(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    request = models.ReceiptRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_receipt_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


_OPS = {
    "list_vendors": _run_list_vendors,
    "list_buyers": _run_list_buyers,
    "list_cost_codes": _run_list_cost_codes,
    "list_jobs": _run_list_jobs,
    "create_po": _run_create_po,
    "create_receipt": _run_create_receipt,
}


def _dispatch(op: str, company: str, payload: dict) -> dict:
    """Run one job synchronously (pyodbc is blocking) and return its {ok, result|error} body,
    without the id - _handle_job stitches that back on. Runs on a worker thread via
    asyncio.to_thread so a slow GP call doesn't block the channel's read loop."""
    handler = _OPS.get(op)
    if handler is None:
        return {"ok": False, "error": errors.error_body("unknown_op", f"unknown op {op!r}")}
    if not company:
        return {"ok": False, "error": errors.error_body("missing_company", "company is required")}

    try:
        result = handler(company, payload)
        return {"ok": True, "result": result}
    except ops.RelayOpError as e:
        return {"ok": False, "error": errors.error_body(e.code, e.message, **e.context)}
    except econnect.EConnectError as e:
        # the connection that raised this is already closed by the time we're back here (the `with`
        # block in the handler closed it on the way out), but the description lookup only needs a
        # live connection to run the SELECT - open a fresh read-only one for it.
        try:
            with db.get_read_connection(company) as conn:
                body = errors.econnect_error_body(conn, e)
        except pyodbc.Error:
            body = errors.error_body("econnect_error", str(e), proc=e.proc, error_state=e.error_state)
        return {"ok": False, "error": body}
    except PydanticValidationError as e:
        return {"ok": False, "error": errors.error_body("invalid_payload", str(e))}
    except pyodbc.Error as e:
        return {"ok": False, "error": errors.error_body("sql_error", str(e))}


async def _handle_job(job: dict) -> dict:
    job_id = job.get("id")
    op = job.get("op")
    company = job.get("company")
    payload = job.get("payload") or {}

    try:
        reply = await asyncio.to_thread(_dispatch, op, company, payload)
    except Exception as e:  # last-resort guard: one bad job must never kill the channel loop
        logger.exception("unhandled error dispatching op", extra={"op": op, "id": job_id})
        reply = {"ok": False, "error": errors.error_body("internal_error", str(e))}
    reply["id"] = job_id
    return reply


async def _run_once(url: str, secret: str, cfg) -> None:
    # websockets is pinned to ^13.0 (see pyproject); on 13.x the top-level websockets.connect is the
    # legacy client whose keyword is `extra_headers`. `additional_headers` is the 14.0+ name and raises
    # TypeError on 13.x, which run_forever would swallow and retry forever - the channel would never
    # connect. Keep this as extra_headers until the pin moves to websockets >=14.
    async with websockets.connect(
        url,
        extra_headers={"Authorization": f"Bearer {secret}"},
        ping_interval=cfg.ping_interval,
        ping_timeout=cfg.ping_timeout,
    ) as ws:
        logger.info("channel connected", extra={"url": url})

        # Dispatch each job as its own task so the read loop keeps pulling frames instead of blocking on
        # the current job's GP round-trip (issue #202 #5). The Create-PO page fires list_vendors +
        # list_buyers + list_jobs + list_cost_codes at once; serial handling made later jobs wait behind
        # earlier ones and could push them past the backend's 30s relay_call timeout. Replies are pushed
        # through a single writer coroutine so concurrent jobs never interleave frames on the socket.
        send_queue: asyncio.Queue = asyncio.Queue()
        jobs: set[asyncio.Task] = set()

        async def _writer() -> None:
            while True:
                reply = await send_queue.get()
                try:
                    await ws.send(json.dumps(reply, default=str))
                finally:
                    send_queue.task_done()

        async def _dispatch_job(job: dict) -> None:
            reply = await _handle_job(job)
            await send_queue.put(reply)

        writer_task = asyncio.create_task(_writer())
        try:
            async for raw in ws:
                try:
                    job = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("channel received a non-JSON message", extra={"raw": str(raw)[:200]})
                    continue
                task = asyncio.create_task(_dispatch_job(job))
                jobs.add(task)
                task.add_done_callback(jobs.discard)
        finally:
            writer_task.cancel()
            for task in list(jobs):
                task.cancel()


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Dial the backend channel, reconnecting with exponential backoff on drop. Intended to run as a
    background asyncio task alongside the relay's existing HTTP server (see cli.py). A blank
    [channel].backend_url disables it entirely - the relay just runs the HTTP server, as before."""
    cfg = get_settings().channel
    if not cfg.backend_url:
        logger.info("channel disabled (no [channel] backend_url configured)")
        return

    secret = get_settings().auth.shared_secret
    backoff = cfg.reconnect_min_seconds
    while stop_event is None or not stop_event.is_set():
        try:
            await _run_once(cfg.backend_url, secret, cfg)
            backoff = cfg.reconnect_min_seconds  # clean run - reset backoff before the next attempt
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("channel connection dropped, retrying", extra={"error": str(e), "backoff": backoff})
            backoff = min(backoff * 2, cfg.reconnect_max_seconds)
        await asyncio.sleep(backoff)
