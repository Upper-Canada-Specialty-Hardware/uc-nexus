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
from app.errors import ConflictError, RelayBusyError, RelayTimeoutError, RelayUnavailableError
from app.models.project import Project as ProjectModel
from app.repositories import project_repository
from app.services import gp_load
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

# Jobs are created by hand in GP a few times a week at most, so this is a backstop, not the main path -
# wake() covers the case that actually matters (a relay coming back), and the admin Sync from GP button
# covers "I just made one and want it now".
POLL_SECONDS = 300.0

# How long /admin/reset-data waits for its one forced sync pass. Generous next to relay_call's own 30s
# because this pass also writes a project row per GP job, and the reset is a deliberate manual action
# that nobody is timing - overshooting costs a few seconds, giving up early costs every buyer link.
RESET_SYNC_TIMEOUT_SECONDS = 90.0

# Floor between this service's background reads. Small because a list_jobs is cheap next to a PO page;
# gp_load raises it whenever the server says the read actually cost something.
COMPANY_FLOOR_SECONDS = 1.0

_wake_event: asyncio.Event | None = None

# The loop `run_forever` was scheduled on, which is the loop the relay websocket lives on. Captured so
# a *synchronous* caller in the threadpool can still run a sync pass: `/admin/reset-data` is a sync def
# and must re-adopt every GP job right after it rebuilds the schema, but `run_once` talks to the relay
# over that socket and may only be awaited on its own loop (#410). None until the lifespan task starts,
# and cleared again when it stops - handing a coroutine to a loop that is no longer running never
# completes, so a stale value here would block the reset for the whole timeout and then lie about why.
_loop: asyncio.AbstractEventLoop | None = None


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


def _persist_missing(jobs: list[dict], company: str) -> tuple[int, int]:
    """Create a project for every reported job that doesn't have one IN THIS COMPANY. Returns
    (total, adopted).

    The existing-project set is per company (#637): a job number is only unique within one, so a set
    built across all of them would silently skip adopting UCSH's job 1001 because TUBC already has a
    project of that number.

    Committed per row rather than in one batch: one bad job (a number too long for the column, a
    duplicate racing a create) must not discard the other fourteen. A ConflictError means someone
    else - create_gp_job, or an earlier pass - got there first, which is the expected outcome on every
    pass after the first and not worth logging."""
    with SessionLocal() as session:
        existing = {
            pid for pid in session.scalars(select(ProjectModel.project_id).where(ProjectModel.company == company)).all()
        }

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
                project_repository.adopt_gp_job(session, job_number=job_number, job_name=job_name, company=company)
                session.commit()
                adopted += 1
            except ConflictError:
                session.rollback()
            except Exception:  # noqa: BLE001 - one unusable job must not stop the rest
                session.rollback()
                logger.exception("gp job sync: could not adopt job %s in %s", job_number, company)

    return total, adopted


def _persist_health(jobs: list[dict], company: str) -> int:
    """Stamp the relay's GP setup verdicts onto their projects (#425). Returns how many were stamped.

    Its own session and its own commit, separate from _persist_missing's, so a health stamp that fails
    cannot roll back the adoptions from the same pass. Adoption is the invariant this service exists
    for; the verdict is an annotation on it."""
    verdicts = {
        str(job.get("job_number") or "").strip(): job for job in jobs if str(job.get("job_number") or "").strip()
    }
    if not verdicts:
        return 0
    with SessionLocal() as session:
        stamped = project_repository.stamp_gp_setup_health(session, verdicts, company)
        session.commit()
    return stamped


async def _stamp_setup_health(company: str, *, background: bool = False) -> None:
    """Ask the relay for every job's GP setup verdict and record it (#425).

    Swallows everything. This runs inside the adoption pass and must never cost it: a relay too old
    for the op, a GP read that times out, a malformed answer - all of them leave the existing stamps
    exactly as they were, which is the correct fallback because a stale verdict is still a verdict and
    the alternative (blanking it) would un-quarantine a broken project on a transient failure.

    Logged at info without a traceback for the same reason the pass itself is: relays restart, get
    updated and flap, and a stack trace per flap buries the one that matters."""
    try:
        call = await gp_load.paced_call(
            company, "job_setup_health", floor_seconds=COMPANY_FLOOR_SECONDS, background=background
        )
        jobs = (call["result"] or {}).get("jobs") or []
        stamped = await asyncio.to_thread(_persist_health, jobs, company)
        unhealthy = sum(1 for job in jobs if not job.get("ok"))
        if unhealthy:
            logger.info("gp job sync: %s of %s %s jobs have broken GP setup", unhealthy, stamped, company)
    except Exception as e:  # noqa: BLE001 - a health check must never break job adoption
        logger.info(
            "gp job sync: could not read GP setup health for %s this pass (%s); stamps left as they were",
            company,
            e,
        )


