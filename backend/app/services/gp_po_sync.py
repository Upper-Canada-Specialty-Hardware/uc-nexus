"""Mirror GP's own purchase orders into local rows (gp-owned-po mirror).

A PO is only real once it is in GP. This service keeps the register a mirror of GP's purchasing module
rather than only the POs Nexus drafted, so a PO created directly in GP - or stranded after a schema
reset - is visible and receivable. Modelled on gp_job_sync: one lifespan task, every iteration wrapped
so nothing kills the loop, an env kill switch, and a wake() the relay reconnect path calls.

Two phases per company, tracked in gp_po_sync_state:
  - BACKFILL: walk GP's whole PO history in PONUMBER order, one page at a time, until a short page ends
    it. This is the one-time heavy pull (tens of minutes at company scale) and resumes from its stored
    cursor after any restart.
  - INCREMENTAL: from then on, re-read the bounded open-PO set (so received/status stay live) plus
    history rows changed since the watermark. Cheap; runs on the poll timer and on relay reconnect.

Until the workstation relay self-updates to a build advertising the sync_pos op, relay_call fails fast
with RelayOpUnsupportedError and this service no-ops with a log line - so it is safe to deploy ahead of
the relay update (single-PR rollout).
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.errors import RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import gp_po_sync_repository as sync_repo
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

# Open POs are re-read live each incremental pass, and buyers create POs in GP continuously, so a
# backstop timer of a few minutes is right - wake() covers a relay reconnect, this covers steady state.
POLL_SECONDS = 300.0
# Headers per backfill page. 300 keeps a page's line/receipt reads well inside the relay command
# timeout while still draining company-scale history in a reasonable number of round trips.
PAGE_SIZE = 300
# A single run_once drains at most this many backfill pages before returning, so one pass is bounded
# and interruptible; the loop then continues immediately (no poll wait) until the backfill is done.
BACKFILL_MAX_PAGES_PER_PASS = 500
# The incremental read asks for rows modified since the watermark minus a day: GP's modified timestamp
# is effectively day-granular and upserts are idempotent, so the overlap costs nothing and closes the
# gap where a same-day change after the pass would otherwise be missed.
INCREMENTAL_SLACK = timedelta(days=1)

_wake_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None


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


def _load_project_map(session) -> dict:
    """{GP job number -> Nexus project.id} for job matching. A mirrored PO whose lines agree on one job
    that is in here receives into that project's inventory; anything else is stock."""
    rows = session.execute(select(ProjectModel.project_id, ProjectModel.id)).all()
    return {job: pid for job, pid in rows}


def _persist_page(company: str, pos: list[dict], next_cursor: str | None, *, is_backfill: bool) -> dict:
    """Upsert one page of GP POs and advance the sync state. Runs in a worker thread - the relay socket
    lives on the event loop and must not block on Postgres. Returns per-page counts."""
    created = updated = skipped = 0
    latest: datetime | None = None
    with SessionLocal() as session:
        project_map = _load_project_map(session)
        for po in pos:
            try:
                action = sync_repo.upsert_mirrored_po(session, company, po, project_map)
            except Exception:  # noqa: BLE001 - one bad PO must not abort the whole page
                session.rollback()
                logger.exception("gp po sync: failed to upsert PO %s", po.get("po_number"))
                skipped += 1
                continue
            created += action == "created"
            updated += action == "updated"
            skipped += action == "skipped"
            modified = po.get("modified_at")
            if modified:
                try:
                    ts = datetime.fromisoformat(modified)
                    latest = ts if latest is None or ts > latest else latest
                except ValueError:
                    pass
        if is_backfill:
            sync_repo.advance_backfill(session, company, next_cursor=next_cursor)
        if latest is not None:
            sync_repo.set_watermark(session, company, latest)
        session.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


