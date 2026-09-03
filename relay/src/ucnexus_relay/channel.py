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

That set is reconciled against config.toml on a tick rather than read once (issue #456), so adding or
removing a preview environment needs no restart - see `run_forever` for why that mattered enough to
build. The preview URLs themselves are not written there at all any more: PRODUCTION pushes the current
list down the socket it already holds, as a {"type": "channels"} frame, and the relay unions it with
whatever config.toml names (see `_handle_channels_frame`). Nothing on the workstation is edited when a
PR opens or closes.

Which backend a channel points at decides what it may reach: the production URL is unrestricted, every
other URL is pinned to the sandbox companies (config.NON_PRIMARY_ALLOWED_COMPANIES). Reads and writes
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
import hashlib
import json
import logging
import re
import time

import pyodbc
import websockets
from pydantic import ValidationError as PydanticValidationError

from . import __version__ as VERSION
from . import companies, db, econnect, errors, models, ops, server_load
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


def forget_channel(url: str) -> None:
    """Drop a channel's state row, once its URL has left config.toml and its task is reaped (#456).

    Without this a torn-down PR environment would keep its row on /health forever, so the desktop
    app's channel panel would go on listing a backend nobody is dialling any more - which reads as a
    broken connection rather than a removed one."""
    _STATES.pop(url, None)


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
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_vendors(conn, active_only=payload.get("active_only", True))
    return {"company": company, "vendors": rows}


def _run_get_vendor_contact(company: str, payload: dict) -> dict:
    """#500: the vendor's email and contact name, so Nexus can send them their PO. Read-only, and
    the only reason vendor contact details are reachable at all - GP owns them (#509), Nexus keeps
    none of its own."""
    ops.check_company_served(company)
    vendor_id = (payload.get("vendor_id") or "").strip()
    if not vendor_id:
        raise ops.RelayOpError("invalid_payload", "vendor_id is required")
    with db.get_read_connection(company) as conn:
        contact = econnect.get_vendor_contact(conn, vendor_id)
    if contact is None:
        raise ops.RelayOpError(
            "vendor_not_found", f"Vendor '{vendor_id}' does not exist in {company}", vendor_id=vendor_id
        )
    return {"company": company, **contact}


def _run_list_buyers(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        ids = econnect.list_buyers(conn)
    return {"company": company, "buyers": ids}


def _run_list_buyers_detailed(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_buyers_detailed(conn)
    return models.BuyersDetailedResponse(company=company, buyers=rows).model_dump(mode="json")


def _run_create_buyer(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
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
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_tax_details(conn)
    return {"company": company, "tax_details": rows}


def _run_list_cost_codes(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    job = (payload.get("job") or "").strip()
    if not job:
        raise ops.RelayOpError("missing_job", "job is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_cost_codes(conn, job)
    return {"company": company, "job": job, "cost_codes": rows}


def _run_list_cost_code_master(company: str, payload: dict) -> dict:
    """The company's cost-code master, scoped to one division (#448) - what the create-project dialog
    offers when it asks which cost codes the new job should get.

    Division-scoped for the same reason _run_list_cost_codes is job-scoped: it is not a filter on the
    list, it is what decides the GL account each code would be provisioned with (JC40302 maps
    (Divisions, Cost_Element) -> ACTINDX), so answering without one would return codes with no account
    at all. A missing or blank division answers missing_division, exactly as the job read answers
    missing_job."""
    ops.check_company_served(company)
    division = (payload.get("division") or "").strip()
    if not division:
        raise ops.RelayOpError("missing_division", "division is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_cost_code_master(conn, division)
    return {"company": company, "division": division, "cost_codes": rows}


def _run_list_jobs(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_jobs(conn)
    return {"company": company, "jobs": rows}


def _run_job_setup_health(company: str, payload: dict) -> dict:
    """Read-only GP setup verdict per job (#425), in one of three widths.

    `jobs` (a list) is the batch the adoption pass walks the job master in, charged to its read budget
    at the batch's length. It wins over everything else when it holds anything: without it a batched
    backend would re-read the WHOLE company once per batch, which is worse than the single sweep it
    replaced. `job` (one number) is the live re-check register_po_in_gp runs at submit time. Neither
    is the whole-company sweep, which is what a backend too old to send either still gets.

    An explicitly empty `jobs` reads nothing and opens no connection - the caller named no jobs, so
    there is nothing to ask GP. Unlike _run_list_cost_codes there is no missing_job error: a blank job
    is not a mistake here, it is the sweep."""
    ops.check_company_served(company)
    if "jobs" in payload:
        asked = payload.get("jobs")
        if not isinstance(asked, list):
            raise ops.RelayOpError("invalid_payload", "jobs must be a list of job numbers")
        if len(asked) > econnect.MAX_JOB_NUMBERS:
            raise ops.RelayOpError(
                "too_many_job_numbers",
                f"{len(asked)} job numbers asked for; this relay reads at most "
                f"{econnect.MAX_JOB_NUMBERS} in one request",
                asked=len(asked),
                maximum=econnect.MAX_JOB_NUMBERS,
            )
        keys = econnect.distinct_keys(asked)
        if keys:
            with db.get_read_connection(company) as conn:
                jobs = econnect.job_setup_health(conn, job_numbers=keys)
        else:
            jobs = []
        # `job` stays None for the list form: it means "the caller asked about ONE job", and the
        # backend reads it to tell a single answer from a wider one.
        return models.JobSetupHealthResponse(company=company, job=None, jobs=jobs).model_dump(mode="json")

    job = (payload.get("job") or "").strip() or None
    with db.get_read_connection(company) as conn:
        jobs = econnect.job_setup_health(conn, job)
    return models.JobSetupHealthResponse(company=company, job=job, jobs=jobs).model_dump(mode="json")


def _run_read_po_totals(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    po_number = (payload.get("po_number") or "").strip()
    if not po_number:
        raise ops.RelayOpError("missing_po_number", "po_number is required")
    with db.get_read_connection(company) as conn:
        totals = econnect.read_po_totals(conn, po_number)
    return {"company": company, "totals": totals}


def _run_sync_pos(company: str, payload: dict) -> dict:
    """Read a page of GP purchase orders for the backend's mirror sync (gp-owned-po mirror). Read-only,
    and always a PAGE: backfill walks POP10100/POP30100 by PONUMBER keyset, and `open_only` walks the
    open work book the same way. Both are bounded by page_size; the old unpaged `modified_since` branch
    is still answered for a backend too old to ask for either. See econnect.sync_pos."""
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        result = econnect.sync_pos(
            conn,
            cursor=payload.get("cursor"),
            page_size=payload.get("page_size", 300),
            modified_since=payload.get("modified_since"),
            open_only=bool(payload.get("open_only")),
        )
    return {"company": company, **result}


def _run_read_pos_by_number(company: str, payload: dict) -> dict:
    """Read exactly the POs the backend names, by key seek (econnect.read_pos_by_number).

    The companion to an open_only page: the backend diffs the open set it walked against what it holds
    and asks here for the ones that dropped out, instead of scanning history for them. Capped at
    econnect.MAX_PO_NUMBERS - the budget is bounded work per request, so a batch bigger than one batch
    is refused rather than quietly becoming the unbounded read this replaced."""
    ops.check_company_served(company)
    po_numbers = payload.get("po_numbers") or []
    if not isinstance(po_numbers, list):
        raise ops.RelayOpError("invalid_payload", "po_numbers must be a list of PO numbers")
    if len(po_numbers) > econnect.MAX_PO_NUMBERS:
        raise ops.RelayOpError(
            "too_many_po_numbers",
            f"{len(po_numbers)} PO numbers asked for; this relay reads at most "
            f"{econnect.MAX_PO_NUMBERS} in one request",
            asked=len(po_numbers),
            maximum=econnect.MAX_PO_NUMBERS,
        )
    with db.get_read_connection(company) as conn:
        result = econnect.read_pos_by_number(conn, po_numbers)
    return {"company": company, **result}


def _run_create_po(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
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
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_customers(conn)
    return {"company": company, "customers": rows}


def _run_list_customer_addresses(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    customer = (payload.get("customer") or "").strip()
    if not customer:
        raise ops.RelayOpError("missing_customer", "customer is required")
    with db.get_read_connection(company) as conn:
        rows = econnect.list_customer_addresses(conn, customer)
    return {"company": company, "customer": customer, "addresses": rows}


def _run_list_tax_schedules(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_tax_schedules(conn)
    return {"company": company, "tax_schedules": rows}


def _run_list_employees(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        # active_only is forwarded (like _run_list_vendors): the proc validates the estimator against
        # the whole of UPR00100, not just its active rows, so backdating or recreating a job whose
        # estimator has since been deactivated has to remain expressible.
        rows = econnect.list_employees(conn, active_only=payload.get("active_only", True))
    # Built through the response model rather than returned as a loose dict, so EmployeesResponse is
    # the enforced description of this op's wire shape instead of a second one that can silently drift.
    return models.EmployeesResponse(company=company, employees=rows).model_dump(mode="json")


def _run_list_divisions(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    with db.get_read_connection(company) as conn:
        rows = econnect.list_divisions(conn)
    return {"company": company, "divisions": rows}


def _run_create_job(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    request = models.CreateJobRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_job_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_create_customer_address(company: str, payload: dict) -> dict:
    """Add an address code to a GP customer (#444) - the write half of _run_list_customer_addresses.

    The customer arrives under the key `customer`, as it does on the read op: the two halves of the same
    picker should not disagree about what the customer key is called. `customer_number` is accepted too,
    since that is the name the model and the proc parameter use.

    A payload carrying BOTH with different values is refused rather than resolved. There is no reading
    of that which is a preference to honour - it is a caller that has lost track of which customer it is
    creating an address under, and silently picking one would file a job site against somebody else's
    account in GP, where nothing downstream would ever question it.

    A missing or blank customer answers missing_customer, exactly as _run_list_customer_addresses does.
    Letting the model raise it instead would surface the same mistake as a multi-line pydantic dump on
    the write half of a picker whose read half answers in one clean sentence."""
    ops.check_company_served(company)
    fields = dict(payload)
    customer = fields.pop("customer", None)
    if customer is not None:
        stated = fields.get("customer_number")
        if stated is not None and str(stated).strip() != str(customer).strip():
            raise ops.RelayOpError("invalid_payload", "customer and customer_number disagree")
        fields["customer_number"] = customer
    if not str(fields.get("customer_number") or "").strip():
        raise ops.RelayOpError("missing_customer", "customer is required")
    request = models.CreateCustomerAddressRequest(company=company, **fields)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_customer_address_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_update_job_site(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    request = models.UpdateJobSiteRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.update_job_site_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_create_receipt(company: str, payload: dict) -> dict:
    ops.check_company_served(company)
    request = models.ReceiptRequest(company=company, **payload)
    with db.get_connection(company) as conn:
        try:
            response = ops.create_receipt_op(conn, company=company, request=request)
            conn.commit()
            return response.model_dump(mode="json")
        except Exception:
            conn.rollback()
            raise


def _run_server_load(company: str, payload: dict) -> dict:
    """How busy the GP SQL server is right now (server_load.py), re-read if the cached reading is
    older than 15s. The backend probes this while it is holding a background loop back, so it is the
    one op that must answer while everything else is being refused - it is never itself refused, and
    it needs no company (the DMVs are server-wide, and a paused backend may have none in hand)."""
    return server_load.refresh().to_dict()


_OPS = {
    "list_vendors": _run_list_vendors,
    # issue #500 - the vendor's email, read live at send time. Nexus stores no vendor contact.
    "get_vendor_contact": _run_get_vendor_contact,
    "list_buyers": _run_list_buyers,
    "list_tax_details": _run_list_tax_details,
    "list_cost_codes": _run_list_cost_codes,
    # issue #448 - the company cost-code master, so a job created from Nexus can be provisioned with a
    # cost structure instead of arriving with none (which #425 quarantines on sight).
    "list_cost_code_master": _run_list_cost_code_master,
    "list_jobs": _run_list_jobs,
    "read_po_totals": _run_read_po_totals,
    # issue: gp-owned-po mirror - a page of GP's own purchase orders for the backend to mirror locally.
    "sync_pos": _run_sync_pos,
    # ^ and its companion: the POs that left the open set, fetched by number instead of found by scan.
    "read_pos_by_number": _run_read_pos_by_number,
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
    # issue #444 - the create-job dialog can add a job site that was never entered in GP, instead of
    # dead-ending on an address picker that has no code for it.
    "create_customer_address": _run_create_customer_address,
    # issue #497 - a project's site address and name are edited in Nexus, and GP has to hear about it.
    # Mints a job-specific address code rather than editing a shared one; see update_job_site_op.
    "update_job_site": _run_update_job_site,
    # issue #425 - jobs replicated from UCSH carry GL account indexes that do not exist in UBC, so a
    # PO against them registers and can never be received. This is how Nexus finds out which ones.
    "job_setup_health": _run_job_setup_health,
    # the live load reading the backend paces its background loops on - see BACKGROUND_OPS below.
    "server_load": _run_server_load,
}

# WHICH CALL is deferrable is the caller's to declare: the job frame carries `background: true`, set by
# the backend's timer-driven loops and by nothing else. That is the flag the busy gate keys on, because
# the op name alone cannot answer it - the GP job picker, the admin Sync from GP button and the
# register-PO screen's live setup check all reach the same ops the adoption pass does, and somebody is
# waiting on those.
#
# BACKGROUND_OPS is the relay's own outer bound on that claim: the ops a backend loop is known to call
# on a timer, audited against its callers.
#   sync_pos           - gp_po_sync.run_forever, the PO mirror's backfill and open-book pages
#   read_pos_by_number - the same loop, fetching the POs that dropped out of the open set
#   list_jobs          - gp_job_sync.run_forever, the job adoption pass (POLL_SECONDS)
#   job_setup_health   - the same adoption pass's setup-health stamp
# A flagged job is only sampled for - and so only ever refused - if its op is in here. A backend that
# flagged create_po as background could otherwise have a user's PO write, already accepted and owed to
# them, deferred by this relay; the list is what makes that unexpressible.
#
# Everything else reaching the relay is somebody waiting on it: the create/receive writes (directly or
# replayed from the backend's outbox), and the pickers. None of those are ever refused - a person is
# worth more than a percentage point of CPU - and an UNFLAGGED job is never refused and never pays for
# a sample, whatever its op.
BACKGROUND_OPS = frozenset({"sync_pos", "read_pos_by_number", "list_jobs", "job_setup_health"})

# Ops that answer a question about the SERVER rather than about a company. They run without one: the
# backend probes the load while paused, and the company checks below have nothing to bite on because
# there is no company data in the answer.
_COMPANYLESS_OPS = frozenset({"server_load"})

# What the backend is told to wait before trying the deferred work again. One minute because that is
# how often SQL Server refreshes the ring buffer the CPU reading comes from - asking sooner can only
# get the same number back.
BUSY_RETRY_AFTER_SECONDS = 60


def _allowed_phrase(companies: list[str]) -> str:
    """The pin as a sentence fragment: one company reads "TUBC is", a longer pin "TUBC and UBC are". The
    refusal below is shown verbatim in the browser, so it has to read as prose however many companies are
    in the pin - one of them today."""
    if len(companies) == 1:
        return f"{companies[0]} is"
    return f"{', '.join(companies[:-1])} and {companies[-1]} are"


def _dispatch(
    op: str,
    company: str,
    payload: dict,
    allowed_companies: list[str] | None = None,
    background: bool = False,
) -> dict:
    """Run one job synchronously (pyodbc is blocking) and return its {ok, result|error} body,
    without the id - _handle_job stitches that back on. Runs on a worker thread via
    asyncio.to_thread so a slow GP call doesn't block the channel's read loop.

    `background` is the frame's own claim that nobody is waiting on this call (see BACKGROUND_OPS).
    It is the only thing that can get a job deferred while GP's server is busy; a frame without it is
    run whatever the server looks like.

    `allowed_companies` is the CHANNEL's restriction (#414): None for the production channel, which
    reaches every company this relay discovered, and the sandbox list for any other backend.
    Non-production channels get full read AND write access - a PR that touches GP has to be verifiable
    before it merges - and this is the sole thing keeping that safe, so it is checked before any handler
    runs. It layers on top of ops.check_company_served rather than replacing it: that one is what says
    the company was found in GP at all."""
    handler = _OPS.get(op)
    if handler is None:
        return _reply({"ok": False, "error": errors.error_body("unknown_op", f"unknown op {op!r}")})
    if op not in _COMPANYLESS_OPS:
        if not company:
            return _reply({"ok": False, "error": errors.error_body("missing_company", "company is required")})
        if allowed_companies is not None and company not in allowed_companies:
            return _reply(
                {
                    "ok": False,
                    "error": errors.error_body(
                        "company_not_allowed_on_channel",
                        # Joined, not interpolated as a list: relay_gateway raises RelayCallError(error
                        # ["message"]), so this string is what the browser shows - "only ['TUBC']" would
                        # leak a Python repr into the UI.
                        f"{company} is not reachable from a non-production backend; "
                        f"only {_allowed_phrase(allowed_companies)}",
                        company=company,
                        allowed=list(allowed_companies),
                    ),
                }
            )

    # The last gate in front of GP. Work the backend itself declared deferrable stands down while the
    # server is busy - whatever that backend's own pacing decided, because a relay that ran the mirror
    # into a pinned CPU once has to be the thing that cannot do it again. Read fresh (15s-cached)
    # rather than off the last reading: the whole point is the LIVE state of the server. An unflagged
    # job never reaches this and never pays for the sample.
    if background and op in BACKGROUND_OPS:
        # Named while it samples: a reading that is not already cached opens a connection of its own to
        # the system database, and that is the relay's overhead for deciding whether to run at all -
        # not the deferred op's cost. Unnamed it would land in gp_cost as an unattributed "unknown"
        # against DYNAMICS, which is the one thing the cost accounting exists to stop.
        with db.measuring("server_load", ""):
            load = server_load.refresh()
        ceiling = get_settings().gp.load_ceiling_pct
        if load.busy(ceiling):
            logger.info(
                "background op deferred; the GP server is busy",
                extra={
                    "category": "server_busy",
                    "op": op,
                    "company": company,
                    "sql_cpu_pct": load.sql_cpu_pct,
                    "ceiling_pct": ceiling,
                },
            )
            return _reply(
                {
                    "ok": False,
                    "error": errors.error_body(
                        "server_busy",
                        f"GP SQL server is at {load.sql_cpu_pct}% CPU, above this relay's ceiling of "
                        f"{ceiling}%; background work deferred",
                        sql_cpu_pct=load.sql_cpu_pct,
                        ceiling_pct=ceiling,
                        retry_after_seconds=BUSY_RETRY_AFTER_SECONDS,
                    ),
                }
            )

    # Everything below runs named: db.py measures what each connection cost the GP server and books it
    # against (company, op). The whole block, not just the handler - the eConnect description lookup
    # opens a connection of its own, and it belongs to this op too. The flag rides along so a
    # background read gets the shorter command timeout (db._command_timeout): nobody is waiting on it,
    # so an overrunning statement is cancelled on the server rather than allowed the user-facing limit.
    # Same audit as the gate above: only an op in BACKGROUND_OPS is ever cut short, so a write a backend
    # mis-flagged as background still gets the user-facing timeout it needs.
    with db.measuring(op, company, background and op in BACKGROUND_OPS) as measured:
        reply = _run_handler(handler, company, payload)
    return _reply(reply, cost=measured.cost)


def _run_handler(handler, company: str, payload: dict) -> dict:
    """The handler call and its error mapping: the {ok, result|error} half of a reply, before the
    cost/server fields _reply attaches."""
    try:
        return {"ok": True, "result": handler(company, payload)}
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


def _reply(body: dict, cost: dict | None = None) -> dict:
    """Every reply carries what the op cost the GP server and what the server looked like, so the
    backend paces on measured facts instead of on a fixed wait.

    `server` is the LAST reading, not a fresh one: only a background op samples on its own account
    (above), because a user-facing op must not pay a connect - up to the 10s connection timeout, on a
    server that is by definition already struggling - before its own work starts. `sampled_at` rides
    along so the backend can see how old the reading it got is, and null means this relay has not
    taken one yet."""
    latest = server_load.current()
    body["cost"] = cost
    body["server"] = latest.to_dict() if latest is not None else None
    return body


async def _handle_job(job: dict, allowed_companies: list[str] | None = None) -> dict:
    job_id = job.get("id")
    op = job.get("op")
    company = job.get("company")
    payload = job.get("payload") or {}
    # Optional, and strictly true: the backend's timer-driven loops set it and nothing else does, so
    # anything else in that slot - absent, false, a string, a relay talking to an older backend - means
    # somebody is waiting on this job and it runs.
    background = job.get("background") is True

    try:
        reply = await asyncio.to_thread(_dispatch, op, company, payload, allowed_companies, background)
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


def _served_companies(channel_allowed: list[str] | None) -> tuple[list[str], dict[str, str], str | None]:
    """What THIS channel is told it can reach: the companies discovered in GP, intersected with the
    channel's own pin (#414) so a test backend is never offered a company it would refuse anyway. The
    discovery error rides along, so a backend can tell "this relay could not read GP" from "this relay
    serves none of the companies you may ask for"."""
    discovered = companies.current()
    served = [c for c in discovered.companies if channel_allowed is None or c in channel_allowed]
    return served, {c: discovered.names[c] for c in served}, discovered.error


def _hello_frame(channel_allowed: list[str] | None = None) -> dict:
    """The relay's identity frame, sent right after the channel connects (issue #315) and again on the
    same socket whenever the discovered companies change. It carries the build tag and the exact op-set
    this relay supports so the backend can reject a call for an op this build lacks with a clear
    'update the relay' error - proactively, and without a 30s round-trip - and show the live build on
    Admin -> Relay Installs. `updater.current_build()` is 'dev' for a source checkout, which is fine:
    the backend only compares the op-set, and reports the build verbatim.

    `companies` / `company_names` are the GP companies this relay serves ON THIS CHANNEL, read from GP's
    own company master (companies.py), so the backend can route a job to a relay that can actually answer
    it instead of learning company_not_allowed on the round-trip. Both are empty and `companies_error`
    carries the reason when that master could not be read - a relay that cannot tell which companies
    exist serves none of them. `features` says what this build understands beyond jobs - "channels" means
    it accepts a pushed preview-channel list, so a backend talking to an older relay knows not to bother
    sending one."""
    from . import updater  # lazy: keep channel import-light and avoid any package load-order coupling

    served, names, error = _served_companies(channel_allowed)
    return {
        "type": "hello",
        "build": updater.current_build(),
        "ops": sorted(_OPS),
        "version": VERSION,
        "companies": served,
        "company_names": names,
        "companies_error": error,
        "features": ["channels"],
    }


# How often a live channel re-reads GP's company master. A company is added in GP about once a year, so
# this is set by "nobody should have to restart the relay for it", not by any need for speed.
COMPANY_REFRESH_SECONDS = 900.0


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

        # Re-read GP's company master before announcing anything: the hello names the companies this
        # relay serves, and a set discovered ten hours ago on a previous connection is not what the
        # backend should be routing on. On a thread because pyodbc blocks, and cheap when several
        # channels connect together - companies.refresh hands back a reading a few seconds old.
        await asyncio.to_thread(companies.refresh)

        # Advertise this relay's build + op-set to the backend before anything else (issue #315). Sent
        # directly here, ahead of the writer coroutine below, so it's the first frame on the wire - the
        # backend records it and can then reject calls for ops this build lacks with a clear error.
        await ws.send(json.dumps(_hello_frame(allowed_companies)))
        sent_companies = _served_companies(allowed_companies)

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

        async def _company_refresher() -> None:
            # Re-discover on a timer and re-announce only when THIS channel's answer actually changed
            # (a company added in GP, or discovery recovering from a failed read). Per connection like
            # the writer above, and cancelled with it, so a dropped socket takes its refresher with it.
            nonlocal sent_companies
            while True:
                await asyncio.sleep(COMPANY_REFRESH_SECONDS)
                await asyncio.to_thread(companies.refresh)
                served = _served_companies(allowed_companies)
                if served != sent_companies:
                    sent_companies = served
                    await send_queue.put(_hello_frame(allowed_companies))

        writer_task = asyncio.create_task(_writer())
        refresh_task = asyncio.create_task(_company_refresher())
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
                if isinstance(job, dict) and job.get("type") == "channels":
                    # The preview-environment list, pushed rather than polled. Nothing to answer.
                    _handle_channels_frame(job, url)
                    continue
                task = asyncio.create_task(_dispatch_job(job))
                jobs.add(task)
                task.add_done_callback(jobs.discard)
        finally:
            writer_task.cancel()
            refresh_task.cancel()
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
            # A clean return - the socket closed without raising - used to log NOTHING, so the only
            # trace of the drop was the next "channel connected" line with no warning before it
            # (issue #384). The 2026-07-28 outage reads in relay.log as a bare reconnect out of
            # nowhere for exactly this reason, which is what made the drop undiagnosable from either
            # end. Same shape as the classified failures below so the desktop UI and anyone grepping
            # relay.log treat it like any other reconnect event.
            #
            # It goes through the same quiet_repeat demotion for the same #414 reason: a PR
            # environment torn down when its PR closed can sit in config.toml closing cleanly in a
            # loop, and that must not bury production's own reconnect events. The secret_rejected arm
            # of the rule below cannot apply here, so the primary channel never demotes this one -
            # a production channel that keeps closing cleanly is exactly what we want to see.
            quiet_repeat = prev_category == "closed_clean" and not primary
            logger.log(
                logging.DEBUG if quiet_repeat else logging.WARNING,
                "channel closed without an error; reconnecting",
                extra={"category": "closed_clean", "url": url, "backoff": backoff},
            )
            prev_category = "closed_clean"
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


# How often the supervisor re-reads config.toml to see which backends it should be dialling (#456).
# The cost of a tick is one small TOML parse - the same one _run_channel already pays on every
# reconnect attempt - so this is set by how long somebody should have to wait for a channel to come
# up, not by what the parse costs. Ten seconds is under the time it takes to alt-tab back to the
# browser, which is the point: adding a PR environment stops being a thing you wait on.
CHANNEL_RECONCILE_SECONDS = 10.0


def _secret_hash(secret: str) -> str:
    """A fingerprint of the enrolled secret, so the supervisor can notice it changed without holding
    the secret itself in a second place."""
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


def _configured_channels() -> tuple[list[str], str] | None:
    """The backend URLs config.toml currently names and a hash of the secret beside them, or None if it
    could not be read.

    Guarded and returning None rather than raising, for the reason _run_channel re-reads the secret
    the same way: hand-editing config.toml on a running relay is the documented way to add a test
    backend (#414), so catching a save mid-write or a missing bracket is a live possibility. Letting
    that propagate would kill the supervisor, taking production's channel with it - and no amount of
    fixing the file afterwards would bring it back without a serve restart, which is the thing #456
    exists to stop needing. None means "keep whatever is running"."""
    try:
        get_settings.cache_clear()
        settings = get_settings()
        return settings.channel.backend_urls, _secret_hash(settings.auth.shared_secret)
    except Exception as e:
        logger.warning(
            "could not re-read config.toml; leaving the current channels alone",
            extra={"category": "config_unreadable", "error": str(e)},
        )
        return None


# The ONLY shape a pushed channel may take. This is the load-bearing check on this side: the relay
# holds GP credentials, so "the backend told me to" is not sufficient reason to dial a host. Anchored
# and fully literal apart from the PR number, so no frame off the socket can name an arbitrary
# destination - the worst a compromised or buggy backend can produce is a Railway preview address that
# does not exist, which fails to connect and retries harmlessly.
_PUSHED_URL_RE = re.compile(r"^wss://backend-uc-nexus-pr-\d+\.up\.railway\.app/relay-link$")

# The preview channels production last pushed. None means "never told", which is different from "told,
# and there are none" - the latter is an empty list and legitimately retires every pushed channel. A
# push REPLACES this wholesale: the frame carries the full list every time, so a URL absent from it is
# a preview environment that has gone away.
_pushed: list[str] | None = None

# Set by a push so the supervisor reconciles at once instead of sitting out the rest of its tick. A PR
# environment coming up in about a second rather than up to ten is the whole reason the backend pushes
# rather than the relay polling. Bound to the supervisor's own loop and cleared when it exits, so a
# frame arriving with no supervisor running (there is none - the channels live under it) is a no-op.
_wake: asyncio.Event | None = None


def _pushed_urls() -> list[str]:
    """Whatever production last pushed. Empty until the first frame, so this can only ever ADD to what
    config.toml names - a relay that never hears from production behaves exactly as it did before the
    pushed list existed."""
    return list(_pushed or [])


def _accepts_pushed_channels() -> bool:
    try:
        return bool(get_settings().channel.accept_pushed_preview_backends)
    except Exception:
        # An unreadable config is already logged by the supervisor's own read; refusing the push is the
        # conservative half of "cannot tell".
        return False


def _handle_channels_frame(frame: dict, url: str) -> None:
    """Take a {"type": "channels", "urls": [...]} push and make it the pushed set.

    PRIMARY channel only. A preview backend is the least trusted thing this process talks to, and one
    that could name the next backends to dial would be able to walk the relay onto a host of its
    choosing; production is the only channel whose word is taken for this."""
    global _pushed

    if not is_primary_backend_url(url):
        logger.debug(
            "ignoring a channel list pushed by a non-production backend",
            extra={"category": "pushed_channels_ignored", "url": url},
        )
        return
    if not _accepts_pushed_channels():
        return

    raw = frame.get("urls")
    if not isinstance(raw, list):
        logger.warning(
            "ignored a channels frame with no usable url list",
            extra={"category": "pushed_channels_rejected", "url": url},
        )
        return

    accepted, rejected = [], []
    for candidate in raw:
        pushed = candidate.strip() if isinstance(candidate, str) else ""
        # is_primary_backend_url as well as the pattern: belt and braces, so a pushed URL can never take
        # production's identity and shed the sandbox company pin that makes this safe at all.
        if _PUSHED_URL_RE.match(pushed) and not is_primary_backend_url(pushed):
            if pushed not in accepted:
                accepted.append(pushed)
        elif pushed:
            rejected.append(pushed)
    if rejected:
        logger.warning(
            "ignored pushed channel URLs that do not match the preview backend pattern",
            extra={"category": "pushed_channels_rejected", "rejected": rejected},
        )

    previous = _pushed_urls()
    _pushed = accepted
    if previous == accepted:
        return  # the same list re-sent (a reconnect, or a push we already applied)
    logger.info(
        "backend channels pushed",
        extra={
            "urls": accepted,
            "added": sorted(set(accepted) - set(previous)),
            # Named as well as added, for the same reason the supervisor names them: a removal
            # otherwise logs `added: []` and leaves the operator diffing two lines by eye.
            "removed": sorted(set(previous) - set(accepted)),
        },
    )
    if _wake is not None:
        _wake.set()


def _warn_if_no_primary(urls: list[str]) -> None:
    """Loud, because the likeliest cause is a typo in a hand-added backend_url list rather than a
    deliberate choice: production is then just another restricted channel and every real UBC/UCSH job
    is refused with company_not_allowed_on_channel. A dev checkout pointed at localhost hits this
    legitimately, which is why it warns rather than refusing to start."""
    if urls and not any(is_primary_backend_url(url) for url in urls):
        logger.warning(
            "no production channel configured - EVERY channel is restricted to the sandbox companies. "
            "if this is a workstation, check [channel] backend_url matches the production URL exactly, "
            "or list only the extra backend under [channel] extra_backend_urls and leave backend_url alone.",
            extra={"category": "no_primary_channel", "urls": urls, "expected": PRODUCTION_BACKEND_URL},
        )


async def _wait_for_next_tick(stop_event: asyncio.Event | None, wake: asyncio.Event) -> None:
    """Sit out the reconcile interval, returning early when shutdown is requested or a pushed channel
    list woke us. `wake` is cleared AFTER the wait rather than before it, so a push that lands while a
    reconcile pass is still running gets its own pass instead of being swallowed by that one."""
    waiters = [asyncio.ensure_future(wake.wait())]
    if stop_event is not None:
        waiters.append(asyncio.ensure_future(stop_event.wait()))
    try:
        await asyncio.wait(waiters, timeout=CHANNEL_RECONCILE_SECONDS, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        wake.clear()


async def run_forever(stop_event: asyncio.Event | None = None) -> None:
    """Hold up one reconnecting channel per configured backend URL, and keep that set in step with
    config.toml. Intended to run as a single background asyncio task alongside the relay's existing
    HTTP server (see cli.py); with no [channel] backend_url configured it simply runs no channels.

    The URL list used to be read once, so adding or removing a backend took a serve restart - the
    desktop app's Restart Relay button. That was the wrong shape for the thing it was blocking (#456).
    Testing a change against a Railway PR environment means adding its URL, and on an empty preview
    database nothing is testable at all until the channel is up: the project list itself comes from
    GP. An agent can edit config.toml and read relay.log; it cannot click a button in a tray app. So
    the one manual step sat in the middle of an otherwise unattended loop, and a session on #455 spent
    thirty minutes idle waiting for that click.

    Now the URL set is reconciled on a tick, the way the secret is already re-read on every reconnect:
    a URL that appears gets a channel, a URL that disappears has its channel cancelled and its /health
    row dropped. Teardown matters as much as setup - a closed PR's environment otherwise retries
    forever against a backend that no longer exists.

    The same tick also notices a re-enrolment. `_run_channel` re-reads the secret before every dial, so
    a channel that is DOWN heals itself - but a connected one holds a socket authenticated with the old
    secret and would never dial again to find out, which reads as "enrolled fine, still not working".
    A channel whose recorded secret hash no longer matches the file is cancelled and restarted here.

    What is deliberately NOT reconciled is a channel that died: the task set is diffed against the URL
    set, not against liveness. `_run_channel` catches per attempt and is not supposed to exit, so one
    that does is a bug worth seeing in the log rather than papering over with a respawn loop."""
    global _wake

    tasks: dict[str, asyncio.Task] = {}
    # The secret each running channel dialled with, so a re-enrolment can be told from a steady state.
    # Hashes, not the secret itself.
    secrets: dict[str, str] = {}
    known: set[str] | None = None
    # Created here rather than at import: an asyncio.Event binds to the loop that first waits on it, and
    # the supervisor is the only thing that waits on this one.
    wake = asyncio.Event()
    _wake = wake

    async def _supervised(url: str) -> None:
        """Log a channel that escapes its own retry loop. _run_channel is not supposed to - it catches
        Exception per attempt - but if it ever does, the log has to happen HERE, because nothing else
        awaits these tasks while they are healthy."""
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

    async def _restart_drifted(urls: list[str], secret_hash: str) -> None:
        """Cancel every channel that connected with a secret the file no longer holds, so the loop
        below re-creates it and it dials with the current one. WARNING, not info: the workstation was
        just re-enrolled and somebody is waiting to see whether it took.

        Only channels that are staying: one whose URL has ALSO just left config.toml is not restarted,
        it is retired below - restarting it would drop its /health row on the floor."""
        drifted = [(url, task) for url, task in tasks.items() if url in urls and secrets.get(url) != secret_hash]
        if not drifted:
            return
        logger.warning(
            "the enrolled secret changed; restarting the backend channels so they reconnect with it",
            extra={"category": "secret_changed", "urls": [url for url, _ in drifted]},
        )
        for url, task in drifted:
            tasks.pop(url, None)
            task.cancel()
        await asyncio.gather(*(task for _, task in drifted), return_exceptions=True)

    async def _reconcile(urls: list[str], secret_hash: str) -> None:
        await _restart_drifted(urls, secret_hash)
        for url in urls:
            if url not in tasks:
                register_channels([url])  # so /health lists it from the next poll, before any dial
                tasks[url] = asyncio.create_task(_supervised(url), name=f"channel:{url}")
                secrets[url] = secret_hash
        retired = [(url, tasks.pop(url)) for url in list(tasks) if url not in urls]
        for _, task in retired:
            task.cancel()
        if retired:
            # Await the cancellations before dropping the state rows, so a task still unwinding cannot
            # re-insert its own key through _mark_disconnected and leave a ghost channel on /health.
            await asyncio.gather(*(task for _, task in retired), return_exceptions=True)
            for url, _ in retired:
                forget_channel(url)
                secrets.pop(url, None)

    try:
        while True:
            channels = _configured_channels()
            urls = None
            secret_hash = ""
            if channels is not None:
                configured, secret_hash = channels
                # Union, config first, so a hand-added URL keeps its position and a pushed one can only
                # ever be additive. Dedup is backend_urls' job for the config half; this repeats it
                # across the join because the same PR environment may legitimately be in both while an
                # operator is mid-migration off the manual step.
                seen = {url.strip().rstrip("/").lower() for url in configured}
                urls = configured + [u for u in _pushed_urls() if u.strip().rstrip("/").lower() not in seen]
            if urls is not None:
                if known != set(urls):
                    # Only on a change, so a steady relay logs this once at startup rather than every
                    # tick - and an operator grepping relay.log sees the edit they just made.
                    logger.info(
                        "backend channels configured" if known is None else "backend channels changed",
                        extra={
                            "urls": urls,
                            "added": sorted(set(urls) - (known or set())),
                            # Named as well as added: a removal otherwise logs `added: []` and leaves
                            # the operator to diff the URL list against the previous line to see what
                            # they just took out.
                            "removed": sorted((known or set()) - set(urls)),
                        },
                    )
                    _warn_if_no_primary(urls)
                    known = set(urls)
                await _reconcile(urls, secret_hash)
            if stop_event is not None and stop_event.is_set():
                return
            # Wait rather than sleeping through the interval, so neither a shutdown nor a pushed
            # channel list is held up for most of a tick.
            await _wait_for_next_tick(stop_event, wake)
            if stop_event is not None and stop_event.is_set():
                return
    finally:
        _wake = None
        # Reap them rather than just cancelling: cli.py cancels THIS task on shutdown, and a bare
        # cancel() would leave the children pending as the loop closes ("Task was destroyed but it is
        # pending"). CancelledError is a BaseException, so a cancelled child is not logged above.
        children = list(tasks.values())
        for task in children:
            task.cancel()
        await asyncio.gather(*children, return_exceptions=True)
