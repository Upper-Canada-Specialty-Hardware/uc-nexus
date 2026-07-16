"""Clerk user queries + mutations."""

import strawberry

from app.repositories import user_repository

from .converters import clerk_user_to_type
from .types import ClerkUser


@strawberry.type
class UserQueries:
    @strawberry.field
    def users(self) -> list[ClerkUser]:
        return [clerk_user_to_type(u) for u in user_repository.list_users()]


@strawberry.type
class UserMutations:
    @strawberry.mutation
    def update_user_roles(self, user_id: str, roles: list[str]) -> ClerkUser:
        return clerk_user_to_type(user_repository.update_user_roles(user_id, roles))

    @strawberry.mutation
    def update_user_name(self, user_id: str, first_name: str, last_name: str) -> ClerkUser:
        """Issue #240: admin-driven display-name change (Clerk first/last name)."""
        return clerk_user_to_type(user_repository.update_user_name(user_id, first_name, last_name))

    @strawberry.mutation
    def update_user_gp_buyer_id(self, user_id: str, gp_buyer_id: str | None = None) -> ClerkUser:
        """Issue #216: link a UC Nexus account to the GP BUYERID it acts as (null clears). The PO
        dialog auto-uses the caller's identity and createPo/registerPoInGp enforce it."""
        return clerk_user_to_type(user_repository.update_user_gp_buyer_id(user_id, gp_buyer_id))
