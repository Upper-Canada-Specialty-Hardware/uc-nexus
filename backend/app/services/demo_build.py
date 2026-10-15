"""Building the demo copy of UBC and keeping it current (#1657).

The demo is one persistent company everybody in demo mode shares, so nothing a user does resets it:

  - `ensure_built`: the first time anybody turns demo mode on and there is no demo yet, it is built.
    Every later switch-on walks into the demo as the role-play left it.
  - `start_rebuild`: a UC NEXUS ADMIN rebuilds it from UBC on purpose, wiping every demo user's role-play.
    It runs in the background - a build of every UBC project, the legacy list and UBC's open POs is
    minutes, not a request - and its progress and outcome are recorded under `build` for the admin page.
  - `run_forever`: the nightly sync, at 2am Toronto. Add-only: UBC jobs that now meet the rule become
    demo projects (with a schedule), a UBC schedule lands on a demo project nobody has imported one into,
    and the masters are read again. It never touches inventory, POs, requests, pulls or shipments - those
    are the role-play's.

Both reads of UBC (the legacy list and GP's masters) are made again before a build and before the nightly
sync (`demo_mirror.refresh_sources`); a read that fails is recorded and the last good one is built from.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database import SessionLocal
from app.demo import DEMO_COMPANY, demo_reset_running
from app.errors import ConflictError
from app.models.project import Project
from app.repositories import demo_mirror_state_repository as state
from app.services import demo_gp, demo_mirror, demo_reset

logger = logging.getLogger(__name__)

_TORONTO = ZoneInfo("America/Toronto")

# Kept so a running build is not garbage collected half way: asyncio holds only a weak reference.
_tasks: set[asyncio.Task] = set()


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


async def _build(started_by: str) -> None:
    """Read UBC again, then wipe and build the demo, recording each step's outcome under `build`."""
    _record(state.BUILD, {"started_at": _now(), "started_by": started_by, "running": True}, replace=True)
    try:
        reads = await demo_mirror.refresh_sources()
        await demo_reset.reset()
        _record(
            state.BUILD,
            {
                "finished_at": _now(),
                "running": False,
                "error": None,
                "read_errors": reads,
                **await asyncio.to_thread(_counts),
            },
        )
        logger.info("demo build: done (%s)", started_by)
    except Exception as e:  # noqa: BLE001 - recorded for the admin page; the next build starts afresh
        logger.exception("demo build: failed")
        _record(state.BUILD, {"finished_at": _now(), "running": False, "error": str(e) or type(e).__name__})


def building() -> bool:
    """Whether a build is under way in this process."""
    return demo_reset_running() or any(not t.done() for t in _tasks)


def start_rebuild(started_by: str) -> None:
    """Start a full rebuild in the background. Refused while one runs."""
    if building():
        raise ConflictError("The demo is being built already. Wait for it to finish.")
    task = asyncio.create_task(_build(started_by))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def ensure_built(started_by: str) -> None:
    """The first switch-on's build: when there is no demo yet, read UBC and build it, waiting for it - the
    caller is about to walk into it. When there is one, or somebody else is building it right now, nothing:
    a demo is never rebuilt by switching on."""
    if await asyncio.to_thread(demo_reset.has_demo_data) or building():
        return
    _record(state.BUILD, {"started_at": _now(), "started_by": started_by, "running": True}, replace=True)
    try:
        with SessionLocal() as session:
            never_read = state.get(session, state.GP_MASTERS) is None
        if never_read:
            await demo_mirror.refresh_sources()
        if await demo_reset.reset(only_if_empty=True):
            _record(state.BUILD, {"finished_at": _now(), "running": False, **await asyncio.to_thread(_counts)})
        else:
            _record(state.BUILD, {"running": False})
    except Exception as e:
        _record(state.BUILD, {"finished_at": _now(), "running": False, "error": str(e) or type(e).__name__})
        raise


# --- the nightly sync ---------------------------------------------------------------------------------


async def nightly() -> dict:
    """One nightly sync: read UBC again, then add what is new. Returns what it added."""
    from app.services import demo_seed

    if not await asyncio.to_thread(demo_reset.has_demo_data):
        return {"skipped": "There is no demo to sync yet."}
    reads = await demo_mirror.refresh_sources()
    # Under the build's own lock: a rebuild started meanwhile would wipe what this adds half way.
    with demo_reset.no_reset_running():
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