async def check_job_setup_live(company: str, job_number: str) -> dict | None:
    """The live, authoritative GP setup verdict for ONE job (#425), or None when it could not be read.

    The stamped verdict on the project is at most one poll interval old, and registering a PO is the
    moment that gap matters most: the PO commits money to a job, and if the job's cost-code accounts
    broke since the last pass the registration is what makes the unreceivable PO. So the register path
    re-asks GP directly, using the op's single-job filter so the answer costs two indexed reads rather
    than a sweep of the whole job master.

    None means "could not check", NOT "healthy" - the caller decides what to do with that, and the
    register path falls back to the stamped verdict rather than refusing. Bricking PO registration on
    a relay blip while the stamp says healthy would trade a rare failure for a constant one."""
    try:
        result = await relay_gateway.relay_call(company, "job_setup_health", {"job": job_number})
    except Exception as e:  # noqa: BLE001 - an unavailable check is not a failed job
        logger.info("gp setup live check: could not read health for job %s (%s)", job_number, e)
        return None
    jobs = (result or {}).get("jobs") or []
    for job in jobs:
        if str(job.get("job_number") or "").strip() == job_number.strip():
            return job
    # GP does not know this job. Not a setup verdict - job_exists is the check for that, and the relay
    # runs it inside create_po - so this stays "could not check" rather than becoming a refusal here.
    return None


async def run_once(*, background: bool = False) -> tuple[int, int]:
    """One sync pass PER COMPANY the connected relay serves (#637): read GP's job master through the
    relay and create the projects that are missing, then stamp each project with its GP setup verdict
    (#425).

    Returns the (total, adopted) summed across companies. Raises RelayUnavailableError if no relay is
    connected - the admin Sync from GP button surfaces that, while the loop below simply skips the pass.

    A company whose read fails does NOT abort the pass. One company's GP being unreachable or slow is
    not a reason to leave every other company's new jobs unadopted, and the next pass retries it.

    The health check runs AFTER adoption for each company, deliberately: a job GP has just started
    reporting gets its project first and its verdict on the same pass, rather than a pass later.

    `background` marks these reads as timer-driven on the wire, which is what the relay's busy gate
    keys on. It defaults FALSE, so the admin Sync from GP button and the /admin/reset-data re-adoption
    are served rather than refused; run_forever passes True for its own passes."""
    companies = relay_gateway.companies
    if not companies:
        raise RelayUnavailableError(
            "The GP relay is not connected, so jobs cannot be synced from GP. Start the relay and try again."
        )

    total = 0
    adopted = 0
    failures = 0
    for company in companies:
        try:
            # Paced like every other background read (gp_load): the wait before this company's read is
            # whatever the previous one cost the server, which is also what spaces the companies apart.
            call = await gp_load.paced_call(
                company, "list_jobs", floor_seconds=COMPANY_FLOOR_SECONDS, background=background
            )
            jobs = (call["result"] or {}).get("jobs") or []
            # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
            company_total, company_adopted = await asyncio.to_thread(_persist_missing, jobs, company)
            total += company_total
            adopted += company_adopted
            await _stamp_setup_health(company, background=background)
        except asyncio.CancelledError:
            raise
        except RelayBusyError:
            # GP is above the relay's ceiling; the next company would be refused for the same reason.
            # End the pass - gp_load is already paused and run_forever will probe until it clears.
            #
            # Raised rather than counted as a failure: the all-companies-failed branch below would
            # otherwise report "the relay could not read jobs", which names the wrong culprit and the
            # wrong fix. The relay is fine; the server is busy.
            logger.info("gp job sync: GP is too busy for background reads; pass stopped at %s", company)
            raise
        except Exception as e:  # noqa: BLE001 - one company must not cost every other company its pass
            failures += 1
            logger.info("gp job sync: pass for %s failed (%s); other companies continue", company, e)

    if failures and failures == len(companies):
        # Nothing was read at all, which the admin Sync from GP button has to surface as a failure
        # rather than as "0 of 0 jobs".
        raise RelayUnavailableError(
            "The GP relay could not read jobs for any company it serves. Check the relay and try again."
        )
    return total, adopted


