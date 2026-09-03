"""Mirror GP's own purchase orders into local rows (gp-owned-po mirror).

A PO is only real once it is in GP. This service keeps the register a mirror of GP's purchasing module
rather than only the POs Nexus drafted, so a PO created directly in GP - or stranded after a schema
reset - is visible and receivable. Modelled on gp_job_sync: one lifespan task, every iteration wrapped
so nothing kills the loop, an env kill switch, and a wake() the relay reconnect path calls.

EVERY request this service makes is bounded and budgeted. It asks GP for at most GP_SYNC_READ_BATCH
purchase orders at a time, and spends those keys from a shared allowance of GP_SYNC_READS_PER_MINUTE
before the request goes out (app/services/gp_load.py). That is the whole throttle: bounded work per
request, a fixed number of reads per minute. Time gaps between requests were tried first and were the
wrong instrument - a gap between two requests that each re-read every open PO in a company is still an
unbounded read, and on 2026-09-03 one such read pinned GP's CPU twice.

Two phases per company, tracked in gp_po_sync_state, on separate schedules in run_forever because they
have opposite shapes:
  - BACKFILL: walk GP's whole PO history in PONUMBER order, a page at a time, until a short page ends
    it. A finite bulk drain that resumes from its stored cursor after any restart. It runs whenever
    the open-book schedule has nothing due, and the budget alone decides how fast.
  - INCREMENTAL: from then on, walk GP's OPEN purchase orders in keyset pages, then re-read by number
    whatever has since left that table (closed, voided, moved to history) - the only way to learn
    about a PO that no open-only page will ever mention again. POLL_SECONDS is the minimum gap between
    consecutive passes of the same company, not a wait between requests.

Until the workstation relay self-updates to a build advertising the sync_pos op, relay_call fails fast
with RelayOpUnsupportedError and this service no-ops with a log line - so it is safe to deploy ahead of
the relay update (single-PR rollout).
"""

import asyncio
import logging
import os
import time
from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.errors import RelayBusyError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import gp_po_sync_repository as sync_repo
from app.services import gp_load, gp_window
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

_env_warned: set[str] = set()


def _env_number(name: str, default, cast, *, minimum):
    """This module's tunables, through the shared parser (gp_load.env_number). Keeps its own `warned`
    set and log prefix so a mistyped GP_PO_SYNC_* variable is reported as this service's problem."""
    return gp_load.env_number(name, default, cast, minimum=minimum, warned=_env_warned, prefix="gp po sync")


# THE INCREMENTAL SCHEDULE. One tick refreshes ONE already-mirrored company's open book, and this is
# the MINIMUM gap between consecutive passes of the same company - not a wait between requests. The
# requests inside a pass are paced by the shared read budget (gp_load), which is what actually bounds
# the load on GP; this only stops a company with a small open book from being re-read continuously.
POLL_SECONDS = _env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0)
# A single background run_once drains at most this many backfill pages before returning, so one pass
# is bounded and the loop can interleave companies. At READ_BATCH keys a page that is 300 POs a pass.
BACKFILL_MAX_PAGES_PER_PASS = _env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1)
# WHEN the history drain is allowed to run. Massive sync jobs may not run during the working day, so
# the backfill - and only the backfill - is confined to a nightly window in Toronto wall-clock time.
# The open-book refresh, the by-number closure fetch and the job sync are bounded and budgeted, so they
# keep running all day. An EMPTY window means no gate at all, which is what a preview environment sets
# to exercise the backfill in the afternoon.
BACKFILL_WINDOW = gp_window.parse(
    os.getenv("GP_PO_SYNC_BACKFILL_WINDOW", gp_window.DEFAULT_WINDOW),
    os.getenv("GP_PO_SYNC_BACKFILL_WINDOW_TZ", gp_window.DEFAULT_TZ),
    warned=_env_warned,
)
# The admin syncGpPos mutation drains only this many pages inline, then wake()s the background loop for
# the rest. A backfill of GP's whole history is hours; draining it inside one GraphQL request would
# time out at the edge while the server ran on, so the mutation just kicks it and returns.
ADMIN_SYNC_BACKFILL_PAGES = 2

_wake_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None

# Where each round robin is up to, keyed by schedule. The backfill and the incremental tick walk
# different (and differently sized) sets of companies, so they cannot share a counter. In-memory on
# purpose: which company happens to go first after a restart does not matter, only that a tick takes
# one of them rather than all of them.
_rotations: dict[str, int] = {}


