"""Clerk user queries + mutations.

Every resolver here is Admin/Manager-gated (#415). `updateUserRoles` is the grant path for
`Admin/Manager` itself - the role that gates relay provisioning, relay deletion, buyer assignments,
`createGpJob` and `createGpBuyer` - so an ungated copy let any caller mint the role that opens all of
them. `users` is gated for the same reason a roster is not public: it returns every account's email,
roles and GP buyer id. The three writes are only ever issued by the admin User Management page.

The requirement itself lives in ROOT_FIELD_POLICY (app/auth_policy.py) since #423, not in these
bodies - which is why nothing below opens with a gate call.

The one exception is `updateUserRoles`' own DB-Admin guard (`_enforce_db_admin_grant_rules`): the
Admin/Manager gate in the policy table makes the field admin-only, but "DB Admin" is a tier ABOVE
Admin/Manager, so who may grant it is a property of the ARGUMENTS (which roles are changing) and the
CALLER, not of the field - the exact case ROOT_FIELD_POLICY cannot express and a body check must.
"""

import strawberry

from app.auth import ADMIN_ROLE, DB_ADMIN_ROLE, ForbiddenError, caller_roles, invalidate_display_name, user_roster
from app.repositories import user_repository

from .converters import clerk_user_to_type
from .types import ClerkUser


def _enforce_db_admin_grant_rules(info: strawberry.Info, *, target_user_id: str, new_roles: list[str]) -> None:
    """Keep the "DB Admin" tier exclusive and stacked, for every caller of `updateUserRoles`.

    Two invariants, enforced in the backend rather than left to the User Management UI:

    1. STACKING: a roles list carrying "DB Admin" without "Admin/Manager" is refused for everyone.
       The db-access page lives inside the Admin/Manager-gated admin shell, so a standalone DB Admin
       could reach neither the page nor the roster its mint dialog reads. This also stops an admin
       from stripping Admin/Manager off a DB Admin and stranding them.
    2. GRANT: only a DB Admin may add or remove "DB Admin". `updateUserRoles` is Admin/Manager-gated,
       so without this any admin could hand themselves the tier and walk in - exclusive in name only.

    The caller's roles come from the per-request memo the gate already filled (Admin/Manager-gated,
    so it resolved them), meaning a DB-Admin caller costs no extra Clerk call. Detecting an add or
    remove needs the TARGET's current roles, so that one read happens only when the caller is not a
    DB Admin - the only case where the change is not already permitted.
    """
    new = set(new_roles)
    if DB_ADMIN_ROLE in new and ADMIN_ROLE not in new:
        raise ForbiddenError(f"{DB_ADMIN_ROLE} requires {ADMIN_ROLE}; it cannot be held on its own")

    if DB_ADMIN_ROLE in caller_roles(info.context):
        return  # a DB Admin may add or remove the tier freely (the stacking check above still bound them)

    current = set(user_repository.get_user_roles(target_user_id))
    if (DB_ADMIN_ROLE in new) != (DB_ADMIN_ROLE in current):
        raise ForbiddenError(f"only a {DB_ADMIN_ROLE} may grant or remove {DB_ADMIN_ROLE}")


@strawberry.type
class UserQueries:
    @strawberry.field
    def users(self, info: strawberry.Info) -> list[ClerkUser]:
        """The whole Clerk roster, for the admin User Management page.

        Reads the request-scoped roster the gate already fetched to check this caller holds
        Admin/Manager (ROSTER_BACKED in app/auth_policy.py), so authorizing the call and answering
        it share one trip to Clerk."""
        return [clerk_user_to_type(u) for u in user_roster(info.context)]


@strawberry.type
class UserMutations:
    @strawberry.mutation
    def update_user_roles(self, info: strawberry.Info, user_id: str, roles: list[str]) -> ClerkUser:
        """Set a user's roles outright, including granting Admin/Manager. Admin-gated: this is the
        privilege-escalation path, so the gate is the whole protection - nothing downstream re-checks
        who asked.

        The one thing the gate cannot decide is the "DB Admin" tier, which sits above Admin/Manager:
        `_enforce_db_admin_grant_rules` restricts granting/removing it to a DB Admin and refuses a
        standalone one, for every caller."""
        _enforce_db_admin_grant_rules(info, target_user_id=user_id, new_roles=roles)
        return clerk_user_to_type(user_repository.update_user_roles(user_id, roles))

    @strawberry.mutation
    def update_user_name(self, info: strawberry.Info, user_id: str, first_name: str, last_name: str) -> ClerkUser:
        """Issue #240: admin-driven display-name change (Clerk first/last name).

        Drops the cached display name too. Since #427 every audit and history row is stamped with
        `resolve_display_name`, which caches for a few minutes to keep a Clerk round-trip off hot
        write paths; without this the rows would keep naming the old spelling until that expired."""
        updated = clerk_user_to_type(user_repository.update_user_name(user_id, first_name, last_name))
        invalidate_display_name(user_id)
        return updated

    @strawberry.mutation
    def update_user_gp_buyer_id(self, info: strawberry.Info, user_id: str, gp_buyer_id: str | None = None) -> ClerkUser:
        """Issue #216: link a UC Nexus account to the GP BUYERID it acts as (null clears). The PO
        dialog auto-uses the caller's identity and createPo/registerPoInGp enforce it."""
        return clerk_user_to_type(user_repository.update_user_gp_buyer_id(user_id, gp_buyer_id))

    @strawberry.mutation
    def update_user_company(self, info: strawberry.Info, user_id: str, company: str | None = None) -> ClerkUser:
        """#637: assign the GP company this account belongs to - its tenant (null clears).

        Admin-only, and the most consequential of the three writes here after `updateUserRoles`: this
        is what decides which company's projects, POs, inventory and shipments the account can see at
        all. An Admin/Manager is deliberately unscoped by it (`tenant_scope` returns None for them),
        so setting a company on an admin records the affiliation without narrowing what they read."""
        return clerk_user_to_type(user_repository.update_user_company(user_id, company))
