"""Demo mode (#1608): turning it on and off, and the demo copy of UBC behind it (#1657).

Who may do what was ruled on the issues:

  - an account of a UBC company - UBC or its test company TUBC - turns demo mode on and off for itself
    (`setMyDemoMode`, #1629, narrowed to UBC by #1658). UCSH and every other company may not turn it on;
    anybody already in it may always turn it off, so nobody is stuck;
  - a UC NEXUS ADMIN turns it on or off for any account of a UBC company (`updateUserDemoMode`), and
    turns it on for themselves only while working in one;
  - a UC NEXUS ADMIN rebuilds the demo from UBC (`rebuildDemo`), wiping every demo user's role-play, and
    sees what it is built from (`demoMirror`);
  - anybody in demo mode resets it the same way from its banner (`resetDemo`, #1697), and everybody else
    is told it was reset, by whom and when, the next time they are in demo mode (`demoResetStatus`,
    `acknowledgeDemoReset`).

Turning demo mode on builds the demo the first time anybody does, so there is always one to walk into.
"""

import asyncio
from datetime import datetime

import strawberry
from sqlalchemy import func, select

from app.auth import (
    NEXUS_ADMIN_ROLE,
    ForbiddenError,
    admin_acting_company,
    caller_company,
    caller_demo_mode,
    caller_roles,
    current_user,
    resolve_display_name,
)
from app.database import SessionLocal
from app.demo import DEMO_COMPANY, may_use_demo_mode
from app.models.project import Project
from app.repositories import demo_mirror_state_repository as state
from app.repositories import demo_snapshot_repository, user_repository
from app.services import demo_build, demo_mirror, demo_snapshot

from .converters import clerk_user_to_type
from .types import ClerkUser, DemoMirrorStatus, DemoResetNotice, DemoResetStatus, DemoSourceRead

_NOT_UBC = "Demo mode is only for UBC accounts."
_NOT_IN_DEMO = "Only someone in demo mode can reset the demo or read its resets."


def _when(value) -> datetime | None:
    if not value:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _read(data: dict | None, read_at) -> DemoSourceRead:
    data = data or {}
    return DemoSourceRead(
        read_at=_when(read_at),
        attempted_at=_when(data.get("attempted_at")),
        error=data.get("error"),
        reading=bool(data.get("reading")),
    )


def _status() -> DemoMirrorStatus:
    with SessionLocal() as session:
        source = demo_mirror.load_source(session)
        entries = demo_snapshot.inventory_entries(source.rows, source.job_numbers)
        snapshot = demo_snapshot_repository.current(session)
        masters = state.get(session, state.GP_MASTERS) or {}
        build = state.get(session, state.BUILD) or {}
        nightly = state.get(session, state.NIGHTLY) or {}
        demo_projects = session.scalar(select(func.count()).select_from(Project).where(Project.company == DEMO_COMPANY))
        legacy = state.get(session, state.LEGACY_LIST)
    return DemoMirrorStatus(
        source=source.name,
        legacy_list=_read(legacy, snapshot.uploaded_at if snapshot else None),
        legacy_rows=snapshot.row_count if snapshot else 0,
        gp_masters=_read(masters, masters.get("read_at")),
        vendor_count=len(source.masters.get("vendors") or []),
        project_count=len(source.jobs),
        specialties_project_count=len(demo_snapshot.specialties_jobs(source.rows) & source.job_numbers),
        project_units=sum(e.quantity for e in entries if e.project_number),
        pool_units=sum(e.quantity for e in entries if not e.project_number),
        open_po_count=len(source.open_pos),
        demo_project_count=demo_projects or 0,
        building=demo_build.building(),
        build_started_at=_when(build.get("started_at")),
        build_started_by=build.get("started_by"),
        build_finished_at=_when(build.get("finished_at")),
        build_error=build.get("error"),
        nightly_ran_at=_when(nightly.get("ran_at")),
        nightly_error=nightly.get("error") or nightly.get("skipped"),
        nightly_projects_added=list(nightly.get("projects_added") or []),
        nightly_schedules_added=list(nightly.get("schedules_added") or []),
    )


def _reset_status(user_id: str) -> DemoResetStatus:
    with SessionLocal() as session:
        build = state.get(session, state.BUILD) or {}
    building = demo_build.building()
    notice = demo_build.reset_notice(user_id)
    return DemoResetStatus(
        building=building,
        build_started_at=_when(build.get("started_at")) if building else None,
        build_started_by=build.get("started_by") if building else None,
        notice=DemoResetNotice(reset_at=_when(notice["reset_at"]), reset_by=notice["reset_by"]) if notice else None,
    )