def _next_company(companies: list[str], *, key: str) -> str:
    """The next company in `key`'s round-robin order. `companies` arrives sorted, so a fresh process
    starts at the first alphabetically and every company gets an equal share of that schedule's ticks.

    The index is taken modulo the current list length, so a company appearing or disappearing between
    ticks shifts the order rather than breaking it - one company may be visited twice or skipped once
    across that change, which the next lap corrects."""
    index = _rotations.get(key, 0)
    _rotations[key] = index + 1
    return companies[index % len(companies)]


# Companies an operator has asked to have refreshed out of turn. The LOOP is the only thing that ever
# walks an open book, so a button press queues here rather than walking inline - see request_refresh.
_requested: set[str] = set()


def request_refresh(company: str) -> None:
    """Ask the loop to refresh this company's open book on its next turn, ahead of the rotation.

    The alternative - walking it inline in the caller - is what this exists to prevent. UBC's open
    book is ~94 pages at one page per 15 seconds, so an inline walk is ~24 minutes inside a GraphQL
    request: the edge times out, the walk carries on in the orphaned request task, and it races the
    loop's own walk over the same `open_book_cursor` row. Two walkers on one cursor lose pages.

    Idempotent, and cheap enough to call from any request path."""
    _requested.add(company)
    wake()


def enabled() -> bool:
    """Env kill switch, default on, so the mirror can be stopped without a code deploy."""
    return os.getenv("GP_PO_SYNC_ENABLED", "true").lower() not in ("false", "0", "no")


def wake() -> None:
    """Nudge the loop out of its sleep. Called by /relay-link right after a successful try_register."""
    if _wake_event is not None:
        try:
            _wake_event.set()
        except Exception:  # noqa: BLE001 - never let a wake-up break the caller's request path
            logger.exception("gp po sync: failed to signal the worker")


def _load_project_map(session, company: str) -> dict:
    """{GP job number -> Nexus project.id} for job matching, WITHIN one company (#637). A mirrored PO
    whose lines agree on one job that is in here receives into that project's inventory; anything else
    is stock.

    Scoped because a job number is only unique within a company: an unscoped map would attribute a
    UCSH purchase order to the TUBC project that happens to share its job number, receiving another
    company's hardware into it."""
    rows = session.execute(
        select(ProjectModel.project_id, ProjectModel.id).where(ProjectModel.company == company)
    ).all()
    return {job: pid for job, pid in rows}


def _persist_page(company: str, pos: list[dict], next_cursor: str | None, *, is_backfill: bool) -> dict:
    """Upsert one page of GP POs and advance the sync state. Runs in a worker thread - the relay socket
    lives on the event loop and must not block on Postgres.

    Each PO is upserted inside its own SAVEPOINT (begin_nested), so a failure rolls back only that PO and
    the page's other upserts still commit at the end. The backfill cursor is advanced only over POs that
    actually persisted: if a PO in the page failed, the cursor is parked at the last consecutively-
    persisted PO (or left untouched when even the first failed) so the next pass re-reads and retries it.
    History is invisible to the incremental phase, so a PO skipped PAST here would be a permanent hole.

    Returns per-page counts plus `stored_cursor` (the keyset written, None when the cursor did not move)
    and `backfill_done`."""
    created = updated = skipped = 0
    latest: datetime | None = None
    all_persisted = True
    last_persisted_cursor: str | None = None
    with SessionLocal() as session:
        project_map = _load_project_map(session, company)
        pending_registration = sync_repo.po_numbers_pending_registration(session, company)
        for po in pos:
            po_number = (po.get("po_number") or "").strip()
            try:
                with session.begin_nested():  # per-PO SAVEPOINT
                    action = sync_repo.upsert_mirrored_po(
                        session, company, po, project_map, pending_registration=pending_registration
                    )
            except Exception:  # noqa: BLE001 - one bad PO must not lose the rest of the page
                logger.exception("gp po sync: failed to upsert PO %s", po.get("po_number"))
                skipped += 1
                all_persisted = False
                continue
            created += action == "created"
            updated += action == "updated"
            skipped += action == "skipped"
            # Advance the resume point only while every PO so far has persisted; the first failure freezes
            # it, so the cursor never moves past an unpersisted PO.
            if all_persisted and po_number:
                last_persisted_cursor = po_number
            modified = po.get("modified_at")
            if modified:
                try:
                    ts = datetime.fromisoformat(modified)
                    latest = ts if latest is None or ts > latest else latest
                except ValueError:
                    pass

        stored_cursor: str | None = None
        done = False
        if is_backfill:
            if all_persisted:
                if next_cursor is None:
                    done = True  # short page, every PO persisted -> history drained
                else:
                    stored_cursor = next_cursor
            else:
                # A PO in this page did not persist: resume from the last one that did (None leaves the
                # cursor untouched, so the next pass re-reads from the same place).
                stored_cursor = last_persisted_cursor
            sync_repo.advance_backfill(session, company, cursor=stored_cursor, done=done)
        if latest is not None:
            sync_repo.set_watermark(session, company, latest)
        session.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "stored_cursor": stored_cursor,
        "backfill_done": done,
    }


