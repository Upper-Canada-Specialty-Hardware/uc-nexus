"""Outbound WS channels: the relay dials OUT to a UC Nexus backend at wss://<backend>/relay-link,
authenticates with the enrolled [auth].shared_secret on the connect handshake, and answers job
messages of the shape {id, op, company, payload} with {id, ok, result|error}. It also answers the
backend's application-level heartbeat - a {"type": "ping"} control message - with {"type": "pong"}
(issue #277).

There can be MORE THAN ONE backend (issue #414). A Railway PR environment cannot exercise any
relay-dependent path unless a relay dials it, and the relay only ever had one URL - so verifying a
GP-touching change meant re-pointing the workstation, which un-pairs it from production. `run_forever`
now supervises one independent reconnecting channel per configured URL, and production's connection is
never dropped to test a PR. The same enrolled secret authenticates on all of them (the backend matches
on its hash, and a PR environment is seeded with that hash rather than issued a credential of its own).

Which backend a channel points at decides what it may reach: the production URL is unrestricted, every
other URL is pinned to the sandbox company (config.NON_PRIMARY_ALLOWED_COMPANIES). Reads and writes
are both served on a test channel - a PR that touches GP has to be verifiable before it merges - and
that company pin is the sole reason it is safe, so `_dispatch` enforces it before any handler runs.

This is a second, additive transport alongside the existing inbound HTTP server (main.py) - nothing
here changes GET /vendors etc. Op handlers call the SAME eConnect functions (and, for create_po /
create_receipt, the same ops.py orchestration) the HTTP routes use, so the GP access path is identical
either way.

Reconnects with exponential backoff on drop. The `websockets` client's default ping_interval=20s /
ping_timeout=20s already satisfies the ~20s keepalive a corporate proxy idle timeout needs, so no
separate ping loop is required here - see ChannelCfg in config.py. That WS-protocol ping is distinct
from the backend's data-message heartbeat above: the protocol ping keeps a corporate proxy from idling
the socket, while answering the data heartbeat lets the backend reap a dead relay from its registry
within ~a minute (issue #277) - the websockets client auto-answers protocol pings but not data pings.
"""

import asyncio
import json
import logging
import time

import pyodbc
import websockets
from pydantic import ValidationError as PydanticValidationError

from . import __version__ as VERSION
from . import db, econnect, errors, models, ops
from .config import (
    PRODUCTION_BACKEND_URL,
    channel_allowed_companies,
    get_settings,
    is_primary_backend_url,
    primary_url,
)
from .logging_setup import get_logger

logger = get_logger()

# Live channel state PER backend URL, updated by _run_channel and exposed on /health, so the desktop
# app shows the REAL backend-channel status instead of inferring it from relay.log (a killed serve
# never writes a clean disconnect line, so the log's last event goes stale). `state` mirrors
# _classify_connect_failure. Keyed by URL and insertion-ordered, so it reads in configured order.
_STATES: dict[str, dict] = {}

_UNKNOWN_STATE = {"connected": False, "state": "unknown"}

# GP jobs currently being dispatched, and when the last one finished. The `jobs` task set below is
# per-connection and lives in the SERVE child; the auto-update poller lives in the desktop app PARENT
# and has no way to see it. These module-level counters ride out on /health (the parent already polls
# it) so the poller can refuse to swap the exe out from under an in-flight GP write. Deliberately
# global rather than per-channel: the poller's question is "is ANY GP write in flight right now", and
# a job from a PR-environment channel is just as real a GP write as one from production.
_INFLIGHT = 0
_LAST_JOB_AT: float | None = None