def _in_demo_mode(info: strawberry.Info) -> str:
    """The caller's user id, refused unless their account is in demo mode. Not `tenant_scope`: these fields
    must answer while a reset runs, when every demo-scoped read is refused (#1635)."""
    user_id = current_user(info)["user_id"]
    if not caller_demo_mode(info.context):
        raise ForbiddenError(_NOT_IN_DEMO)
    return user_id


def _working_company(info: strawberry.Info) -> str | None:
    """The company the caller works in: an admin's is the one they act in, anybody else's their own."""
    if NEXUS_ADMIN_ROLE in caller_roles(info.context):
        return admin_acting_company(info.context)
    return caller_company(info.context)


@strawberry.type
class DemoQueries:
    @strawberry.field
    async def demo_mirror(self, info: strawberry.Info) -> DemoMirrorStatus:
        """UC NEXUS ADMIN: the demo copy of UBC - what it is built from, and how its last build and nightly
        sync went (#1657)."""
        return await asyncio.to_thread(_status)

    @strawberry.field
    async def demo_reset_status(self, info: strawberry.Info) -> DemoResetStatus:
        """Anybody in demo mode (#1697): whether a reset is running, and the last one they have not been
        told of. Answered while a reset runs, so a tab can wait it out."""
        user_id = _in_demo_mode(info)
        return await asyncio.to_thread(_reset_status, user_id)


@strawberry.type
class DemoMutations:
    @strawberry.mutation
    async def set_my_demo_mode(self, info: strawberry.Info, enabled: bool) -> ClerkUser:
        """Turn demo mode on or off for the caller's own account (#1629). On only for an account working
        in a UBC company (#1658); off for anybody.

        Safe for those because demo mode narrows what an account reaches rather than widening it: the
        caller is pinned to the demo company, keeps their own roles, and GP is simulated. The demo is
        built on the way in when it never has been. The account's real company, roles and buyer identity
        are left as they are, so turning it off puts the caller back exactly where they were."""
        user_id = current_user(info)["user_id"]
        if enabled:
            if not may_use_demo_mode(await asyncio.to_thread(_working_company, info)):
                raise ForbiddenError(_NOT_UBC)
            await demo_build.ensure_built(resolve_display_name(user_id))
        return clerk_user_to_type(await asyncio.to_thread(user_repository.update_user_demo_mode, user_id, enabled))

    @strawberry.mutation
    async def update_user_demo_mode(self, info: strawberry.Info, user_id: str, enabled: bool) -> ClerkUser:
        """UC NEXUS ADMIN: turn demo mode on or off for an account - on only for one of a UBC company."""
        if enabled:
            if not may_use_demo_mode(await asyncio.to_thread(user_repository.get_user_company, user_id)):
                raise ForbiddenError(_NOT_UBC)
            await demo_build.ensure_built(resolve_display_name(current_user(info)["user_id"]))
        return clerk_user_to_type(await asyncio.to_thread(user_repository.update_user_demo_mode, user_id, enabled))

    @strawberry.mutation
    async def rebuild_demo(self, info: strawberry.Info) -> DemoMirrorStatus:
        """UC NEXUS ADMIN: read UBC again and rebuild the demo from it, in the background (#1657). Every demo
        user's role-play is wiped. Refused while a build runs."""
        user_id = current_user(info)["user_id"]
        # #1697: the admin who rebuilt it is the one person not told of it, as for a reset from the banner.
        demo_build.start_rebuild(resolve_display_name(user_id), started_by_id=user_id, kind=demo_build.ADMIN_REBUILD)
        return await asyncio.to_thread(_status)

    @strawberry.mutation
    async def reset_demo(self, info: strawberry.Info) -> DemoResetStatus:
        """Anybody in demo mode (#1697): rebuild the demo from UBC, as the admin rebuild does, wiping every
        demo user's role-play. Everybody else is told the next time they are in demo mode. Refused while a
        build runs."""
        user_id = _in_demo_mode(info)
        demo_build.start_rebuild(resolve_display_name(user_id), started_by_id=user_id, kind=demo_build.DEMO_RESET)
        return await asyncio.to_thread(_reset_status, user_id)

    @strawberry.mutation
    async def acknowledge_demo_reset(self, info: strawberry.Info) -> DemoResetStatus:
        """Anybody in demo mode (#1697): they have seen the last reset's notice."""
        user_id = _in_demo_mode(info)
        await asyncio.to_thread(demo_build.acknowledge_reset, user_id)
        return await asyncio.to_thread(_reset_status, user_id)
