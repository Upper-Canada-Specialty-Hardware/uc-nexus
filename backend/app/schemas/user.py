"""Clerk user queries + mutations.

Every resolver here is Admin/Manager-gated (#415). `updateUserRoles` is the grant path for
`Admin/Manager` itself - the role that gates relay provisioning, relay deletion, buyer assignments,
`createGpJob` and `createGpBuyer` - so an ungated copy let any caller mint the role that opens all of
them. `users` is gated for the same reason a roster is not public: it returns every account's email,
roles and GP buyer id. The three writes are only ever issued by the admin User Management page.
"""

import strawberry

from app.auth import invalidate_display_name, require_admin
from app.repositories import user_repository

from .converters import clerk_user_to_type
from .types import ClerkUser


@strawberry.type
class UserQueries:
    @strawberry.field
    def users(self, info: strawberry.Info) -> list[ClerkUser]:
        require_admin(info)
        return [clerk_user_to_type(u) for u in user_repository.list_users()]


@strawberry.type
class UserMutations:
    @strawberry.mutation
    def update_user_roles(self, info: strawberry.Info, user_id: str, roles: list[str]) -> ClerkUser:
        """Set a user's roles outright, including granting Admin/Manager. Admin-gated: this is the
        privilege-escalation path, so the gate is the whole protection - nothing downstream re-checks
        who asked."""
        require_admin(info)
        return clerk_user_to_type(user_repository.update_user_roles(user_id, roles))

    @strawberry.mutation
    def update_user_name(self, info: strawberry.Info, user_id: str, first_name: str, last_name: str) -> ClerkUser:
        """Issue #240: admin-driven display-name change (Clerk first/last name).

        Drops the cached display name too. Since #427 every audit and history row is stamped with
        `resolve_display_name`, which caches for a few minutes to keep a Clerk round-trip off hot
        write paths; without this the rows would keep naming the old spelling until that expired."""
        require_admin(info)
        updated = clerk_user_to_type(user_repository.update_user_name(user_id, first_name, last_name))
        invalidate_display_name(user_id)
        return updated

    @strawberry.mutation
    def update_user_gp_buyer_id(self, info: strawberry.Info, user_id: str, gp_buyer_id: str | None = None) -> ClerkUser:
        """Issue #216: link a UC Nexus account to the GP BUYERID it acts as (null clears). The PO
        dialog auto-uses the caller's identity and createPo/registerPoInGp enforce it."""
        require_admin(info)
        return clerk_user_to_type(user_repository.update_user_gp_buyer_id(user_id, gp_buyer_id))