async def _run_backfill(company: str, *, max_pages: int, background: bool = True) -> dict:
    """Drain up to max_pages pages of READ_BATCH from the stored cursor. There is no delay between
    pages: each one is charged to the shared read budget before it goes out, and that budget is the
    pace. The result's `backfill_done` tells the loop the history is fully mirrored; `stalled` tells it the cursor
    could not advance this pass (a relay handing back the same keyset, or a page whose leading PO could
    not persist) so it must WAIT rather than treat the backfill as "keep draining immediately" and
    hot-spin relay reads + full-page re-upserts.

    Every page logs one INFO line. The fifteen-hour drain that pinned GP's CPU wrote nothing at all, so
    there was no way to see it running; the budget bounds the rate, so the lines cannot flood."""
    created = updated = skipped = pos_seen = 0
    done = False
    stalled = False
    pages = 0
    pass_started = time.monotonic()
    for page in range(max_pages):
        # Checked before every page, not once per pass: a pass that starts at 04:55 stops at 05:00
        # rather than running on into the morning. The page already in flight finishes and persists
        # its cursor, and the drain picks up from there when the window reopens.
        if not BACKFILL_WINDOW.allows(datetime.utcnow()):
            logger.info(
                "gp po sync: %s backfill paused for the day after %s page(s); window is %s",
                company,
                pages,
                BACKFILL_WINDOW.label,
            )
            break
        cursor = await asyncio.to_thread(_load_cursor, company)
        # paced_call spends READ_BATCH of the shared budget before the request goes out, waiting if
        # the bucket is short. That wait IS the gap between pages - there is no delay of our own, and
        # no "last page" special case, because the debt is left on the bucket for whoever reads next.
        call = await gp_load.paced_call(
            company,
            "sync_pos",
            {"cursor": cursor, "page_size": gp_load.READ_BATCH},
            reads=gp_load.READ_BATCH,
            background=background,
        )
        result = call["result"]
        relay_ms = call["elapsed_ms"]
        pos = (result or {}).get("pos") or []
        next_cursor = (result or {}).get("next_cursor")
        persist_started = time.monotonic()
        counts = await asyncio.to_thread(_persist_page, company, pos, next_cursor, is_backfill=True)
        persist_ms = (time.monotonic() - persist_started) * 1000
        created += counts["created"]
        updated += counts["updated"]
        skipped += counts["skipped"]
        pos_seen += len(pos)
        pages += 1
        logger.info(
            "gp po sync: %s backfill page %s/%s cursor=%s pos=%s created=%s updated=%s skipped=%s "
            "stored_cursor=%s relay_ms=%.0f persist_ms=%.0f cpu_ms=%s sql_cpu_pct=%s waited=%.1fs",
            company,
            page + 1,
            max_pages,
            cursor,
            len(pos),
            counts["created"],
            counts["updated"],
            counts["skipped"],
            counts["stored_cursor"],
            relay_ms,
            persist_ms,
            call["cpu_ms"],
            call["sql_cpu_pct"],
            call["waited"],
        )
        if counts["backfill_done"]:
            done = True
            break
        # The cursor advances only over POs that persisted. If it did not move past the cursor we sent -
        # the relay returned the same keyset, or this page's leading PO failed to persist - stop this pass
        # so run_forever waits out the poll interval instead of re-reading the same page in a tight loop.
        if counts["stored_cursor"] is None or counts["stored_cursor"] == cursor:
            logger.warning("gp po sync: backfill cursor did not advance past %s; pausing this pass", cursor)
            stalled = True
            break
    logger.info(
        "gp po sync: %s backfill pass drained %s page(s) pos=%s created=%s updated=%s skipped=%s "
        "done=%s stalled=%s elapsed_ms=%.0f",
        company,
        pages,
        pos_seen,
        created,
        updated,
        skipped,
        done,
        stalled,
        (time.monotonic() - pass_started) * 1000,
    )
    if done:
        logger.info("gp po sync: backfill complete for %s (created=%s updated=%s)", company, created, updated)
    return {
        "mode": "backfill",
        "backfill_done": done,
        "stalled": stalled,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "pos": pos_seen,
    }


