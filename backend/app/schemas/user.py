"""Clerk user queries + mutations.

Four of the five resolvers here are TENANT_OWNERS-gated and one, `updateUserCompany`, is UC NEXUS
ADMIN (#415, #729). `updateUserRoles` is the grant path for the roles every other entry in
ROOT_FIELD_POLICY is gated on, so an ungated copy let any caller mint the role that opens all of
them. `users` is gated for the same reason a roster is not public: it returns every account's email,
roles and GP buyer id. The writes are only ever issued by the Edit User dialog.

The field-level requirement lives in ROOT_FIELD_POLICY (app/auth_policy.py) since #423, not in these
bodies - which is why nothing below opens with a gate call. What the bodies still decide is the part
that is a property of the ARGUMENTS and the CALLER rather than of the field, which the policy table
cannot express:

  - `_enforce_tenant_owner_grant_rules` keeps a TENANT OWNER inside their own company. They run
    their own company's people - module roles, manager roles, TENANT OWNER itself, names and GP
    identities - and nothing else: a target in another company reads as absent, and a roles change
    that would add or remove UC Nexus Admin or DB Admin is refused.
  - `_enforce_db_admin_grant_rules` keeps the "DB Admin" tier exclusive and stacked on UC Nexus
    Admin, for every caller.
"""

import strawberry

from app.auth import (
    DB_ADMIN_ROLE,
    NEXUS_ADMIN_ROLE,
    ForbiddenError,
    caller_roles,
    invalidate_display_name,
    tenant_scope,
    user_roster,
)
from app.errors import NotFoundError
from app.repositories import user_repository

from .converters import clerk_user_to_type
from .types import ClerkUser

# The roles a TENANT OWNER may never hand out or take away. UC Nexus Admin is the role their own
# authority stops at; DB Admin is the tier above it.
_CROSS_TENANT_ROLES = (NEXUS_ADMIN_ROLE, DB_ADMIN_ROLE)


def _require_target_in_scope(info: strawberry.Info, target_user_id: str) -> str | None:
    """Refuse a caller who is editing an account outside their own company, and return their scope.

    NotFoundError rather than ForbiddenError, and for the same reason every by-id check in
    `app/repositories/tenancy.py` answers that way: a forbidden answer confirms the account exists,
    which turns the mutation into an oracle over the whole Clerk roster. An account in another
    company reads as absent.

    None means the caller is a UC NEXUS ADMIN and there is nothing to check - they are the role that
    moves accounts between companies in the first place.
    """
    scope = tenant_scope(info)
    if scope is None:
        return None
    if user_repository.get_user_company(target_user_id) != scope:
        raise NotFoundError("No user with that id")
    return scope


def _enforce_tenant_owner_grant_rules(info: strawberry.Info, *, target_user_id: str, new_roles: list[str]) -> None:
    """Bound what a TENANT OWNER may do with `updateUserRoles` (#729).

    Two limits, and the second is what stops the first being pointless. A TENANT OWNER may only
    touch an account in their own company, and the roles they write may not add or remove UC Nexus
    Admin or DB Admin - without that, granting themselves the cross-tenant role would be one save
    away, and the company boundary would hold only until somebody noticed it.

    Everything else is theirs: module user and manager roles, and TENANT OWNER itself, so a peer can
    be given the same authority without an admin in the loop.

    A UC NEXUS ADMIN passes straight through; `_enforce_db_admin_grant_rules` still binds them.
    """
    if _require_target_in_scope(info, target_user_id) is None:
        return

    new = set(new_roles)
    current = set(user_repository.get_user_roles(target_user_id))
    for role in _CROSS_TENANT_ROLES:
        if (role in new) != (role in current):
            raise ForbiddenError(f"Only a {NEXUS_ADMIN_ROLE} may grant or remove {role}")


def _enforce_db_admin_grant_rules(info: strawberry.Info, *, target_user_id: str, new_roles: list[str]) -> None:
    """Keep the "DB Admin" tier exclusive and stacked, for every caller of `updateUserRoles`.

    Two invariants, enforced in the backend rather than left to the User Management page:

    1. STACKING: a roles list carrying "DB Admin" without "UC Nexus Admin" is refused for everyone.
       The db-access page lives inside the UC Nexus Admin module, so a standalone DB Admin could
       reach neither the page nor the roster its mint dialog reads. This also stops an admin from
       stripping UC Nexus Admin off a DB Admin and stranding them.
    2. GRANT: only a DB Admin may add or remove "DB Admin". A TENANT OWNER is already refused both
       roles by `_enforce_tenant_owner_grant_rules`; this is what stops a UC NEXUS ADMIN handing
       themselves the tier and walking in - exclusive in name only otherwise.

    The caller's roles come from the per-request memo the gate already filled (this field is
    role-gated, so it resolved them), meaning a DB-Admin caller costs no extra Clerk call. Detecting
    an add or remove needs the TARGET's current roles, so that one read happens only when the caller
    is not a DB Admin - the only case where the change is not already permitted.
    """
    new = set(new_roles)
    if DB_ADMIN_ROLE in new and NEXUS_ADMIN_ROLE not in new:
        raise ForbiddenError(f"{DB_ADMIN_ROLE} requires {NEXUS_ADMIN_ROLE}; it cannot be held on its own")

    if DB_ADMIN_ROLE in caller_roles(info.context):
        return  # a DB Admin may add or remove the tier freely (the stacking check above still bound them)

    current = set(user_repository.get_user_roles(target_user_id))
    if (DB_ADMIN_ROLE in new) != (DB_ADMIN_ROLE in current):
        raise ForbiddenError(f"only a {DB_ADMIN_ROLE} may grant or remove {DB_ADMIN_ROLE}")


