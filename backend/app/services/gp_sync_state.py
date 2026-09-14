"""GP SYNC STATE: the backend's account of its own sync work, served two ways (#679).

NEXUS GP TRAFFIC has two surfaces - the tab in the relay window on the workstation and the page under
Admin in Nexus - and both need the same facts: per company, whether the FIRST TIME GP COMPANY NEXUS
INITIALIZATION is done or where it is up to, the OPEN-POS SYNC in progress and the last one finished,
the last NEW PO CHECK, the last GP JOBS SYNC, plus the GP READ LIMIT balance, whether the GP CPU PAUSE
is on, and the PENDING GP WRITES counts. So it is built once, by `snapshot()`, and then either
converted to the GraphQL type for the `gpSyncState` query or pushed down the relay socket as the
`gp_sync_state` frame. One document, two readers, no chance of the two disagreeing.

Nothing here is stored. Every fact is either already in memory (the two sync loops' own bookkeeping,
the read budget, what the relay said on its hello) or three small aggregate queries away, so the page
can be polled and the frame pushed every few seconds without either becoming a cost.

`snapshot()` is SYNCHRONOUS and touches the database, so both callers run it through
`asyncio.to_thread` - the relay socket lives on the event loop and must not block on Postgres.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models.enums import POStatus
from app.models.gp_po_sync_state import GpPoSyncState
from app.models.purchase_order import PurchaseOrder
from app.repositories import gp_outbox_repository
from app.services import gp_job_sync, gp_load, gp_po_sync
from app.services.relay_gateway import GP_SYNC_STATE_FEATURE
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

_env_warned: set[str] = set()

# How often the connected relay is handed a fresh copy. Ten seconds is fast enough that the tab's "as
# of Ns ago" reads as live and slow enough that the three aggregate queries behind it are nothing. The
# floor is two seconds: anything under that is a poll, not a dashboard.
PUSH_SECONDS = gp_load.env_number(
    "GP_SYNC_STATE_PUSH_SECONDS", 10.0, float, minimum=2.0, warned=_env_warned, prefix="gp sync state"
)

# A mirrored PO is OPEN until GP says it is finished one way or the other. Derived from the status the
# mirror writes (PO STATUS FROM QUANTITIES), not from a GP status code.
_FINISHED_STATUSES = (POStatus.CLOSED, POStatus.CANCELLED)

_wake_event: asyncio.Event | None = None


def enabled() -> bool:
    """Env kill switch, default on, matching the two sync loops this reports on."""
    return os.getenv("GP_SYNC_STATE_ENABLED", "true").lower() not in ("false", "0", "no")


def _iso(value: datetime | None) -> str | None:
    """A timestamp as the contract carries it: ISO 8601 UTC with a trailing Z.

    Every datetime that reaches here is naive UTC - `datetime.utcnow()` in the loops, naive UTC columns
    in the database - so the Z is appended rather than derived. An aware value is converted first so a
    future caller cannot produce a stamp that says Z and means something else."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.isoformat() + "Z"