async def _run_incremental(company: str, *, background: bool = True) -> dict:
    """One full refresh of a company's open book, as a walk rather than a single read.

    This used to be one request: "give me every open PO, plus history changed since the watermark".
    That is unbounded work, and on 2026-09-03 it was the thing that pinned GP's CPU twice - UBC's
    2,344 open POs came back in a single statement, and UCSH's timed out at 30 seconds on our side
    while the server carried on executing it. Bounded work per request is the fix, so:

      1. walk GP's OPEN purchase orders in keyset pages of READ_BATCH (`open_only`), upserting each
         page and storing the cursor, until GP hands back a null next_cursor;
      2. then find the POs Nexus still thinks are open that the walk did not see - they have been
         closed, voided, or moved to history, and no open-only page will ever mention them again -
         and re-read exactly those by number, in batches of READ_BATCH.

    Every request is charged to the shared budget before it goes out, so a company with ten times the
    open POs takes ten times as long rather than ten times as much of GP at once. The walk resumes
    from its stored cursor after a restart; step 2 keys off gp_synced_at against the walk's start time,
    so it survives a restart too."""
    started_at = datetime.utcnow()
    cursor, pass_started_at = await asyncio.to_thread(_begin_open_pass, company, started_at)
    created = updated = skipped = pos_seen = 0
    pages = 0
    pass_clock = time.monotonic()

    while True:
        call = await gp_load.paced_call(
            company,
            "sync_pos",
            {"open_only": True, "cursor": cursor, "page_size": gp_load.READ_BATCH},
            reads=gp_load.READ_BATCH,
            background=background,
        )
        result = call["result"] or {}
        pos = result.get("pos") or []
        next_cursor = result.get("next_cursor")
        persist_started = time.monotonic()
        counts = await asyncio.to_thread(_persist_page, company, pos, None, is_backfill=False)
        persist_ms = (time.monotonic() - persist_started) * 1000
        created += counts["created"]
        updated += counts["updated"]
        skipped += counts["skipped"]
        pos_seen += len(pos)
        pages += 1
        await asyncio.to_thread(_advance_open_pass, company, next_cursor)
        logger.info(
            "gp po sync: %s open page %s cursor=%s pos=%s created=%s updated=%s skipped=%s "
            "next_cursor=%s relay_ms=%.0f persist_ms=%.0f cpu_ms=%s sql_cpu_pct=%s waited=%.1fs",
            company,
            pages,
            cursor,
            len(pos),
            counts["created"],
            counts["updated"],
            counts["skipped"],
            next_cursor,
            call["elapsed_ms"],
            persist_ms,
            call["cpu_ms"],
            call["sql_cpu_pct"],
            call["waited"],
        )
        if not next_cursor:
            break
        if next_cursor == cursor:
            # The relay handed back the keyset it was given. Stop rather than walk the same page
            # forever; the next pass re-reads from the stored cursor.
            logger.warning("gp po sync: %s open-book cursor did not advance past %s; ending pass", company, cursor)
            break
        cursor = next_cursor

    closed = await _sweep_closed(company, pass_started_at, background=background)
    await asyncio.to_thread(_finish_open_pass, company)
    logger.info(
        "gp po sync: %s open book refreshed - %s page(s), %s open POs, %s left the open table, "
        "created=%s updated=%s skipped=%s in %.0fms",
        company,
        pages,
        pos_seen,
        closed,
        created,
        updated,
        skipped,
        (time.monotonic() - pass_clock) * 1000,
    )
    return {
        "mode": "incremental",
        "backfill_done": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "pos": pos_seen + closed,
    }


