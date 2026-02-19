import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, Index, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import NotificationType


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index(
            "ix_notifications_project_role_read",
            "project_id",
            "recipient_role",
            "is_read",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    recipient_role: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", create_constraint=True),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
