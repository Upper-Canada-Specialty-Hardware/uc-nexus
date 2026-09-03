"""Mirror GP's own purchase orders into local rows (gp-owned-po mirror).

A PO is only real once it is in GP. This service keeps the register a mirror of GP's purchasing module
rather than only the POs Nexus drafted, so a PO created directly in GP - or stranded after a schema
reset - is visible and receivable. Modelled on gp_job_sync: one lifespan task, every iteration wrapped
so nothing kills the loop, an env kill switch, and a wake() the relay reconnect path calls.

Two phases per company, tracked in gp_po_sync_state, and they get SEPARATE SCHEDULES in run_forever
because they have opposite shapes:
  - BACKFILL: walk GP's whole PO history in PONUMBER order, one page at a time, until a short page ends
    it. A finite bulk drain, deliberately throttled (see PAGE_DELAY_SECONDS) because it reads GP's SQL
    server hard and nothing waits on it; it resumes from its stored cursor after any restart. Runs on
    the fast cadence, one batch at a time, rotating over the companies still draining.
  - INCREMENTAL: from then on, re-read the bounded open-PO set (so received/status stay live) plus
    history rows changed since the watermark. Cheap per company, but it never stops, so it runs on the
    slow cadence and takes ONE already-mirrored company in rotation rather than all of them.

Until the workstation relay self-updates to a build advertising the sync_pos op, relay_call fails fast
with RelayOpUnsupportedError and this service no-ops with a log line - so it is safe to deploy ahead of
the relay update (single-PR rollout).
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.errors import RelayBusyError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import gp_po_sync_repository as sync_repo
from app.services import gp_load
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

_env_warned: set[str] = set()


def _env_number(name: str, default, cast, *, minimum):
    """This module's tunables, through the shared parser (gp_load.env_number). Keeps its own `warned`
    set and log prefix so a mistyped GP_PO_SYNC_* variable is reported as this service's problem."""
    return gp_load.env_number(name, default, cast, minimum=minimum, warned=_env_warned, prefix="gp po sync")