async def _sweep_closed(company: str, pass_started_at: datetime, *, background: bool = True) -> int:
    """Re-read, by number, the POs that were open in Nexus and did not appear in this pass.

    A PO that has left GP's open table is invisible to every open-only page, so without this the
    mirror would keep it GP_REGISTERED forever - the register would show a PO as outstanding months
    after it was received and closed. `read_pos_by_number` finds them in either table by key, which is
    a seek rather than the history scan the old watermark read did.

    Returns how many were re-read. Batched at READ_BATCH, which is also the relay's per-request key
    cap, and each batch is charged its own length rather than a flat page size - a trailing batch of
    three should cost three."""
    stale = await asyncio.to_thread(_po_numbers_left_open, company, pass_started_at)
    if not stale:
        return 0
    logger.info("gp po sync: %s has %s PO(s) that left GP's open table; re-reading them by number", company, len(stale))
    missing: list[str] = []
    for start in range(0, len(stale), gp_load.READ_BATCH):
        batch = stale[start : start + gp_load.READ_BATCH]
        call = await gp_load.paced_call(
            company,
            "read_pos_by_number",
            {"po_numbers": batch},
            reads=len(batch),
            background=background,
        )
        result = call["result"] or {}
        pos = result.get("pos") or []
        missing.extend(result.get("missing") or [])
        await asyncio.to_thread(_persist_page, company, pos, None, is_backfill=False)
    if missing:
        # In NEITHER GP table: deleted outright rather than closed or moved to history. Nothing is
        # changed here - what the register should do with a PO that has vanished from GP is a product
        # decision, not one to make silently in a sweep. The cost of leaving it is that these rows stay
        # in an open stage and are re-read by number on every pass, so the warning names them: one line
        # per pass, capped, so a company with hundreds cannot flood the log.
        logger.warning(
            "gp po sync: %s: %s PO(s) are in neither GP table; left as-is: %s%s",
            company,
            len(missing),
            ", ".join(missing[:20]),
            "..." if len(missing) > 20 else "",
        )
    return len(stale)


def _begin_open_pass(company: str, started_at: datetime) -> tuple[str | None, datetime]:
    with SessionLocal() as session:
        cursor, pass_started_at = sync_repo.begin_open_pass(session, company, started_at)
        session.commit()
        return cursor, pass_started_at


def _advance_open_pass(company: str, cursor: str | None) -> None:
    with SessionLocal() as session:
        sync_repo.advance_open_pass(session, company, cursor)
        session.commit()


def _finish_open_pass(company: str) -> None:
    with SessionLocal() as session:
        sync_repo.finish_open_pass(session, company)
        session.commit()


def _po_numbers_left_open(company: str, since: datetime) -> list[str]:
    with SessionLocal() as session:
        return sync_repo.po_numbers_left_open(session, company, since)


def _load_cursor(company: str) -> str | None:
    with SessionLocal() as session:
        state = sync_repo.get_or_create_sync_state(session, company)
        session.commit()
        return state.backfill_cursor


def _backfill_done(company: str) -> bool:
    with SessionLocal() as session:
        state = sync_repo.get_or_create_sync_state(session, company)
        session.commit()
        return state.backfill_done


def _backfill_phase(companies: list[str]) -> tuple[list[str], list[str]]:
    """(still draining, fully mirrored) for `companies`, in one session. Re-read on every scheduler
    tick rather than cached, so a company that finishes its history drops out of the backfill rotation
    and into the incremental one by itself, and a company GP only just started reporting joins."""
    draining: list[str] = []
    mirrored: list[str] = []
    with SessionLocal() as session:
        for company in companies:
            state = sync_repo.get_or_create_sync_state(session, company)
            (mirrored if state.backfill_done else draining).append(company)
        session.commit()
    return draining, mirrored