@strawberry.type
class UserQueries:
    @strawberry.field
    def users(self, info: strawberry.Info) -> list[ClerkUser]:
        """The Clerk roster the Edit User pages work from.

        Reads the request-scoped roster the gate already fetched to check this caller's role
        (ROSTER_BACKED in app/auth_policy.py), so authorizing the call and answering it share one
        trip to Clerk.

        A scoped caller sees only their own company's accounts (#729). The filter is applied to that
        same roster rather than by refetching: Clerk has no server-side filter on publicMetadata, so
        every roster read is the whole list either way, and asking twice would only cost a second
        round trip.

        The stored value is normalized before comparing, the same way `caller_company` and
        `remember_roster_entry` normalize it. A company written into publicMetadata by hand, or by
        an older path, can carry different casing or whitespace, and a raw comparison would let it
        through the filter or drop the caller's own accounts out of it."""
        company = tenant_scope(info)
        roster = user_roster(info.context)
        if company is not None:
            roster = [u for u in roster if user_repository.normalize_company(u.get("company")) == company]
        return [clerk_user_to_type(u) for u in roster]


@strawberry.type
class UserMutations:
    @strawberry.mutation
    def update_user_roles(self, info: strawberry.Info, user_id: str, roles: list[str]) -> ClerkUser:
        """Set a user's roles outright. Role-gated: this is the privilege-escalation path, so the
        gate plus the two body checks are the whole protection - nothing downstream re-checks who
        asked.

        What the gate cannot decide is which roles THIS caller may write, and onto whom.
        `_enforce_tenant_owner_grant_rules` holds a TENANT OWNER to their own company's accounts and
        to the roles below their own; `_enforce_db_admin_grant_rules` restricts granting or removing
        the "DB Admin" tier to a DB Admin and refuses a standalone one, for every caller.

        A roles list without PO User also gives the account's GP buyer identity back, in the same
        write - the repository keeps that pairing (#687 gap 6), so a demotion made anywhere clears
        the identity registerPoInGp gates on."""
        _enforce_tenant_owner_grant_rules(info, target_user_id=user_id, new_roles=roles)
        _enforce_db_admin_grant_rules(info, target_user_id=user_id, new_roles=roles)
        return clerk_user_to_type(user_repository.update_user_roles(user_id, roles))

    @strawberry.mutation
    def update_user_name(self, info: strawberry.Info, user_id: str, first_name: str, last_name: str) -> ClerkUser:
        """Issue #240: a display-name change made for somebody else (Clerk first/last name), and
        only for an account in the caller's own company (#729).

        Drops the cached display name too. Since #427 every audit and history row is stamped with
        `resolve_display_name`, which caches for a few minutes to keep a Clerk round-trip off hot
        write paths; without this the rows would keep naming the old spelling until that expired."""
        _require_target_in_scope(info, user_id)
        updated = clerk_user_to_type(user_repository.update_user_name(user_id, first_name, last_name))
        invalidate_display_name(user_id)
        return updated

    @strawberry.mutation
    def update_user_gp_buyer_id(self, info: strawberry.Info, user_id: str, gp_buyer_id: str | None = None) -> ClerkUser:
        """Issue #216: link a UC Nexus account to the GP BUYERID it acts as (null clears). The PO
        dialog auto-uses the caller's identity and createPo/registerPoInGp enforce it. Refused for
        an account that does not hold PO User (#687 gap 6): the identity is that role's alone, and
        refused for an account outside the caller's own company (#729)."""
        _require_target_in_scope(info, user_id)
        return clerk_user_to_type(user_repository.update_user_gp_buyer_id(user_id, gp_buyer_id))

    @strawberry.mutation
    def update_user_company(self, info: strawberry.Info, user_id: str, company: str | None = None) -> ClerkUser:
        """#637: assign the GP company this account belongs to - its tenant (null clears).

        UC NEXUS ADMIN only, and the most consequential of the writes here after `updateUserRoles`:
        this is what decides which company's projects, POs, inventory and shipments the account can
        see at all. It is the one user-management field a TENANT OWNER may not touch (#729) - the
        boundary they are themselves confined to is not theirs to move. A UC NEXUS ADMIN is
        deliberately unscoped by it (`tenant_scope` returns None for them), so setting a company on
        one records the affiliation without narrowing what they read."""
        return clerk_user_to_type(user_repository.update_user_company(user_id, company))