def channel_state_snapshot() -> dict:
    """The channel view /health publishes.

    The TOP LEVEL keys stay exactly what they were before multi-channel (#414) and mirror the PRIMARY
    channel: the desktop app's status tab and the update poller both read `connected` / `state` there,
    and neither should start reporting on a throwaway PR-environment channel. `channels` carries the
    per-URL detail for the app to render when more than one is configured. With no primary configured
    (a dev checkout pointed at localhost) the first channel stands in, so the app is never blank."""
    # Copy the mapping ONCE before walking it. /health is a sync def, so Starlette runs it on a
    # threadpool worker while the event loop keeps running - and a channel's first _mark_* call INSERTS
    # a key. Iterating _STATES directly could then raise "dictionary changed size during iteration",
    # which surfaces as /health 500 -> the desktop app reporting the relay "not running" and the update
    # poller deferring forever. list(dict.items()) takes no Python-level callbacks, so it cannot
    # interleave. (register_channels pre-seeds the keys too, so in practice this is belt and braces.)
    states = list(_STATES.items())
    urls = [url for url, _ in states]
    chosen = primary_url(urls)
    snapshot = dict(dict(states).get(chosen, _UNKNOWN_STATE) if chosen else _UNKNOWN_STATE)
    snapshot["jobs_in_flight"] = _INFLIGHT
    snapshot["last_job_finished_ago"] = None if _LAST_JOB_AT is None else time.monotonic() - _LAST_JOB_AT
    snapshot["channels"] = [{"url": url, "primary": is_primary_backend_url(url), **state} for url, state in states]
    return snapshot


def register_channels(urls: list[str]) -> None:
    """Pre-seed a state row per configured URL, before any of them dials. Two reasons: the desktop
    app's panel can then list every channel from the first poll instead of only those that have already
    attempted a connection (an operator who just added a PR URL would otherwise see no sign of it), and
    the key set stops changing under channel_state_snapshot once startup is done."""
    for url in urls:
        _STATES.setdefault(url, dict(_UNKNOWN_STATE))


def _mark_connected(url: str) -> None:
    _STATES.setdefault(url, {}).update(connected=True, state="connected")


def _mark_disconnected(url: str, state: str = "disconnected") -> None:
    _STATES.setdefault(url, {}).update(connected=False, state=state)


# WS close code the backend sends when a second relay connects while one already holds the single
# connection slot (backend/main.py: try_register -> close(4409)). It arrives AFTER accept(), so the
# client sees it as a close frame - distinct from a secret rejection, which is refused pre-accept.
_SLOT_BUSY_CLOSE_CODE = 4409

# RFC 6455 1012 "Service Restart", sent by the backend's graceful shutdown (#353 PR F). It means the
# backend is coming straight back, so growing the reconnect backoff is exactly wrong - the socket
# should be re-established immediately rather than after up to reconnect_max_seconds of waiting.
_SERVICE_RESTART_CLOSE_CODE = 1012


def _classify_connect_failure(exc: Exception) -> tuple[str, str]:
    """Map a failed/dropped channel connection to a (category, operator_message) so the log says WHY,
    not just "retrying" (issue #204).

    The backend refuses a bad or orphaned secret BEFORE accepting the socket (authenticate_secret ->
    close(4401) before websocket.accept()), which the websockets client sees as an HTTP 403 at the
    handshake (InvalidStatusCode.status_code == 403), NOT a WS close frame - that means this relay's
    enrolled secret no longer matches any relay_installs row and it needs re-enrollment (e.g. after a
    dev DB wipe). A VALID secret that loses the single-connection race is accepted and then closed with
    code 4409. Everything else (network drop, backend restart, proxy idle close) is a transient retry.

    Attribute-based on purpose: robust across websockets versions, and unit-testable with the real
    exception types without a live socket."""
    status = getattr(exc, "status_code", None)  # websockets InvalidStatusCode: handshake was rejected
    if status in (401, 403):
        return (
            "secret_rejected",
            "backend rejected the relay secret - this relay likely needs re-enrollment: provision a new "
            "token in UC Nexus admin, then re-run `ucnexus-relay enroll`. the new secret is picked up "
            "automatically on the next reconnect - no restart required. still retrying.",
        )
    rcvd = getattr(exc, "rcvd", None)  # websockets ConnectionClosed: the close frame we received
    close_code = getattr(rcvd, "code", None) if rcvd is not None else getattr(exc, "code", None)
    if close_code == _SLOT_BUSY_CLOSE_CODE:
        return (
            "slot_busy",
            "another relay already holds the backend connection for this company; standing by. still retrying.",
        )
    if close_code == _SERVICE_RESTART_CLOSE_CODE:
        return ("server_restarting", "backend is restarting; reconnecting immediately")
    return ("dropped", "channel connection dropped, retrying")


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


