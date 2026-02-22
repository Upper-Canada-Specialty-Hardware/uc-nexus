import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.enums import NotificationType
from app.models.notification import Notification


def create_notification(
    session: Session,
    project_id: uuid.UUID,
    recipient_role: str,
    notification_type: NotificationType,
    message: str,
) -> Notification:
    notification = Notification(
        id=uuid.uuid4(),
        project_id=project_id,
        recipient_role=recipient_role,
        type=notification_type,
        message=message,
        is_read=False,
        created_at=datetime.utcnow(),
    )
    session.add(notification)
    return notification