async def _run_backfill(company: str) -> dict:
    """Drain up to BACKFILL_MAX_PAGES_PER_PASS pages from the stored cursor. Returns a result whose
    backfill_done tells the loop whether to keep going immediately."""
    created = updated = skipped = pos_seen = 0
    done = False
    for _ in range(BACKFILL_MAX_PAGES_PER_PASS):
        cursor = await asyncio.to_thread(_load_cursor, company)
        result = await relay_gateway.relay_call(company, "sync_pos", {"cursor": cursor, "page_size": PAGE_SIZE})
        pos = (result or {}).get("pos") or []
        next_cursor = (result or {}).get("next_cursor")
        counts = await asyncio.to_thread(_persist_page, company, pos, next_cursor, is_backfill=True)
        created += counts["created"]
        updated += counts["updated"]
        skipped += counts["skipped"]
        pos_seen += len(pos)
        if next_cursor is None:
            done = True
            break
        # Anti-stall: a relay that keeps handing back the same cursor would loop forever. Cursor is the
        # last PONUMBER of the page, so it must advance; if it did not, stop and let the next pass retry.
        if next_cursor == cursor:
            logger.warning("gp po sync: backfill cursor did not advance past %s; stopping this pass", cursor)
            break
    if done:
        logger.info("gp po sync: backfill complete for %s (created=%s updated=%s)", company, created, updated)
    return {"mode": "backfill", "backfill_done": done, "created": created, "updated": updated, "pos": pos_seen}


async def _run_incremental(company: str) -> dict:
    """Re-read the open-PO set plus history rows changed since the watermark, and upsert them."""
    watermark = await asyncio.to_thread(_load_watermark, company)
    modified_since = (watermark - INCREMENTAL_SLACK).isoformat() if watermark else "1900-01-01T00:00:00"
    result = await relay_gateway.relay_call(
        company, "sync_pos", {"page_size": PAGE_SIZE, "modified_since": modified_since}
    )
    pos = (result or {}).get("pos") or []
    counts = await asyncio.to_thread(_persist_page, company, pos, None, is_backfill=False)
    return {"mode": "incremental", "backfill_done": True, **counts, "pos": len(pos)}


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


async def run_once() -> dict:
    """One sync pass: backfill a batch of pages if history is not fully mirrored yet, otherwise run one
    incremental pass. Returns a result dict (mode, counts, backfill_done).

    Raises RelayUnavailableError if no relay is connected. Returns a no-op result (mode 'unsupported')
    when the connected relay is too old to serve sync_pos, so the admin button and the loop both
    degrade cleanly until the relay updates."""
    company = relay_gateway.company
    if not company:
        raise RelayUnavailableError(
            "The GP relay is not connected, so purchase orders cannot be mirrored from GP. "
            "Start the relay and try again."
        )
    try:
        if await asyncio.to_thread(_backfill_done, company):
            return await _run_incremental(company)
        return await _run_backfill(company)
    except RelayOpUnsupportedError:
        logger.info("gp po sync: connected relay does not support sync_pos yet; skipping until it updates")
        return {"mode": "unsupported", "backfill_done": False, "created": 0, "updated": 0, "pos": 0}


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it. While the backfill is
    still draining it loops immediately (no poll wait) so the one-time history pull finishes promptly."""
    global _wake_event, _loop
    _wake_event = asyncio.Event()
    _loop = asyncio.get_running_loop()
    logger.info("gp po sync started")
    try:
        while True:
            backfilling = False
            try:
                if relay_gateway.connected and relay_gateway.company:
                    result = await run_once()
                    if result.get("created") or result.get("updated"):
                        logger.info(
                            "gp po sync: %s pass mirrored %s new / %s updated POs",
                            result.get("mode"),
                            result.get("created"),
                            result.get("updated"),
                        )
                    backfilling = result.get("mode") == "backfill" and not result.get("backfill_done")
            except asyncio.CancelledError:
                raise
            except (RelayUnavailableError, RelayTimeoutError) as e:
                logger.info("gp po sync: relay unavailable this pass (%s); retrying later", e.message)
            except Exception:  # noqa: BLE001
                logger.exception("gp po sync iteration failed")

            if backfilling:
                # More history to drain - keep going without waiting out the poll interval.
                continue

            try:
                await asyncio.wait_for(_wake_event.wait(), timeout=POLL_SECONDS)
            except TimeoutError:
                pass
            finally:
                _wake_event.clear()
    finally:
        _loop = None
        _wake_event = None