def run_once_blocking(timeout: float = RESET_SYNC_TIMEOUT_SECONDS) -> tuple[int, int] | None:
    """One sync pass driven from a worker thread instead of the event loop (#410).

    `/admin/reset-data` is a sync def, so FastAPI runs it in the threadpool - but it has to re-adopt
    every GP job the moment it has rebuilt the schema. Waiting out POLL_SECONDS is not an option there:
    the buyer/project links the reset restores are matched by job number, so until the projects are
    back there is nothing to match and every link drops. `run_once` awaits the relay socket and may
    only be awaited on the loop that owns it, hence the hand-off.

    Returns (total, adopted), or None when no pass could run - sync disabled, no relay connected, the
    relay went away mid-pass, or it did not answer in time. Every one of those is a skip rather than a
    failure: a reset must not fail because GP happened to be unreachable.

    `enabled()` is re-checked here rather than inferred from `_loop` being None. The kill switch and
    the loop handle are two different facts, and a caller that blocks for 90 seconds should not depend
    on the lifespan wiring never changing."""
    loop = _loop
    if not enabled() or loop is None or not loop.is_running() or not relay_gateway.connected:
        return None
    try:
        return asyncio.run_coroutine_threadsafe(run_once(), loop).result(timeout=timeout)
    except (RelayUnavailableError, RelayTimeoutError) as e:
        logger.info("gp job sync: relay unavailable during reset (%s); projects not re-adopted", e.message)
    except TimeoutError:
        # The pass is still running on the loop; it will finish or fail on its own. Only this wait ends.
        logger.warning("gp job sync: pass did not finish within %ss during reset", timeout)
    except Exception:  # noqa: BLE001 - a reset must not 500 on a bad sync
        logger.exception("gp job sync: pass failed during reset")
    return None


async def run_forever() -> None:
    """The lifespan task. Every iteration is wrapped so no error can kill it - a dead sync is silently
    missing projects, which surfaces much later as "why isn't this job in Nexus"."""
    global _wake_event, _loop
    _wake_event = asyncio.Event()
    _loop = asyncio.get_running_loop()
    logger.info("gp job sync started")
    try:
        while True:
            wait_for = POLL_SECONDS
            try:
                if not relay_gateway.connected:
                    pass
                elif not relay_gateway.companies:
                    # Connected, hello not read yet - the state every connection passes through, because
                    # /relay-link wakes this loop before that frame lands. A short grace rather than the
                    # full poll interval; the read loop also wakes us when the hello arrives.
                    wait_for = gp_load.HELLO_GRACE_SECONDS
                elif gp_load.paused():
                    # GP is above the ceiling. Adopting jobs can wait; not adding load cannot.
                    await gp_load.probe()
                    wait_for = gp_load.SERVER_PROBE_SECONDS if gp_load.paused() else 0.0
                else:
                    total, adopted = await run_once(background=True)
                    if adopted:
                        logger.info("gp job sync: adopted %s of %s GP jobs", adopted, total)
            except asyncio.CancelledError:
                raise
            except RelayBusyError:
                # gp_load is paused by the time this lands; the paused branch above takes over next turn.
                wait_for = gp_load.SERVER_PROBE_SECONDS
            except (RelayUnavailableError, RelayTimeoutError) as e:
                # The relay went away between the guard above and the call, or mid-pass. Routine - relays
                # restart, get updated, and flap - and the next tick retries. Logging a traceback for every
                # relay restart would bury a real fault in noise.
                logger.info("gp job sync: relay unavailable this pass (%s); retrying later", e.message)
            except Exception:  # noqa: BLE001
                logger.exception("gp job sync iteration failed")

            try:
                await asyncio.wait_for(_wake_event.wait(), timeout=max(0.0, wait_for))
            except TimeoutError:
                pass
            finally:
                _wake_event.clear()
    finally:
        # Shutdown, or the task being cancelled. Drop the handles so run_once_blocking skips instead of
        # scheduling a coroutine onto a loop that will never run it.
        _loop = None
        _wake_event = None