def _read_db(companies_hint: list[str]) -> dict:
    """The only database work a snapshot does: three aggregate queries in ONE session.

    No PO rows are ever loaded. `mirrored_pos` and `open_pos` come from a single grouped count over
    purchase_orders - two filtered counts in one pass - because this is polled by every open admin page
    and pushed to the relay every few seconds, and materializing a company's purchase orders to count
    them is exactly the resolver N+1 the performance rules in CLAUDE.md exist to prevent.

    `companies_hint` is what the connected relay serves. When it is empty - nothing connected - the
    companies come from the MIRROR PROGRESS rows instead, so the admin page still shows the history of
    a mirror that is currently dark."""
    with SessionLocal() as session:
        progress = {
            row.company: {
                "initialization_done": bool(row.backfill_done),
                "initialization_cursor": row.backfill_cursor,
                "open_pass_cursor": row.open_book_cursor,
                "open_pass_started_at": row.open_pass_started_at,
            }
            for row in session.execute(
                select(
                    GpPoSyncState.company,
                    GpPoSyncState.backfill_done,
                    GpPoSyncState.backfill_cursor,
                    GpPoSyncState.open_book_cursor,
                    GpPoSyncState.open_pass_started_at,
                )
            ).all()
        }
        po_counts = {
            company: {"mirrored_pos": mirrored or 0, "open_pos": still_open or 0}
            for company, mirrored, still_open in session.execute(
                select(
                    PurchaseOrder.company,
                    func.count(),
                    func.count().filter(PurchaseOrder.status.notin_(_FINISHED_STATUSES)),
                )
                .where(
                    # A GP number is what makes a PO one GP holds: a Nexus draft has none until it is
                    # registered. Soft-deleted rows are left out, as every other read of this table
                    # leaves them out - a figure nobody can see in the PO table is not a figure.
                    PurchaseOrder.po_number.isnot(None),
                    PurchaseOrder.deleted_at.is_(None),
                )
                .group_by(PurchaseOrder.company)
            ).all()
        }
        pending_writes = gp_outbox_repository.summary(session)
    return {
        "companies": sorted(companies_hint) if companies_hint else sorted(progress),
        "progress": progress,
        "po_counts": po_counts,
        "pending_writes": pending_writes,
    }


def activity() -> dict:
    """What the two GP sync loops are doing at this instant.

    The PO mirror answers first: it is the loop that runs for most of the day, and when both have a
    record the PO page is the one somebody watching is waiting on. With neither running, GP CPU PAUSE
    is a different answer from idle - "nothing is happening because GP is busy" against "nothing is
    due" - so the pause is reported as its own kind."""
    current = gp_po_sync.activity() or gp_job_sync.activity()
    if current is not None:
        return {
            "kind": current["kind"],
            "company": current.get("company"),
            "page": current.get("page"),
            "cursor": current.get("cursor"),
            "started_at": _iso(current.get("started_at")),
        }
    return {
        "kind": "paused" if gp_load.paused() else "idle",
        "company": None,
        "page": None,
        "cursor": None,
        "started_at": None,
    }


