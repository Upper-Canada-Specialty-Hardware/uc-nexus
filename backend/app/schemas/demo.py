"""Demo mode mutations (#1608): turning it on and off, and resetting the demo company.

Who may do what was ruled on the issue:

  - every signed-in user turns demo mode on and off for themselves (`setMyDemoMode`), with no admin
    involved (#1629, replacing #1617's tenant-owner-only rule);
  - a UC NEXUS ADMIN turns it on or off for any account (`updateUserDemoMode`);
  - a TENANT OWNER or UC NEXUS ADMIN who is in demo mode resets the demo company (`resetDemoData`).

Turning demo mode on seeds the demo company the first time anybody does, so there is always a starting
state to walk into.
"""

import asyncio

import strawberry

from app.auth import (
    ForbiddenError,
    current_user,
    tenant_scope,
)
from app.demo import DEMO_COMPANY
from app.repositories import user_repository
from app.services import demo_reset

from .converters import clerk_user_to_type
from .types import ClerkUser


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