async def run_once(
    *, backfill_max_pages: int | None = None, all_companies: bool = False, background: bool = False
) -> dict:
    """One sync pass for ONE of the companies the connected relay serves (#637): backfill a batch of
    pages if that company's history is not fully mirrored yet, otherwise run one incremental pass for
    it. Returns an aggregate result dict (mode, counts, backfill_done, stalled).

    ONE COMPANY PER CALL, round robin (_next_company). `all_companies=True` covers all of them in one
    call and belongs ONLY to the deliberate paths: the admin syncGpPos button and /admin/reset-data,
    where a person is waiting and expects every company to be looked at.

    run_forever NEVER uses it. Sweeping every company on a reconnect is what re-issued two unbounded
    open-book reads minutes after the first of them had already pinned GP's CPU on 2026-09-03; a wake
    now only resumes the schedules where they were. The loop's routine ticks do not come through here
    at all - they drive _run_backfill and _run_incremental directly.

    Either way every request inside draws on the same read budget, so "all companies" is slower here,
    not heavier on GP.

    gp_po_sync_state was always one row per company, so each company keeps its own cursors and backfill
    phase - one company still draining history does not hold another's open-book refresh.

    `background` marks these reads as timer-driven on the wire, which is the ONLY thing the relay's
    busy gate keys on. It defaults FALSE because every remaining caller of this function is a person
    waiting on a button, and those are served rather than refused.

    backfill_max_pages bounds how many backfill pages a single call drains PER COMPANY. None means the
    configured BACKFILL_MAX_PAGES_PER_PASS (read at call time, not bound as a default argument, so the
    env-derived budget is the one that applies); the admin syncGpPos mutation passes a small cap so it
    returns promptly (and wakes the loop to drain the rest) rather than holding one GraphQL request open
    across the whole history.

    Raises RelayUnavailableError if no relay is connected. Returns a no-op result (mode 'unsupported')
    when the connected relay is too old to serve sync_pos, so the admin button and the loop both
    degrade cleanly until the relay updates."""
    max_pages = BACKFILL_MAX_PAGES_PER_PASS if backfill_max_pages is None else backfill_max_pages
    companies = relay_gateway.companies
    if not companies:
        raise RelayUnavailableError(
            "The GP relay is not connected, so purchase orders cannot be mirrored from GP. "
            "Start the relay and try again."
        )
    targets = companies if all_companies else [_next_company(companies, key="adhoc")]

    created = updated = skipped = pos_seen = 0
    modes: list[str] = []
    all_done = True
    any_stalled = False
    for company in targets:
        try:
            if await asyncio.to_thread(_backfill_done, company):
                # QUEUED, never walked here. A mirrored company's open book is a multi-page walk of
                # tens of minutes; running it inside a request would time out at the edge and race the
                # loop for the same cursor. The loop is the only walker.
                request_refresh(company)
                result = {"mode": "queued", "backfill_done": True, "created": 0, "updated": 0, "skipped": 0, "pos": 0}
            else:
                # A backfill batch IS bounded - ADMIN_SYNC_BACKFILL_PAGES pages of READ_BATCH - so it
                # still runs inline and returns something the caller can see.
                result = await _run_backfill(company, max_pages=max_pages, background=background)
        except RelayOpUnsupportedError:
            logger.info("gp po sync: connected relay does not support sync_pos yet; skipping until it updates")
            return {"mode": "unsupported", "backfill_done": False, "created": 0, "updated": 0, "pos": 0}
        except RelayBusyError:
            # GP is above the relay's ceiling. The next company would be refused by the same server for
            # the same reason, so the pass ENDS here rather than working through the list collecting
            # refusals - gp_load is already paused and the loop will probe until it clears.
            #
            # Raised, not swallowed into a 0-created result: run_forever catches it and hands over to
            # its paused branch, and the admin Sync from GP button gets a RELAY_BUSY error saying why
            # nothing happened instead of a silent "0 new / 0 updated" that reads like success.
            # Whatever earlier companies committed stays committed - each has its own session.
            logger.info("gp po sync: GP is too busy for background reads; pass stopped at %s", company)
            raise
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - one company must not cost every other company its pass
            logger.info("gp po sync: pass for %s failed (%s); other companies continue", company, e)
            all_done = False
            continue
        created += result.get("created", 0)
        updated += result.get("updated", 0)
        skipped += result.get("skipped", 0)
        pos_seen += result.get("pos", 0)
        modes.append(result["mode"])
        all_done = all_done and bool(result.get("backfill_done"))
        any_stalled = any_stalled or bool(result.get("stalled"))

    return {
        # 'queued' when every mirrored company was handed to the loop and nothing was drained here.
        "mode": "backfill" if "backfill" in modes else ("queued" if "queued" in modes else "incremental"),
        "backfill_done": all_done,
        "stalled": any_stalled,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "pos": pos_seen,
    }


async def _wait(seconds: float) -> bool:
    """Sleep up to `seconds`. True if wake() cut it short, False if the interval simply elapsed - the
    caller uses that to tell a reconnect (cover every company at once) from a routine tick (take the
    next company on whichever schedule is due)."""
    if _wake_event is None:
        return False
    woken = True
    try:
        await asyncio.wait_for(_wake_event.wait(), timeout=seconds)
    except TimeoutError:
        woken = False
    finally:
        _wake_event.clear()
    return woken