def snapshot() -> dict:
    """The whole GP SYNC STATE document. Synchronous, and safe to call from a worker thread."""
    now = datetime.utcnow()
    db = _read_db(relay_gateway.companies)
    names = relay_gateway.company_names
    budget = gp_load.policy.budget()
    sample = relay_gateway.last_server_sample or {}
    last_open_passes = gp_po_sync.last_open_passes()
    last_new_po_checks = gp_po_sync.last_new_po_checks()
    last_jobs_syncs = gp_job_sync.last_runs()

    companies = []
    for company in db["companies"]:
        # A company the relay serves that has no MIRROR PROGRESS row yet is listed anyway, as not
        # initialized with zero counts - "this company exists and nothing has been mirrored" is the
        # answer somebody enrolling a new company is looking for.
        progress = db["progress"].get(company, {})
        counts = db["po_counts"].get(company, {})
        open_pass = last_open_passes.get(company)
        new_po_check = last_new_po_checks.get(company)
        jobs_sync = last_jobs_syncs.get(company)
        companies.append(
            {
                "company": company,
                "name": names.get(company),
                "initialization_done": bool(progress.get("initialization_done", False)),
                "initialization_cursor": progress.get("initialization_cursor"),
                "open_pass_started_at": _iso(progress.get("open_pass_started_at")),
                "open_pass_cursor": progress.get("open_pass_cursor"),
                "last_open_pass_finished_at": _iso(open_pass["finished_at"]) if open_pass else None,
                "last_open_pass": (
                    {
                        "pages": open_pass["pages"],
                        "pos": open_pass["pos"],
                        "left_open_table": open_pass["left_open_table"],
                        "missing_in_gp": open_pass["missing_in_gp"],
                        "cancelled": open_pass["cancelled"],
                        "created": open_pass["created"],
                        "updated": open_pass["updated"],
                    }
                    if open_pass
                    else None
                ),
                "last_new_po_check_at": _iso(new_po_check["at"]) if new_po_check else None,
                "last_new_po_check_pos": new_po_check["pos"] if new_po_check else None,
                "last_jobs_sync_at": _iso(jobs_sync["at"]) if jobs_sync else None,
                "last_jobs_sync": (
                    {"total": jobs_sync["total"], "adopted": jobs_sync["adopted"]} if jobs_sync else None
                ),
                "mirrored_pos": counts.get("mirrored_pos", 0),
                "open_pos": counts.get("open_pos", 0),
            }
        )

    pending = db["pending_writes"]
    return {
        "generated_at": _iso(now),
        "relay": {
            "connected": relay_gateway.connected,
            "build": relay_gateway.build,
            "companies": relay_gateway.companies,
            "install_id": str(relay_gateway.install_id) if relay_gateway.install_id else None,
        },
        "po_sync_enabled": gp_po_sync.enabled(),
        "job_sync_enabled": gp_job_sync.enabled(),
        "pacing": {
            "reads_per_minute": budget["reads_per_minute"],
            "read_batch": budget["read_batch"],
            "reads_available": budget["reads_available"],
            "paused": gp_load.policy.paused,
            "paused_reason": gp_load.policy.paused_reason,
            "resume_check_in_seconds": gp_load.policy.resume_check_in_seconds(),
            "cpu_pause_pct": gp_load.SERVER_CPU_PAUSE_PCT,
            "sql_cpu_pct": sample.get("sql_cpu_pct"),
            "sql_cpu_sampled_at": sample.get("sampled_at"),
        },
        "initialization_window": {
            "label": gp_po_sync.BACKFILL_WINDOW.label,
            "open": gp_po_sync.BACKFILL_WINDOW.allows(now),
        },
        "activity": activity(),
        "companies": companies,
        "pending_writes": {
            "pending": pending["pending"],
            "in_flight": pending["in_flight"],
            "failed": pending["failed"],
            "oldest_pending_at": _iso(pending["oldest_pending_at"]),
            "last_drained_at": _iso(pending["last_drained_at"]),
        },
    }


def wake() -> None:
    """Push the next copy now rather than at the end of the interval. Called when the relay's hello
    lands, so its tab has the state within a moment of connecting instead of up to PUSH_SECONDS later."""
    if _wake_event is not None:
        try:
            _wake_event.set()
        except Exception:  # noqa: BLE001 - never let a wake-up break the caller's read loop
            logger.exception("gp sync state: failed to signal the push loop")


async def _push_once() -> bool:
    """Build and push one copy, if there is a relay that can read it. True if one was sent.

    Gated on the feature the relay advertises rather than on the connection alone: a build that
    predates NEXUS GP TRAFFIC would read the frame as a job reply and log an uncorrelated id, which is
    the same reason push_channels is gated."""
    if not (relay_gateway.connected and relay_gateway.has_feature(GP_SYNC_STATE_FEATURE)):
        return False
    state = await asyncio.to_thread(snapshot)
    await relay_gateway.push_gp_sync_state(state)
    return True


async def run_forever() -> None:
    """The lifespan task: hand the connected relay a fresh GP SYNC STATE every PUSH_SECONDS.

    Every iteration is wrapped so nothing kills it, like the loops it reports on. A push that fails is
    already swallowed by the gateway; this catch is for the snapshot itself - a database that is
    briefly unwell must cost one copy of a dashboard, not the whole task."""
    global _wake_event
    _wake_event = asyncio.Event()
    logger.info("gp sync state push started")
    try:
        while True:
            try:
                await _push_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("gp sync state push failed")
            try:
                await asyncio.wait_for(_wake_event.wait(), timeout=PUSH_SECONDS)
            except TimeoutError:
                pass
            finally:
                _wake_event.clear()
    finally:
        _wake_event = None