def _run_list_buyers_detailed(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_buyers_detailed(conn)
    return models.BuyersDetailedResponse(company=company, buyers=rows).model_dump(mode="json")


def _run_create_buyer(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    request = models.CreateBuyerRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_buyer_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_list_tax_details(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_tax_details(conn)
    return {"company": company, "tax_details": rows}


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


def _run_job_setup_health(company: str, payload: dict) -> dict:
    """Read-only GP setup verdict per job (#425). The optional `job` filter narrows it to one job for
    the live re-check register_po_in_gp runs at submit time; without it this answers for every job in
    the company, which is what the backend's sync pass stamps onto projects.

    Unlike _run_list_cost_codes there is no missing_job error: a blank job is not a mistake here, it
    is the whole-company sweep."""
    ops.check_company_allowed(company)
    job = (payload.get("job") or "").strip() or None
    with db.get_read_connection(company) as conn:
        jobs = econnect.job_setup_health(conn, job)
    return models.JobSetupHealthResponse(company=company, job=job, jobs=jobs).model_dump(mode="json")


def _run_read_po_totals(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    po_number = (payload.get("po_number") or "").strip()
    if not po_number:
        raise ops.RelayOpError("missing_po_number", "po_number is required")
    with db.get_read_connection(company) as conn:
        totals = econnect.read_po_totals(conn, po_number)
    return {"company": company, "totals": totals}


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


def _run_list_customers(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_customers(conn)
    return {"company": company, "customers": rows}


def _run_list_customer_addresses(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    customer = (payload.get("customer") or "").strip()
    if not customer:
        raise ops.RelayOpError("missing_customer", "customer is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_customer_addresses(conn, customer)
    return {"company": company, "customer": customer, "addresses": rows}


def _run_list_tax_schedules(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_tax_schedules(conn)
    return {"company": company, "tax_schedules": rows}


def _run_list_employees(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        # active_only is forwarded (like _run_list_vendors): the proc validates the estimator against
        # the whole of UPR00100, not just its active rows, so backdating or recreating a job whose
        # estimator has since been deactivated has to remain expressible.
        rows = econnect.list_employees(conn, active_only=payload.get("active_only", True))
    # Built through the response model rather than returned as a loose dict, so EmployeesResponse is
    # the enforced description of this op's wire shape instead of a second one that can silently drift.
    return models.EmployeesResponse(company=company, employees=rows).model_dump(mode="json")


def _run_list_divisions(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_divisions(conn)
    return {"company": company, "divisions": rows}


def _run_create_job(company: str, payload: dict) -> dict:
    ops.check_company_allowed(company)
    request = models.CreateJobRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_job_op(conn, company=company, request=request)
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
    "list_tax_details": _run_list_tax_details,
    "list_cost_codes": _run_list_cost_codes,
    "list_jobs": _run_list_jobs,
    "read_po_totals": _run_read_po_totals,
    "create_po": _run_create_po,
    "create_receipt": _run_create_receipt,
    # issue #380 - the create-job form's live reads, and the create itself.
    "list_customers": _run_list_customers,
    "list_customer_addresses": _run_list_customer_addresses,
    "list_tax_schedules": _run_list_tax_schedules,
    "list_divisions": _run_list_divisions,
    "create_job": _run_create_job,
    # issue #392 - estimator / WS manager are validated against the payroll master, so they need a
    # picker rather than free text.
    "list_employees": _run_list_employees,
    # issue #409 - the admin buyer screens: the buyer master with descriptions, and registering a new
    # buyer so linking a Nexus account to a GP buyer identity never needs GP opened.
    "list_buyers_detailed": _run_list_buyers_detailed,
    "create_buyer": _run_create_buyer,
    # issue #425 - jobs replicated from UCSH carry GL account indexes that do not exist in UBC, so a
    # PO against them registers and can never be received. This is how Nexus finds out which ones.
    "job_setup_health": _run_job_setup_health,
}


def _dispatch(op: str, company: str, payload: dict, allowed_companies: list[str] | None = None) -> dict:
    """Run one job synchronously (pyodbc is blocking) and return its {ok, result|error} body,
    without the id - _handle_job stitches that back on. Runs on a worker thread via
    asyncio.to_thread so a slow GP call doesn't block the channel's read loop.

    `allowed_companies` is the CHANNEL's restriction (#414): None for the production channel, which is
    governed by [gp] allowed_companies alone as it always has been, and the sandbox list for any other
    backend. Non-production channels get full read AND write access - a PR that touches GP has to be
    verifiable before it merges - and this is the sole thing keeping that safe, so it is checked before
    any handler runs. It layers on top of ops.check_company_allowed rather than replacing it: that one
    is the workstation's own guardrail against production GP companies and still applies."""
    handler = _OPS.get(op)
    if handler is None:
        return {"ok": False, "error": errors.error_body("unknown_op", f"unknown op {op!r}")}
    if not company:
        return {"ok": False, "error": errors.error_body("missing_company", "company is required")}
    if allowed_companies is not None and company not in allowed_companies:
        return {
            "ok": False,
            "error": errors.error_body(
                "company_not_allowed_on_channel",
                # Joined, not interpolated as a list: relay_gateway raises RelayCallError(error
                # ["message"]), so this string is what the browser shows - "only ['TUBC']" would leak a
                # Python repr into the UI.
                f"{company} is not reachable from a non-production backend; only {', '.join(allowed_companies)} is",
                company=company,
                allowed=list(allowed_companies),
            ),
        }

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


async def _handle_job(job: dict, allowed_companies: list[str] | None = None) -> dict:
    job_id = job.get("id")
    op = job.get("op")
    company = job.get("company")
    payload = job.get("payload") or {}

    try:
        reply = await asyncio.to_thread(_dispatch, op, company, payload, allowed_companies)
    except Exception as e:  # last-resort guard: one bad job must never kill the channel loop
        logger.exception("unhandled error dispatching op", extra={"op": op, "id": job_id})
        reply = {"ok": False, "error": errors.error_body("internal_error", str(e))}
    reply["id"] = job_id
    return reply


def _heartbeat_reply(message: object) -> dict | None:
    """The pong to send for the backend's application-level heartbeat ping (issue #277), or None if
    `message` is a normal job to dispatch. ASGI can't send a WS ping frame, so the backend pings on a
    data message; the relay answers it here (the websockets client auto-answers only protocol pings)."""
    if isinstance(message, dict) and message.get("type") == "ping":
        return {"type": "pong"}
    return None


def _hello_frame() -> dict:
    """The relay's identity frame, sent once right after the channel connects (issue #315). It carries
    the build tag and the exact op-set this relay supports so the backend can reject a call for an op this
    build lacks with a clear 'update the relay' error - proactively, and without a 30s round-trip - and
    show the live build on Admin -> Relay Installs. `updater.current_build()` is 'dev' for a source
    checkout, which is fine: the backend only compares the op-set, and reports the build verbatim."""
    from . import updater  # lazy: keep channel import-light and avoid any package load-order coupling

    return {"type": "hello", "build": updater.current_build(), "ops": sorted(_OPS), "version": VERSION}


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
        # What this channel may target: None for production, the sandbox list for any other backend
        # (#414). Resolved once per connection rather than per job - it is a property of the URL.
        allowed_companies = channel_allowed_companies(url)
        logger.info("channel connected", extra={"url": url, "restricted_to": allowed_companies})
        _mark_connected(url)

        # Advertise this relay's build + op-set to the backend before anything else (issue #315). Sent
        # directly here, ahead of the writer coroutine below, so it's the first frame on the wire - the
        # backend records it and can then reject calls for ops this build lacks with a clear error.
        await ws.send(json.dumps(_hello_frame()))

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
            # try/finally so a crashing or cancelled job cannot leak the counter: a stuck _INFLIGHT
            # would wedge the update poller into deferring forever, which looks exactly like "updates
            # silently stopped working".
            global _INFLIGHT, _LAST_JOB_AT
            _INFLIGHT += 1
            try:
                reply = await _handle_job(job, allowed_companies)
                await send_queue.put(reply)
            finally:
                _INFLIGHT -= 1
                _LAST_JOB_AT = time.monotonic()

        writer_task = asyncio.create_task(_writer())
        try:
            async for raw in ws:
                try:
                    job = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    logger.warning("channel received a non-JSON message", extra={"raw": str(raw)[:200]})
                    continue
                pong = _heartbeat_reply(job)
                if pong is not None:
                    # Backend heartbeat (issue #277): answer through the same writer queue so the pong
                    # never interleaves mid-frame with a job reply, and don't dispatch it as a job.
                    await send_queue.put(pong)
                    continue
                task = asyncio.create_task(_dispatch_job(job))
                jobs.add(task)
                task.add_done_callback(jobs.discard)
        finally:
            writer_task.cancel()
            for task in list(jobs):
                task.cancel()


async def _run_channel(url: str, stop_event: asyncio.Event | None = None) -> None:
    """Hold ONE backend channel up: dial it, then reconnect with exponential backoff on drop. Backoff
    and failure classification are per-channel, so a dead PR environment retrying at its ceiling has
    no effect on how fast production reconnects."""
    primary = is_primary_backend_url(url)
    settings = get_settings()
    backoff = settings.channel.reconnect_min_seconds
    prev_category: str | None = None
    while stop_event is None or not stop_event.is_set():
        # Re-read config on EVERY attempt, dropping the lru_cache first. Reading the secret once before
        # the loop meant a re-enrolment could never take effect in a running process: `enroll` rewrites
        # [auth] shared_secret in config.toml, but this task kept dialling with the stale value forever,
        # so the backend 403'd every handshake until someone restarted the service by hand - on a
        # workstation that may be nowhere near whoever is debugging. Now a re-enrolment self-heals on
        # the next retry. Cost is one small TOML parse per reconnect attempt.
        #
        # Guarded, and keeping the last good Settings on failure: hand-editing config.toml on a running
        # relay is the documented way to add a test backend (#414), so a save caught mid-write or a
        # missing bracket is a live possibility. Letting that raise here - outside the try below - would
        # kill this channel task outright, production's included, and no amount of fixing the file would
        # bring it back without a serve restart.
        try:
            get_settings.cache_clear()
            settings = get_settings()
        except Exception as e:
            logger.warning(
                "could not re-read config.toml; retrying with the last good settings",
                extra={"category": "config_unreadable", "error": str(e), "url": url},
            )
        secret = settings.auth.shared_secret
        cfg = settings.channel
        try:
            await _run_once(url, secret, cfg)
            backoff = cfg.reconnect_min_seconds  # clean run - reset backoff before the next attempt
            prev_category = None
            _mark_disconnected(url)  # _run_once returned -> socket closed; reconnecting on the next loop
        except asyncio.CancelledError:
            raise
        except Exception as e:
            category, message = _classify_connect_failure(e)
            # A rejected/orphaned secret can't self-heal until someone re-enrols, so a de-enrolled relay
            # would otherwise log the same WARNING every ~30s forever. Log it loudly once on the
            # transition into that state, then at DEBUG. Transient drops and slot-busy stay at WARNING -
            # each is a real, distinct reconnect event. (The re-enrolment itself is now picked up
            # automatically at the top of this loop; no restart needed.)
            #
            # A NON-PRIMARY channel demotes EVERY repeated category, not just secret_rejected (#414): a
            # PR environment gets torn down when its PR closes, and the URL then sits in config.toml
            # failing forever. That must not bury production's own reconnect events in the same log.
            quiet_repeat = category == prev_category and (not primary or category == "secret_rejected")
            logger.log(
                logging.DEBUG if quiet_repeat else logging.WARNING,
                message,
                extra={"category": category, "error": str(e), "backoff": backoff, "url": url},
            )
            _mark_disconnected(url, category if category in ("secret_rejected", "slot_busy") else "disconnected")
            if category == "server_restarting":
                # A deploy, not a fault: the backend told us it is coming straight back, so dial again
                # at the minimum interval rather than growing the backoff and sitting out the first
                # half-minute of the new deployment (#353 PR F).
                backoff = cfg.reconnect_min_seconds
            else:
                backoff = min(backoff * 2, cfg.reconnect_max_seconds)
            prev_category = category
        await asyncio.sleep(backoff)


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Supervise one reconnecting channel per configured backend URL. Intended to run as a single
    background asyncio task alongside the relay's existing HTTP server (see cli.py); an empty
    [channel].backend_url disables it entirely - the relay just runs the HTTP server, as before.

    The URL LIST is read once, here, and a change to it takes effect on the next serve restart (the
    desktop app's Restart Relay button). That is deliberately unlike the secret, which is re-read on
    every reconnect: a re-enrolment has to self-heal a relay nobody can walk over to, whereas adding a
    PR environment is something the person editing config.toml is already standing at the machine for.
    Spawning and reaping channel tasks on every retry to avoid one restart is not worth the machinery."""
    urls = get_settings().channel.backend_urls
    if not urls:
        logger.info("channel disabled (no [channel] backend_url configured)")
        return

    if not any(is_primary_backend_url(url) for url in urls):
        # Loud, because the likeliest cause is a typo in a hand-added backend_url list rather than a
        # deliberate choice: production is then just another restricted channel and every real UBC/UCSH
        # job is refused with company_not_allowed_on_channel. A dev checkout pointed at localhost hits
        # this legitimately, which is why it warns rather than refusing to start.
        logger.warning(
            "no production channel configured - EVERY channel is restricted to the sandbox company. "
            "if this is a workstation, check [channel] backend_url matches the production URL exactly, "
            "or list only the extra backend under [channel] extra_backend_urls and leave backend_url alone.",
            extra={"category": "no_primary_channel", "urls": urls, "expected": PRODUCTION_BACKEND_URL},
        )

    logger.info("starting backend channels", extra={"urls": urls})
    register_channels(urls)  # so /health lists every channel from the first poll, before any dials

    async def _supervised(url: str) -> None:
        """Log a channel that escapes its own retry loop. _run_channel is not supposed to - it catches
        Exception per attempt - but if it ever does, the log has to happen HERE. Doing it from the
        gather() below cannot work: gather returns only once EVERY awaitable is done, and the siblings
        loop forever, so an aggregated result is never reached and a dead channel would be visible
        only as a stale 'disconnected' on /health with nothing in relay.log."""
        try:
            await _run_channel(url, stop_event)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "backend channel exited unexpectedly and will not reconnect until serve restarts",
                extra={"category": "channel_died", "url": url},
            )
            _mark_disconnected(url, "failed")

    tasks = [asyncio.create_task(_supervised(url), name=f"channel:{url}") for url in urls]
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        # Reap them rather than just cancelling: cli.py cancels THIS task on shutdown, and a bare
        # cancel() would leave the children pending as the loop closes ("Task was destroyed but it is
        # pending"). CancelledError is a BaseException, so a cancelled child is not logged above.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
