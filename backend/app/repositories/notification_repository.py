"""Repository for notification data access.

Every read and write here is for one caller (#1111): the notifications they can see are the ones in
their company (`scope`, from `tenant_scope`; None for a UC NEXUS ADMIN with no company picked)
addressed to an audience their roles belong to or to them by user id, and "read" is their own read,
recorded as a NotificationRead row.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models.notification import Notification, NotificationRead
from app.repositories.tenancy import project_ids_for
from app.services.notification_service import audiences_for

# The most rows one notifications read returns (#1134). The bell asks for 5.
MAX_NOTIFICATIONS_LIMIT = 200

# The unread count stops here (#1224). The bell shows 99+ past 99, so counting further only makes
# every 30s poll walk a reader's whole unread history for a number nobody sees.
UNREAD_COUNT_CAP = 100


@dataclass(frozen=True)
class Reader:
    """Who is asking: their Clerk user id, their roles, and their company scope."""

    user_id: str
    roles: tuple[str, ...]
    scope: str | None


def _read_by(reader: Reader):
    return exists().where(
        NotificationRead.notification_id == Notification.id,
        NotificationRead.user_id == reader.user_id,
    )


def _visible(reader: Reader) -> list:
    """The WHERE clauses for the notifications this reader can see."""
    clauses = []
    if reader.scope is not None:
        clauses.append(Notification.project_id.in_(project_ids_for(reader.scope)))
    audiences = audiences_for(reader.roles)
    for_audience = (
        Notification.recipient_role.is_not(None) if audiences is None else Notification.recipient_role.in_(audiences)
    )
    clauses.append(or_(Notification.recipient_user_id == reader.user_id, for_audience))
    return clauses


def get_notifications(
    session: Session,
    reader: Reader,
    project_id: uuid.UUID | None = None,
    unread_only: bool | None = None,
    limit: int = 5,
) -> list[tuple[Notification, bool]]:
    """The newest notifications this reader can see, each with whether they have read it."""
    limit = max(1, min(limit, MAX_NOTIFICATIONS_LIMIT))
    read = _read_by(reader)
    stmt = select(Notification, read.label("read_by_me")).where(*_visible(reader))
    if project_id is not None:
        stmt = stmt.where(Notification.project_id == project_id)
    if unread_only:
        stmt = stmt.where(~read)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return [(n, bool(is_read)) for n, is_read in session.execute(stmt).all()]


def count_unread(session: Session, reader: Reader) -> int:
    """How many notifications this reader can see and has not read, up to UNREAD_COUNT_CAP. One
    COUNT over a LIMITed subquery, so the scan stops at the cap instead of walking the history."""
    unread = select(Notification.id).where(*_visible(reader), ~_read_by(reader)).limit(UNREAD_COUNT_CAP).subquery()
    return int(session.scalar(select(func.count()).select_from(unread)) or 0)


def mark_as_read(session: Session, notification_id: uuid.UUID, reader: Reader) -> Notification:
    """Record this reader's read. A notification they cannot see reads as absent."""
    notification = session.scalars(
        select(Notification).where(Notification.id == notification_id, *_visible(reader))
    ).first()
    if notification is None:
        raise NotFoundError("Notification not found")
    session.execute(
        insert(NotificationRead)
        .values(notification_id=notification.id, user_id=reader.user_id, read_at=datetime.utcnow())
        .on_conflict_do_nothing()
    )
    notification.is_read = True
    session.flush()
    return notification


def mark_all_as_read(session: Session, reader: Reader) -> int:
    """Record this reader's read on every notification they can see and have not read. Two
    statements whatever the count. Returns how many were marked."""
    unread_ids = select(Notification.id).where(*_visible(reader), ~_read_by(reader))
    result = session.execute(
        insert(NotificationRead)
        .from_select(
            ["notification_id", "user_id", "read_at"],
            select(
                unread_ids.subquery().c.id,
                literal(reader.user_id),
                literal(datetime.utcnow()),
            ),
        )
        .on_conflict_do_nothing()
        .returning(NotificationRead.notification_id)
    )
    marked = [row[0] for row in result.all()]
    if marked:
        session.execute(update(Notification).where(Notification.id.in_(marked)).values(is_read=True))
    session.flush()
    return len(marked)
