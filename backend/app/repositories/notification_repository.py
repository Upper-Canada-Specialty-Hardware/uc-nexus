"""Repository for notification data access."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models.notification import Notification


def get_notifications(
    session: Session,
    project_id: uuid.UUID,
    recipient_role: str,
    unread_only: bool | None = None,
    limit: int = 5,
) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.project_id == project_id,
    )
    if recipient_role:
        stmt = stmt.where(Notification.recipient_role == recipient_role)
    if unread_only:
        stmt = stmt.where(Notification.is_read == False)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return list(session.scalars(stmt).all())


def mark_as_read(session: Session, notification_id: uuid.UUID) -> Notification:
    notification = session.get(Notification, notification_id)
    if notification is None:
        raise NotFoundError("Notification not found")
    notification.is_read = True
    session.flush()
    return notification
