"""Notification queries + mutations.

Each one answers for the caller (#1111): the notifications in their company, addressed to an
audience their roles belong to or to them, with their own read state. See notification_repository.
"""

import uuid

import strawberry

from app.auth import caller_roles, current_user, tenant_scope
from app.database import SessionLocal
from app.repositories import notification_repository

from .converters import notification_to_type
from .types import Notification


def _reader(info: strawberry.Info) -> notification_repository.Reader:
    return notification_repository.Reader(
        user_id=current_user(info)["user_id"],
        roles=tuple(caller_roles(info.context)),
        scope=tenant_scope(info),
    )


@strawberry.type
class NotificationQueries:
    @strawberry.field
    def notifications(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        unread_only: bool | None = None,
        limit: int = 5,
    ) -> list[Notification]:
        reader = _reader(info)
        with SessionLocal() as session:
            results = notification_repository.get_notifications(
                session,
                reader,
                uuid.UUID(str(project_id)) if project_id else None,
                unread_only,
                limit,
            )
            return [notification_to_type(n, is_read=is_read) for n, is_read in results]

    @strawberry.field
    def notification_unread_count(self, info: strawberry.Info) -> int:
        """How many notifications the caller has not read, for the bell's badge. Stops at 100 (#1224):
        the bell shows 99+ from there."""
        reader = _reader(info)
        with SessionLocal() as session:
            return notification_repository.count_unread(session, reader)


@strawberry.type
class NotificationMutations:
    @strawberry.mutation
    def mark_notification_as_read(self, info: strawberry.Info, id: strawberry.ID) -> Notification:
        reader = _reader(info)
        with SessionLocal() as session:
            notification = notification_repository.mark_as_read(session, uuid.UUID(str(id)), reader)
            session.commit()
            session.refresh(notification)
            return notification_to_type(notification, is_read=True)

    @strawberry.mutation
    def mark_all_notifications_as_read(self, info: strawberry.Info) -> int:
        """Mark every notification the caller can see as read by them. Returns how many it marked."""
        reader = _reader(info)
        with SessionLocal() as session:
            marked = notification_repository.mark_all_as_read(session, reader)
            session.commit()
            return marked