def _log_pass(result: dict) -> None:
    """One line when a pass actually mirrored something. Silence otherwise - the per-page and
    per-company lines inside the passes already say what ran."""
    if result.get("created") or result.get("updated"):
        logger.info(
            "gp po sync: %s pass mirrored %s new / %s updated POs",
            result.get("mode"),
            result.get("created"),
            result.get("updated"),
        )


async def _backfill_tick(draining: list[str], stalled: set[str]) -> bool:
    """One backfill batch for the next company still draining. True if one ran.

    No deadline of its own any more: the read budget is the pace, so the backfill simply takes whatever
    the incremental schedule is not using. A company whose cursor could not advance is held out until
    the next incremental tick clears the set - the old anti-hot-spin rule, per company."""
    drainable = [c for c in draining if c not in stalled]
    if not drainable:
        return False
    company = _next_company(drainable, key="backfill")
    result = await _run_backfill(company, max_pages=BACKFILL_MAX_PAGES_PER_PASS)
    _log_pass(result)
    if result.get("stalled"):
        stalled.add(company)
    return True


async def _incremental_tick(company: str) -> None:
    """One full open-book refresh for a company whose history is already mirrored. A company still
    backfilling is skipped: its open POs are inside the history it is drawing down anyway, and reading
    them twice would double this schedule's cost for no new rows."""
    _log_pass(await _run_incremental(company))


def _next_refresh(mirrored: list[str], last_pass: dict[str, float]) -> str | None:
    """The company whose open book to walk next: anything an operator asked for, then whatever is most
    overdue. None when nothing is waiting.

    A requested company jumps the rotation but is walked by the LOOP, on the loop's budget, exactly
    like any other pass - which is the whole point of queueing it rather than walking it in the
    request that asked for it."""
    asked = sorted(c for c in mirrored if c in _requested)
    if asked:
        return asked[0]
    return _due_for_refresh(mirrored, last_pass)


def _due_for_refresh(mirrored: list[str], last_pass: dict[str, float]) -> str | None:
    """The mirrored company most overdue for an open-book refresh, or None if none is.

    Least-recently-refreshed rather than a rotation counter: the set of due companies changes shape
    every turn as passes complete, and an index taken modulo a shrinking list picks an arbitrary order
    - correct, in that nothing starves, but not one anybody can predict from the logs. Oldest-first is
    the same fairness with an order that can be read. Never refreshed sorts first; ties break on the
    company code so the answer is stable."""
    now = time.monotonic()
    due = [c for c in mirrored if now - last_pass.get(c, float("-inf")) >= POLL_SECONDS]
    if not due:
        return None
    return min(due, key=lambda c: (last_pass.get(c, float("-inf")), c))


