"""Auto-adopt every GP job as a UC Nexus project (#380).

GP owns jobs. A job that exists there but not here is a project people cannot import a schedule
against, raise a PO on, or ship from - so the rule is simply "if it is a job in GP, it is a project in
Nexus", and this service enforces it continuously rather than leaving it to somebody remembering to
adopt one.

That makes manual adoption redundant, which is why the old Adopt GP Job dialog is gone. The only two
writers of a project's identity are now this sync and create_gp_job, and both take the job number from
GP itself, so the invariant the #314 guard defended - no project without a real GP job behind it - is
now structural instead of enforced by a check.

Modelled on gp_outbox_worker: one lifespan task, every iteration wrapped so nothing can kill the loop,
an env kill switch, and a wake() the relay registration path calls so a reconnect syncs at once.
"""

import asyncio
import logging
import os

from sqlalchemy import select

from app.database import SessionLocal
from app.errors import ConflictError, RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import project_repository
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

# Jobs are created by hand in GP a few times a week at most, so this is a backstop, not the main path -
# wake() covers the case that actually matters (a relay coming back), and the admin Sync from GP button
# covers "I just made one and want it now".
POLL_SECONDS = 300.0

_wake_event: asyncio.Event | None = None


def enabled() -> bool:
    """Env kill switch, default on, so the sync can be stopped without a code deploy."""
    return os.getenv("GP_JOB_SYNC_ENABLED", "true").lower() not in ("false", "0", "no")


def wake() -> None:
    """Nudge the loop out of its sleep. Called by /relay-link right after a successful try_register, so
    a reconnect syncs within milliseconds instead of up to POLL_SECONDS later."""
    if _wake_event is not None:
        try:
            _wake_event.set()
        except Exception:  # noqa: BLE001 - never let a wake-up break the caller's request path
            logger.exception("gp job sync: failed to signal the worker")


def _persist_missing(jobs: list[dict]) -> tuple[int, int]:
    """Create a project for every reported job that doesn't have one. Returns (total, adopted).

    Committed per row rather than in one batch: one bad job (a number too long for the column, a
    duplicate racing a create) must not discard the other fourteen. A ConflictError means someone
    else - create_gp_job, or an earlier pass - got there first, which is the expected outcome on every
    pass after the first and not worth logging."""
    with SessionLocal() as session:
        existing = {pid for pid in session.scalars(select(ProjectModel.project_id)).all()}

        total = 0
        adopted = 0
        seen: set[str] = set()
        for job in jobs:
            job_number = str(job.get("job_number") or "").strip()
            if not job_number or job_number in seen:
                continue
            seen.add(job_number)
            total += 1
            if job_number in existing:
                continue

            job_name = str(job.get("job_name") or "").strip() or None
            try:
                project_repository.adopt_gp_job(session, job_number=job_number, job_name=job_name)
                session.commit()
                adopted += 1
            except ConflictError:
                session.rollback()
            except Exception:  # noqa: BLE001 - one unusable job must not stop the rest
                session.rollback()
                logger.exception("gp job sync: could not adopt job %s", job_number)

    return total, adopted


async def run_once() -> tuple[int, int]:
    """One sync pass: read GP's job master through the relay and create the projects that are missing.
    Returns (total, adopted). Raises RelayUnavailableError if no relay is connected - the admin
    Sync from GP button surfaces that, while the loop below simply skips the pass."""
    company = relay_gateway.company
    if not company:
        raise RelayUnavailableError(
            "The GP relay is not connected, so jobs cannot be synced from GP. Start the relay and try again."
        )
    result = await relay_gateway.relay_call(company, "list_jobs")
    jobs = (result or {}).get("jobs") or []
    # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
    return await asyncio.to_thread(_persist_missing, jobs)


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it - a dead sync is silently
    missing projects, which surfaces much later as "why isn't this job in Nexus"."""
    global _wake_event
    _wake_event = asyncio.Event()
    logger.info("gp job sync started")
    while True:
        try:
            if relay_gateway.connected and relay_gateway.company:
                total, adopted = await run_once()
                if adopted:
                    logger.info("gp job sync: adopted %s of %s GP jobs", adopted, total)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("gp job sync iteration failed")

        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=POLL_SECONDS)
        except TimeoutError:
            pass
        finally:
            _wake_event.clear()