# THE INCREMENTAL SCHEDULE. One tick reads ONE already-mirrored company, so the interval and the
# company count together set the load GP carries forever: at the 900s default and the twelve companies
# GP reports since #667, that is one company's open-book read every 15 minutes and each company
# revisited every 3 hours. The old 300s ran EVERY company on EVERY tick - twelve open-book reads every
# five minutes - which is the steady load that sat underneath the backfill and never went away.
# wake() still covers what actually needs to be prompt (a relay reconnect, the admin button).
POLL_SECONDS = _env_number("GP_PO_SYNC_POLL_SECONDS", 900.0, float, minimum=1.0)
# Floor between all-companies sweeps. A wake() fires on every relay reconnect, and the relay does drop
# and re-dial within minutes (#384) - so an unguarded wake path hands a flapping socket the exact load
# the rest of this throttle removes: all twelve companies swept per reconnect. A wake inside this gap
# is downgraded to "run whatever ticks are due, now", which is what a reconnect actually needs.
ALL_COMPANIES_MIN_GAP_SECONDS = _env_number("GP_PO_SYNC_ALL_COMPANIES_MIN_GAP_SECONDS", 300.0, float, minimum=0.0)
# Headers per backfill page. 300 keeps a page's line/receipt reads well inside the relay command
# timeout while still draining company-scale history in a reasonable number of round trips.
PAGE_SIZE = 300
# THE BACKFILL SCHEDULE, which runs on its own cadence alongside the incremental one rather than
# sharing its rotation - the two have opposite shapes (a finite bulk drain vs a permanent trickle) and
# tying them together made whichever was slower set the pace for both.
#
# A backfill page makes the relay read POP10110/POP30110/POP10500 in 1000-PO IN chunks. Drained flat
# out across every company the pass loop pinned the GP SQL server's CPU for fifteen hours. So: a page
# every PAGE_DELAY_SECONDS, at most BACKFILL_MAX_PAGES_PER_PASS pages in a batch, one batch every
# BACKFILL_PASS_DELAY_SECONDS, and the batch goes to the next company still draining in its own round
# robin. At defaults that is one 12-page batch every ~90 seconds (eleven 5s gaps inside the batch, plus
# the 30s between batches), so GP sees at most one page read every five seconds no matter how many
# companies are behind. Eight companies still draining means each gets a batch every ~12 minutes, and a
# company-scale history lands in hours - slow on purpose, since nothing waits on it and the cursor
# survives a restart. Env-tunable so a stuck or over-eager drain is a variable edit, not a deploy.
PAGE_DELAY_SECONDS = _env_number("GP_PO_SYNC_PAGE_DELAY_SECONDS", 5.0, float, minimum=0.0)
BACKFILL_PASS_DELAY_SECONDS = _env_number("GP_PO_SYNC_BACKFILL_PASS_DELAY_SECONDS", 30.0, float, minimum=0.0)
BACKFILL_MAX_PAGES_PER_PASS = _env_number("GP_PO_SYNC_BACKFILL_MAX_PAGES_PER_PASS", 12, int, minimum=1)
# The admin syncGpPos mutation drains only this many pages inline, then wake()s the background loop for
# the rest. A backfill of GP's whole history is tens of minutes; draining it inside one GraphQL request
# would time out at the edge while the server ran on, so the mutation just kicks it and returns.
ADMIN_SYNC_BACKFILL_PAGES = 2
# The incremental read asks for rows modified since the watermark minus a day: GP's modified timestamp
# is effectively day-granular and upserts are idempotent, so the overlap costs nothing and closes the
# gap where a same-day change after the pass would otherwise be missed.
INCREMENTAL_SLACK = timedelta(days=1)

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
    """Drain up to max_pages pages from the stored cursor, pausing PAGE_DELAY_SECONDS between them. The
    result's `backfill_done` tells the loop the history is fully mirrored; `stalled` tells it the cursor
    could not advance this pass (a relay handing back the same keyset, or a page whose leading PO could
    not persist) so it must WAIT rather than treat the backfill as "keep draining immediately" and
    hot-spin relay reads + full-page re-upserts.

    Every page logs one INFO line. The fifteen-hour drain that pinned GP's CPU wrote nothing at all, so
    there was no way to see it running; one line per page is bounded by the page delay and cannot flood."""
    created = updated = skipped = pos_seen = 0
    done = False
    stalled = False
    pages = 0
    pass_started = time.monotonic()
    for page in range(max_pages):
        cursor = await asyncio.to_thread(_load_cursor, company)
        # paced_call waits out whatever the PREVIOUS page earned before issuing this one, so the gap
        # between pages is the pace gp_load computed from that page's real cost, floored at
        # PAGE_DELAY_SECONDS. Waiting before the next op rather than after the last one also means a
        # pass boundary is spaced for free - there is no "last page" special case to get wrong.
        call = await gp_load.paced_call(
            company,
            "sync_pos",
            {"cursor": cursor, "page_size": PAGE_SIZE},
            floor_seconds=PAGE_DELAY_SECONDS,
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
            "stored_cursor=%s relay_ms=%.0f persist_ms=%.0f cpu_ms=%s sql_cpu_pct=%s next_pace=%.1fs",
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
            call["pace"],
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
    """Re-read the open-PO set plus history rows changed since the watermark, and upsert them.

    This is the pass that runs forever, so it logs one INFO line of its own: it is not free (the relay
    reads all of POP10100 plus the changed history rows, then their lines in 1000-PO chunks) and one
    company's worth of it every tick is the whole of the mirror's steady-state cost on GP."""
    watermark = await asyncio.to_thread(_load_watermark, company)
    modified_since = (watermark - INCREMENTAL_SLACK).isoformat() if watermark else "1900-01-01T00:00:00"
    call = await gp_load.paced_call(
        company,
        "sync_pos",
        {"page_size": PAGE_SIZE, "modified_since": modified_since},
        floor_seconds=BACKFILL_PASS_DELAY_SECONDS,
        background=background,
    )
    result = call["result"]
    relay_ms = call["elapsed_ms"]
    pos = (result or {}).get("pos") or []
    persist_started = time.monotonic()
    counts = await asyncio.to_thread(_persist_page, company, pos, None, is_backfill=False)
    persist_ms = (time.monotonic() - persist_started) * 1000
    history = sum(1 for po in pos if (po.get("source_table") or "work") == "history")
    logger.info(
        "gp po sync: %s incremental pass open=%s history_since=%s created=%s updated=%s skipped=%s "
        "relay_ms=%.0f persist_ms=%.0f cpu_ms=%s sql_cpu_pct=%s next_pace=%.1fs",
        company,
        len(pos) - history,
        history,
        counts["created"],
        counts["updated"],
        counts["skipped"],
        relay_ms,
        persist_ms,
        call["cpu_ms"],
        call["sql_cpu_pct"],
        call["pace"],
    )
    return {
        "mode": "incremental",
        "backfill_done": True,
        "created": counts["created"],
        "updated": counts["updated"],
        "skipped": counts["skipped"],
        "pos": len(pos),
    }


def _load_cursor(company: str) -> str | None:
    with SessionLocal() as session:
        state = sync_repo.get_or_create_sync_state(session, company)
        session.commit()
        return state.backfill_cursor


def _load_watermark(company: str) -> datetime | None:
    with SessionLocal() as session:
        state = sync_repo.get_or_create_sync_state(session, company)
        session.commit()
        return state.watermark


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

    ONE COMPANY PER CALL, round robin (_next_company). Every company on every call was twelve open-book
    reads against GP every poll interval, forever, which is the steady-state load the throttle exists to
    remove. `all_companies=True` opts back into covering all of them in one call and belongs to the
    paths where promptness is the point: the background loop uses it for the pass that follows a wake()
    (a relay reconnect), and the admin syncGpPos mutation passes it because a person just pressed a
    button expecting every company to be looked at.

    This is the entry point for those two callers. run_forever's ROUTINE ticks do not come through here
    - they drive _run_backfill and _run_incremental directly, on two separate schedules that this
    function's single-company-then-decide shape cannot express.

    gp_po_sync_state was always one row per company, so each company keeps its own cursor, watermark
    and backfill phase - one company still draining history does not hold another's incremental pass.
    The result's `mode` reads 'backfill' when any company covered by THIS call is still backfilling,
    which is what the loop keys its short between-pass wait off.

    `background` marks these reads as timer-driven on the wire, which is the ONLY thing the relay's
    busy gate keys on. It defaults FALSE so the admin Sync from GP button - the one caller that is a
    person waiting - is served rather than refused; run_forever passes True for its own sweeps.

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
                result = await _run_incremental(company, background=background)
            else:
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
        "mode": "backfill" if "backfill" in modes else "incremental",
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


async def _backfill_tick(draining: list[str], stalled: set[str], idle_until: float) -> float:
    """One backfill batch for the next company still draining. Returns when the next batch is due.

    With nothing left to drain (or nothing left that is not stalled) the schedule parks on the
    incremental cadence rather than probing every pass delay forever - the phase read is cheap, but a
    query every 30 seconds for the rest of the process's life is not nothing, and the moment anything
    needs draining again the next tick picks it straight back up."""
    drainable = [c for c in draining if c not in stalled]
    if not drainable:
        return max(idle_until, time.monotonic() + BACKFILL_PASS_DELAY_SECONDS)
    company = _next_company(drainable, key="backfill")
    result = await _run_backfill(company, max_pages=BACKFILL_MAX_PAGES_PER_PASS)
    _log_pass(result)
    if result.get("stalled"):
        stalled.add(company)
    return time.monotonic() + BACKFILL_PASS_DELAY_SECONDS


async def _incremental_tick(mirrored: list[str]) -> None:
    """One incremental pass for the next company whose history is already mirrored. A company still
    backfilling is skipped here: its open POs are inside the history it is drawing down anyway, and
    reading them twice would double this schedule's cost for no new rows."""
    if not mirrored:
        return
    _log_pass(await _run_incremental(_next_company(mirrored, key="incremental")))


def _defer(next_incremental_at: float) -> tuple[float, float]:
    """Push both schedules out after a failed tick. Without this a deadline that never advanced is due
    again immediately, so a persistently failing pass (a relay that keeps timing out) would spin."""
    now = time.monotonic()
    return now + BACKFILL_PASS_DELAY_SECONDS, max(next_incremental_at, now + BACKFILL_PASS_DELAY_SECONDS)


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it.

    TWO SCHEDULES, one task, and never more than one relay op in flight because both run inline here:

      - INCREMENTAL, every POLL_SECONDS: one already-mirrored company, round robin. This one never
        ends, so its cost is the mirror's permanent footprint on GP.
      - BACKFILL, every BACKFILL_PASS_DELAY_SECONDS while any company is still draining: one batch of
        BACKFILL_MAX_PAGES_PER_PASS pages for the next such company, its own round robin. This one
        finishes, and wants to finish faster than the incremental cadence would ever allow.

    They were one rotation before, which made the tail of a backfill crawl: with eleven companies done
    and one draining, that company only got a batch when the rotation reached it, once every eleven
    poll intervals. Separate deadlines fix that without either schedule pushing the other around. The
    loop sleeps until whichever is due next; wake() cuts the sleep short and promotes the next pass to
    all-companies, as does startup, because in both cases nothing has been read yet. That promotion is
    floored at ALL_COMPANIES_MIN_GAP_SECONDS, so a flapping relay cannot turn its reconnects into a
    sweep of every company each time; a wake inside the gap just makes both schedules due immediately.

    A company whose batch could not advance its cursor is held out of the backfill rotation until the
    next incremental tick, which is the old anti-hot-spin rule made per company: a stalled company is
    retried on the poll cadence instead of every pass delay, and the others keep draining meanwhile.

    Above all of that sits gp_load: while it says GP is too busy, NO tick runs at all - the loop only
    probes the server until it recovers. Both delays are floors now, not the actual spacing; what
    decides how long a gap really is comes from what the last read cost the server."""
    global _wake_event, _loop
    _wake_event = asyncio.Event()
    _loop = asyncio.get_running_loop()
    logger.info("gp po sync started")
    # Startup is a wake: nothing has been mirrored this process, so the first pass covers everything.
    run_all = True
    next_incremental_at = 0.0
    next_backfill_at = 0.0
    # When the last all-companies sweep STARTED. None until the startup one, which is never rate-limited.
    last_all_at: float | None = None
    stalled: set[str] = set()
    try:
        while True:
            try:
                if not relay_gateway.connected:
                    # No relay, nothing to schedule against. run_all is deliberately NOT consumed - the
                    # all-companies pass it promises has not happened yet, and the reconnect that makes
                    # it possible will wake() anyway.
                    now = time.monotonic()
                    next_incremental_at = next_backfill_at = now + POLL_SECONDS
                elif not relay_gateway.companies:
                    # Connected, but the hello frame carrying the company list has not been read yet.
                    # /relay-link calls wake() the instant try_register succeeds, which is BEFORE that
                    # frame arrives - so this is the normal state for the first moments of EVERY
                    # connection, and parking it on POLL_SECONDS is what left a freshly connected mirror
                    # silent for fifteen minutes on 2026-09-03. A short grace instead; the read loop
                    # also wakes us the moment the hello lands, so the grace is only the backstop.
                    now = time.monotonic()
                    next_incremental_at = next_backfill_at = now + gp_load.HELLO_GRACE_SECONDS
                elif gp_load.paused():
                    # GP is above the ceiling. No ticks at all - just ask the server how it is doing,
                    # when a probe is due, and sleep until the next one. run_all is not consumed here
                    # either: the sweep it promises still has to happen once the server recovers.
                    await gp_load.probe()
                    now = time.monotonic()
                    next_incremental_at = next_backfill_at = gp_load.policy.probe_due_at() if gp_load.paused() else now
                elif run_all:
                    run_all = False
                    now = time.monotonic()
                    since = None if last_all_at is None else now - last_all_at
                    if since is not None and since < ALL_COMPANIES_MIN_GAP_SECONDS:
                        # A reconnect this soon after a sweep has nothing new to sweep. Make both
                        # schedules due instead, so the wake still gets a prompt read out of the loop.
                        logger.info(
                            "gp po sync: wake %.0fs after the last all-companies pass (min gap %ss); "
                            "running the due ticks instead of sweeping every company",
                            since,
                            ALL_COMPANIES_MIN_GAP_SECONDS,
                        )
                        next_incremental_at = next_backfill_at = now
                    else:
                        # Stamped BEFORE the pass, not after: the gap is between sweeps starting, so a
                        # long sweep cannot earn a second one the moment it finishes.
                        last_all_at = now
                        _log_pass(await run_once(all_companies=True, background=True))
                        stalled.clear()
                        now = time.monotonic()
                        next_incremental_at = now + POLL_SECONDS
                        next_backfill_at = now + BACKFILL_PASS_DELAY_SECONDS
                else:
                    now = time.monotonic()
                    backfill_due = now >= next_backfill_at
                    incremental_due = now >= next_incremental_at
                    if backfill_due or incremental_due:
                        draining, mirrored = await asyncio.to_thread(_backfill_phase, relay_gateway.companies)
                        if backfill_due:
                            next_backfill_at = await _backfill_tick(draining, stalled, next_incremental_at)
                        if incremental_due:
                            await _incremental_tick(mirrored)
                            # A stalled company gets its retry on the poll cadence, not the pass delay.
                            stalled.clear()
                            next_incremental_at = time.monotonic() + POLL_SECONDS
            except asyncio.CancelledError:
                raise
            except RelayBusyError:
                # gp_load is paused by the time this lands; the paused branch above takes it from here.
                # No _defer: the probe schedule, not the pass delay, owns the timing now.
                next_backfill_at = next_incremental_at = gp_load.policy.probe_due_at()
            except (RelayUnavailableError, RelayTimeoutError) as e:
                logger.info("gp po sync: relay unavailable this pass (%s); retrying later", e.message)
                next_backfill_at, next_incremental_at = _defer(next_incremental_at)
            except Exception:  # noqa: BLE001
                logger.exception("gp po sync iteration failed")
                next_backfill_at, next_incremental_at = _defer(next_incremental_at)

            if await _wait(max(0.0, min(next_incremental_at, next_backfill_at) - time.monotonic())):
                run_all = True
    finally:
        _loop = None
        _wake_event = None
