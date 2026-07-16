"""Clerk user queries + mutations."""

import strawberry

from app.repositories import user_repository

from .types import ClerkUser


@strawberry.type
class UserQueries:
    @strawberry.field
    def users(self) -> list[ClerkUser]:
        results = user_repository.list_users()
        return [
            ClerkUser(
                id=u["id"],
                first_name=u["first_name"],
                last_name=u["last_name"],
                email=u["email"],
                roles=u["roles"],
                image_url=u["image_url"],
            )
            for u in results
        ]


@strawberry.type
class UserMutations:
    @strawberry.mutation
    def update_user_roles(self, user_id: str, roles: list[str]) -> ClerkUser:
        result = user_repository.update_user_roles(user_id, roles)
        return ClerkUser(
            id=result["id"],
            first_name=result["first_name"],
            last_name=result["last_name"],
            email=result["email"],
            roles=result["roles"],
            image_url=result["image_url"],
        )
