"""Demo mode mutations (#1608): turning it on and off, and resetting the demo company.

Who may do what was ruled on the issue:

  - every signed-in user turns demo mode on and off for themselves (`setMyDemoMode`), with no admin
    involved (#1629, replacing #1617's tenant-owner-only rule);
  - a UC NEXUS ADMIN turns it on or off for any account (`updateUserDemoMode`);
  - a TENANT OWNER or UC NEXUS ADMIN who is in demo mode resets the demo company (`resetDemoData`);
  - a UC NEXUS ADMIN loads the legacy inventory export the demo warehouse is seeded from
    (`uploadDemoInventorySnapshot`, #1638). It is the company's real data, so only an admin handles it.

Turning demo mode on seeds the demo company the first time anybody does, so there is always a starting
state to walk into.
"""

import asyncio

import strawberry

from app.auth import (
    ForbiddenError,
    current_user,
    resolve_display_name,
    tenant_scope,
)
from app.database import SessionLocal
from app.demo import DEMO_COMPANY
from app.errors import ValidationError
from app.models.demo_inventory_snapshot import DemoInventorySnapshot
from app.repositories import demo_snapshot_repository, user_repository
from app.services import demo_reset, demo_snapshot

from .converters import clerk_user_to_type
from .types import ClerkUser, DemoInventorySnapshotSummary


def _summary(snapshot: DemoInventorySnapshot) -> DemoInventorySnapshotSummary:
    rows = [demo_snapshot.SnapshotRow.from_dict(r) for r in snapshot.rows]
    entries = demo_snapshot.inventory_entries(rows)
    return DemoInventorySnapshotSummary(
        file_name=snapshot.file_name,
        uploaded_by=snapshot.uploaded_by,
        uploaded_at=snapshot.uploaded_at,
        row_count=snapshot.row_count,
        project_units=sum(e.quantity for e in entries if e.project_number),
        pool_units=sum(e.quantity for e in entries if not e.project_number),
        project_count=len(demo_snapshot.ongoing_projects(rows)),
        schedule_count=len(demo_snapshot.schedules(rows)),
    )


@strawberry.type
class DemoQueries:
    @strawberry.field
    def demo_inventory_snapshot(self, info: strawberry.Info) -> DemoInventorySnapshotSummary | None:
        """UC NEXUS ADMIN: the stored export the demo warehouse is seeded from, or null when none is."""
        with SessionLocal() as session:
            snapshot = demo_snapshot_repository.current(session)
            return _summary(snapshot) if snapshot else None


@strawberry.type
class DemoMutations:
    @strawberry.mutation
    async def set_my_demo_mode(self, info: strawberry.Info, enabled: bool) -> ClerkUser:
        """Turn demo mode on or off for the caller's own account - any signed-in account (#1629).

        Safe for anybody because demo mode narrows what an account reaches rather than widening it: the
        caller is pinned to the demo company, keeps their own roles, and GP is simulated. The demo company
        is seeded on the way in when it never has been. The account's real company, roles and buyer
        identity are left as they are, so turning it off puts the caller back exactly where they were."""
        user_id = current_user(info)["user_id"]
        if enabled:
            await demo_reset.reset(only_if_empty=True)
        return clerk_user_to_type(await asyncio.to_thread(user_repository.update_user_demo_mode, user_id, enabled))

    @strawberry.mutation
    async def update_user_demo_mode(self, info: strawberry.Info, user_id: str, enabled: bool) -> ClerkUser:
        """UC NEXUS ADMIN: turn demo mode on or off for any account."""
        if enabled:
            await demo_reset.reset(only_if_empty=True)
        return clerk_user_to_type(await asyncio.to_thread(user_repository.update_user_demo_mode, user_id, enabled))

    @strawberry.mutation
    async def reset_demo_data(self, info: strawberry.Info) -> bool:
        """Wipe the demo company and seed it again, back to its starting state. Only from inside demo mode,
        so a reset is always something its caller is looking at - and it only ever touches the demo
        company."""
        if await asyncio.to_thread(tenant_scope, info) != DEMO_COMPANY:
            raise ForbiddenError("Turn on demo mode to reset the demo data.")
        await demo_reset.reset()
        return True

    @strawberry.mutation
    def upload_demo_inventory_snapshot(
        self, info: strawberry.Info, file_name: str, csv_text: str
    ) -> DemoInventorySnapshotSummary:
        """UC NEXUS ADMIN: store the legacy inventory export (#1638), replacing the one stored. Only what
        the seed reads is kept. The demo data is not touched until its next reset, which seeds from it."""
        actor = resolve_display_name(current_user(info)["user_id"])
        try:
            rows = demo_snapshot.parse_csv(csv_text)
        except demo_snapshot.SnapshotError as e:
            raise ValidationError(str(e), field="csvText") from e
        with SessionLocal() as session:
            snapshot = demo_snapshot_repository.store(session, file_name=file_name, rows=rows, uploaded_by=actor)
            session.commit()
            session.refresh(snapshot)
            return _summary(snapshot)
