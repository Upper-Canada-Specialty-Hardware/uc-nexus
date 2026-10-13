"""Demo mode mutations (#1608): turning it on and off, and resetting the demo company.

Who may do what was ruled on the issue:

  - a UC NEXUS ADMIN or TENANT OWNER turns demo mode on for themselves (`setMyDemoMode`);
  - anybody in demo mode may turn it off again, whatever their roles - leaving must never need a
    role somebody might not have;
  - a UC NEXUS ADMIN turns it on or off for any account (`updateUserDemoMode`), which is how a
    product owner holding neither role gets in;
  - a TENANT OWNER or UC NEXUS ADMIN who is in demo mode resets the demo company (`resetDemoData`).

Turning demo mode on seeds the demo company the first time anybody does, so there is always a starting
state to walk into.
"""

import asyncio

import strawberry

from app.auth import (
    TENANT_OWNERS,
    ForbiddenError,
    caller_roles,
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
        """Turn demo mode on or off for the caller's own account.

        On is for a TENANT OWNER or UC NEXUS ADMIN; off is for anybody. The demo company is seeded on the
        way in when it never has been. The account's real company, roles and buyer identity are left as
        they are, so turning it off puts the caller back exactly where they were."""
        user_id = current_user(info)["user_id"]
        if enabled:
            if not TENANT_OWNERS & set(await asyncio.to_thread(caller_roles, info.context)):
                raise ForbiddenError(f"{' or '.join(sorted(TENANT_OWNERS))} role required to turn on demo mode")
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