def _seconds_until_due(mirrored: list[str], last_pass: dict[str, float]) -> float:
    """How long until the soonest company comes due for a refresh. POLL_SECONDS when nothing is
    mirrored yet, which is simply "check again later"."""
    now = time.monotonic()
    if not mirrored:
        return POLL_SECONDS
    return max(0.0, min(POLL_SECONDS - (now - last_pass.get(c, float("-inf"))) for c in mirrored))


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it.

    TWO SCHEDULES, one task, and never more than one relay op in flight because both run inline here:

      - INCREMENTAL: one already-mirrored company's whole open book, walked in pages. POLL_SECONDS is
        the MINIMUM gap between consecutive passes of the SAME company, not a wait between requests.
      - BACKFILL: a batch of history pages for the next company still draining, run whenever the
        incremental schedule has nothing due AND the nightly window is open. It is the one read big
        enough to be worth keeping out of the working day; everything else is bounded and runs all day.

    Neither has a delay of its own. What paces them is the shared read budget in gp_load - a fixed
    number of PO reads per minute across every company and both syncs - so the loop runs page after
    page as fast as that budget allows and no faster. Time gaps were the wrong instrument: a gap
    between two unbounded requests is still an unbounded read, which is how one open-book re-read
    pinned GP's CPU twice on 2026-09-03.

    There is NO all-companies sweep. A wake() (a relay reconnect, the hello landing) only cuts the
    sleep short so the schedules resume; the rotation carries on where it left off. Sweeping every
    company on every reconnect is what re-issued both of those unbounded reads after the first pin."""
    global _wake_event, _loop
    _wake_event = asyncio.Event()
    _loop = asyncio.get_running_loop()
    logger.info("gp po sync started")
    # Monotonic instant each company's last full open-book pass finished.
    last_pass: dict[str, float] = {}
    stalled: set[str] = set()
    # Whether the "backfill is waiting for its window" line has already been logged. One line per
    # transition, not one per check.
    backfill_asleep = False
    try:
        while True:
            wait_for = POLL_SECONDS
            try:
                if not relay_gateway.connected:
                    pass
                elif not relay_gateway.companies:
                    # Connected, but the hello frame carrying the company list has not been read yet.
                    # /relay-link calls wake() the instant try_register succeeds, which is BEFORE that
                    # frame arrives, so this is the normal state for the first moments of EVERY
                    # connection. A short grace rather than the full poll interval; the read loop also
                    # wakes us the moment the hello lands.
                    wait_for = gp_load.HELLO_GRACE_SECONDS
                elif gp_load.paused():
                    # GP is above the ceiling. No reads at all - just ask how it is doing when a probe
                    # is due, and sleep until the next one.
                    await gp_load.probe()
                    wait_for = (
                        0.0 if not gp_load.paused() else max(0.0, gp_load.policy.probe_due_at() - time.monotonic())
                    )
                else:
                    draining, mirrored = await asyncio.to_thread(_backfill_phase, relay_gateway.companies)
                    now_utc = datetime.utcnow()
                    window_open = BACKFILL_WINDOW.allows(now_utc)
                    drainable = [c for c in draining if c not in stalled]
                    ran = False

                    # INSIDE the window the backfill goes FIRST, and keeps going while anything is
                    # drainable. It has to: a company's open book takes ~24 minutes to walk, which is
                    # longer than POLL_SECONDS, so some company is always due and a refresh-first loop
                    # would never once reach the backfill - not even at 3am. The history drain is
                    # finite work and nobody is reading the register overnight, so letting it own the
                    # window and the register go stale until morning is the right trade. By day the
                    # refresh has the budget to itself.
                    if window_open and drainable:
                        ran = await _backfill_tick(draining, stalled)
                        if ran:
                            # The "window open" line is left to the block below, which is the one place
                            # that clears the flag - clearing it here as well meant the wake-up was
                            # never logged on the turn the drain actually resumed.
                            wait_for = 0.0

                    company = None if ran else _next_refresh(mirrored, last_pass)
                    if company is not None:
                        # The open-book refresh is NOT gated by the window: it is bounded and budgeted,
                        # and its whole point is that the register stays live during the working day.
                        _requested.discard(company)
                        await _incremental_tick(company)
                        last_pass[company] = time.monotonic()
                        stalled.clear()
                        ran = True
                        wait_for = 0.0
                    if not ran:
                        # Nothing due: sleep until the soonest open book ages out, or until the window
                        # reopens if there is history waiting on it - whichever comes first.
                        wait_for = _seconds_until_due(mirrored, last_pass)
                        if draining and not window_open:
                            if not backfill_asleep:
                                backfill_asleep = True
                                logger.info(
                                    "gp po sync: backfill outside window, resumes at %s (window %s)",
                                    BACKFILL_WINDOW.next_open(now_utc).isoformat(timespec="minutes"),
                                    BACKFILL_WINDOW.label,
                                )
                            wait_for = min(wait_for, BACKFILL_WINDOW.seconds_until_open(now_utc))
                    if window_open and backfill_asleep:
                        backfill_asleep = False
                        logger.info(
                            "gp po sync: backfill window open (%s); history drain resumes", BACKFILL_WINDOW.label
                        )
            except asyncio.CancelledError:
                raise
            except RelayBusyError:
                # gp_load is paused by the time this lands; the paused branch above takes over next
                # turn. Its probe schedule, not a delay of ours, owns the timing now.
                wait_for = max(0.0, gp_load.policy.probe_due_at() - time.monotonic())
            except (RelayUnavailableError, RelayTimeoutError) as e:
                logger.info("gp po sync: relay unavailable this pass (%s); retrying later", e.message)
                wait_for = gp_load.HELLO_GRACE_SECONDS
            except Exception:  # noqa: BLE001
                logger.exception("gp po sync iteration failed")
                wait_for = gp_load.HELLO_GRACE_SECONDS

            await _wait(wait_for)
    finally:
        _loop = None
        _wake_event = None
