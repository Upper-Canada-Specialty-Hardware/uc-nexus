"""Building the demo copy of UBC and keeping it current (#1657).

The demo is one persistent company everybody in demo mode shares, so it only starts over when somebody
says so:

  - `ensure_built`: the first time anybody turns demo mode on and there is no demo yet, it is built.
    Every later switch-on walks into the demo as the role-play left it.
  - `start_rebuild`: the demo is rebuilt from UBC on purpose, wiping every demo user's role-play - by a
    UC NEXUS ADMIN from Nexus Admin, or by anybody in demo mode from its banner (#1697). It runs in the
    background - a build of every UBC project, the legacy list and UBC's open POs is minutes, not a
    request - and its progress and outcome are recorded under `build`, with who started it and why.
  - `reset_notice` / `acknowledge_reset`: everybody but the person who reset it is told, once, that the
    demo was reset and when (#1697).
  - `run_forever`: the nightly sync, at 2am Toronto. Add-only: UBC jobs that now meet the rule become
    demo projects (with a schedule), a UBC schedule lands on a demo project nobody has imported one into,
    and the masters are read again. It never touches inventory, POs, requests, pulls or shipments - those
    are the role-play's.

The legacy list is read again before a build - one Graph read, seconds - and UBC's GP masters after it,
in the background: those reads are paced behind every other scheduled GP read, an hour on a busy day, so
a build never waits on them. When they land the demo answers with them from then on, and nothing else
in it changes. The nightly sync reads both. A read that fails is recorded and the last good one stands.
"""

import asyncio
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import SessionLocal
from app.demo import DEMO_COMPANY, demo_reset_running
from app.errors import AppError, ConflictError
from app.models.project import Project
from app.repositories import demo_mirror_state_repository as state
from app.services import demo_gp, demo_mirror, demo_reset

logger = logging.getLogger(__name__)

_TORONTO = ZoneInfo("America/Toronto")

# Kept so a running build is not garbage collected half way: asyncio holds only a weak reference.
_tasks: set[asyncio.Task] = set()
# The GP masters read that follows a build, kept apart: it is not a build, and does not hold one up.
_reads: set[asyncio.Task] = set()
# Whether the nightly sync holds the build's lock in this process.
_nightly_running = False


def _now() -> str:
    return datetime.utcnow().isoformat()


def _record(key: str, changes: dict, *, replace: bool = False) -> None:
    """Write `changes` over what is recorded under `key`, or in place of all of it."""
    with SessionLocal() as session:
        if replace:
            state.put(session, key, changes)
        else:
            state.merge(session, key, changes)
        session.commit()


def _counts() -> dict:
    with SessionLocal() as session:
        projects = session.scalar(select(func.count()).select_from(Project).where(Project.company == DEMO_COMPANY))
    return {"projects": projects or 0}


# Why a build ran, on its record (#1697). The first build is nobody's reset; the other two wipe a demo
# people were working in, so everybody but its starter is told.
FIRST_BUILD = "first"
ADMIN_REBUILD = "rebuild"
DEMO_RESET = "reset"


def _started(started_by: str, started_by_id: str | None, kind: str) -> dict:
    return {
        "started_at": _now(),
        "started_by": started_by,
        "started_by_id": started_by_id,
        "kind": kind,
        "running": True,
    }


async def _build(started_by: str, started_by_id: str | None = None, kind: str = ADMIN_REBUILD) -> None:
    """Read UBC again, then wipe and build the demo, recording each step's outcome under `build`."""
    _record(state.BUILD, _started(started_by, started_by_id, kind), replace=True)
    try:
        list_error = await demo_mirror.refresh_legacy_list()
        await demo_reset.reset()
        _record(
            state.BUILD,
            {
                "finished_at": _now(),
                "running": False,
                "error": None,
                "read_errors": {"list": list_error},
                **await asyncio.to_thread(_counts),
            },
        )
        logger.info("demo build: done (%s)", started_by)
        _read_masters_after()
    except Exception as e:  # noqa: BLE001 - recorded for the admin page; the next build starts afresh
        logger.exception("demo build: failed")
        _record(state.BUILD, {"finished_at": _now(), "running": False, "error": str(e) or type(e).__name__})


