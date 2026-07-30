"""Notification queries + mutations."""

import uuid

import strawberry

from app.database import SessionLocal
from app.repositories import notification_repository

from .converters import notification_to_type
from .types import Notification


@strawberry.type
class NotificationQueries:
    @strawberry.field
    def notifications(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        recipient_role: str = "",
        unread_only: bool | None = None,
        limit: int = 5,
    ) -> list[Notification]:
        with SessionLocal() as session:
            results = notification_repository.get_notifications(
                session,
                uuid.UUID(str(project_id)) if project_id else None,
                recipient_role,
                unread_only,
                limit,
            )
            return [notification_to_type(n) for n in results]


@strawberry.type
class NotificationMutations:
    @strawberry.mutation
    def mark_notification_as_read(self, info: strawberry.Info, id: strawberry.ID) -> Notification:
        with SessionLocal() as session:
            notification = notification_repository.mark_as_read(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(notification)
            return notification_to_type(notification)