def _read_masters_after() -> None:
    """Read UBC's GP masters in the background, unless a read is under way already."""
    if any(not t.done() for t in _reads):
        return
    task = asyncio.create_task(demo_mirror.refresh_gp_masters())
    _reads.add(task)
    task.add_done_callback(_reads.discard)


def building() -> bool:
    """Whether a build is under way in this process."""
    return demo_reset_running() or any(not t.done() for t in _tasks)


def start_rebuild(started_by: str, *, started_by_id: str | None = None, kind: str = ADMIN_REBUILD) -> None:
    """Start a full rebuild in the background. Refused while one runs. `kind` says who asked: an admin's
    rebuild or a demo user's reset; either way the starter is the one person not told of it."""
    if building():
        raise ConflictError("The demo is being built already. Wait for it to finish.")
    if _nightly_running:
        # Refused here and not in `building()`, which every demo tab reads as "a reset is under way": the
        # nightly only adds, so the tabs carry on (#1831). Accepted, the reset would tell every tab it was
        # resetting and then fail on the lock the nightly holds.
        raise ConflictError("The demo's nightly sync is running. Try again in a few minutes.")
    task = asyncio.create_task(_build(started_by, started_by_id, kind))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def reset_notice(user_id: str) -> dict | None:
    """The last reset `user_id` has yet to be told of (#1697), as `{"reset_at", "reset_by"}`, or None.

    None while a build runs or after one that failed (there is nothing settled to report), for the first
    build (it reset nobody's work), for the person who started it, and once they have been told. A build
    recorded before #1697 carries no kind and counts as a reset, since only a rebuild wrote one."""
    with SessionLocal() as session:
        build = state.get(session, state.BUILD) or {}
        seen = state.get(session, state.RESET_SEEN) or {}
    if build.get("running") or not build.get("finished_at") or build.get("error"):
        return None
    if build.get("kind") == FIRST_BUILD:
        return None
    if build.get("started_by_id") and build.get("started_by_id") == user_id:
        return None
    if seen.get(user_id) == build.get("started_at"):
        return None
    return {"reset_at": build["finished_at"], "reset_by": build.get("started_by")}


def build_failure(build: dict) -> dict | None:
    """The last build's failure (#1937), as `{"failed_at", "started_by"}`, or None when it did not fail.

    A rebuild runs in the background, so a failed one reached nobody: every tab waiting it out reloaded
    into a demo the failed seed had wiped (demo_reset.reset wipes what a seed left part way). Told to every
    demo tab until the next build starts, since the demo stays broken until somebody rebuilds it. Not the
    "told once" notice: that is about a reset that worked. The recorded error stays off it, for the reason
    ensure_built keeps it off DEMO_BUILD_FAILED; a UC Nexus Admin reads it under Nexus Admin → Demo."""
    if building() or build.get("running") or not build.get("error"):
        return None
    return {"failed_at": build.get("finished_at"), "started_by": build.get("started_by")}


def acknowledge_reset(user_id: str) -> None:
    """`user_id` has been told of the last build (#1697); `reset_notice` stays quiet for them until the next."""
    with SessionLocal() as session:
        build = state.get(session, state.BUILD) or {}
        # A build under way is not the one they were told of (#1814): marking it seen now would keep them
        # from ever hearing of it once it finishes.
        if build.get("started_at") and not build.get("running"):
            state.merge_locked(session, state.RESET_SEEN, {user_id: build["started_at"]})
            session.commit()


async def ensure_built(started_by: str) -> None:
    """The first switch-on's build: when there is no demo yet, read UBC and build it, waiting for it - the
    caller is about to walk into it. When there is one, or somebody else is building it right now, nothing:
    a demo is never rebuilt by switching on."""
    if await asyncio.to_thread(demo_reset.has_demo_data) or building():
        return
    _record(state.BUILD, _started(started_by, None, FIRST_BUILD), replace=True)
    try:
        with SessionLocal() as session:
            never_read = state.get(session, state.LEGACY_LIST) is None
        if never_read:
            await demo_mirror.refresh_legacy_list()
        if await demo_reset.reset(only_if_empty=True):
            _record(state.BUILD, {"finished_at": _now(), "running": False, **await asyncio.to_thread(_counts)})
            _read_masters_after()
        else:
            _record(state.BUILD, {"running": False})
    except Exception as e:
        _record(state.BUILD, {"finished_at": _now(), "running": False, "error": str(e) or type(e).__name__})
        if isinstance(e, AppError):
            raise
        # #1937: anything else reached the person switching demo mode on as the masked server error, with
        # nothing to say demo mode stayed off because the build failed - nor why.
        # The exception's own text stays in the recorded build error and the log: a database error carries
        # its SQL and UBC's values, a client error internal URLs - not for the person switching it on.
        raise AppError(
            "The demo couldn't be built. A UC Nexus Admin can see why under Nexus Admin → Demo.",
            "DEMO_BUILD_FAILED",
        ) from e


# --- the nightly sync ---------------------------------------------------------------------------------


@contextmanager
def _nightly_holds_the_lock():
    """The build's lock for the nightly sync, said in this process too, so `start_rebuild` refuses a reset."""
    global _nightly_running
    with demo_reset.no_reset_running():
        _nightly_running = True
        try:
            yield
        finally:
            _nightly_running = False


async def nightly() -> dict:
    """One nightly sync: read UBC again, then add what is new. Returns what it added."""
    from app.services import demo_seed

    if not await asyncio.to_thread(demo_reset.has_demo_data):
        return {"skipped": "There is no demo to sync yet."}
    reads = await demo_mirror.refresh_sources()
    # Under the build's own lock: a rebuild started meanwhile would wipe what this adds half way.
    with _nightly_holds_the_lock():
        with SessionLocal() as session:
            source = demo_mirror.load_source(session)
            demo_gp.update_masters(session, source.masters)
            added_jobs = demo_gp.add_jobs(session, source.jobs)
            session.commit()

        demo = demo_seed.nightly_demo()
        if added_jobs:
            await demo.projects_from_gp()
        else:
            await demo.load_projects()
        # A schedule only where nobody has imported one: a project the role-play has worked keeps its own.
        with SessionLocal() as session:
            bare = {
                job for job, project_id in demo.projects.items() if not demo_mirror.has_schedule(session, project_id)
            }
        # Only jobs that are new tonight get a made-up schedule; UBC's own schedules reach any bare project.
        wanted = (bare & set(source.schedules)) | (bare & set(added_jobs))
        scheduled = await demo.import_schedules(source, only=wanted) if wanted else []
    return {"projects_added": added_jobs, "schedules_added": scheduled, "read_errors": reads}


def _seconds_until_next_run(now: datetime | None = None) -> float:
    hour = int(os.getenv("DEMO_NIGHTLY_HOUR", "2"))
    now = now or datetime.now(_TORONTO)
    run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if run <= now:
        run = (run + timedelta(days=1)).replace(hour=hour)
    return (run - now).total_seconds()


def enabled() -> bool:
    """Env kill switch, default on, so the nightly sync can be stopped without a code deploy."""
    return os.getenv("DEMO_NIGHTLY_ENABLED", "true").lower() not in ("false", "0", "no")


async def run_forever() -> None:
    while True:
        await asyncio.sleep(_seconds_until_next_run())
        started = _now()
        try:
            added = await nightly()
            _record(state.NIGHTLY, {"ran_at": started, "finished_at": _now(), "error": None, **added}, replace=True)
            logger.info("demo nightly sync: %s", added)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - recorded; tomorrow's runs again
            logger.exception("demo nightly sync failed")
            _record(
                state.NIGHTLY,
                {"ran_at": started, "finished_at": _now(), "error": str(e) or type(e).__name__},
                replace=True,
            )
