import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Index, String, text
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
        # The dedupe lookup for the "this pull is unblocked again" signal (#344): does this pull
        # already have an unread notification of this type? Partial, because only the handful of
        # notifications that are *about* a pull carry the FK at all.
        Index(
            "ix_notifications_pull_request_unread",
            "pull_request_id",
            "type",
            postgresql_where=text("pull_request_id IS NOT NULL AND is_read = false"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String, nullable=False)
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type", create_constraint=True),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(String, nullable=False)
    # The pull this notification is about, when it is about one (#344). Nullable and set only by the
    # pull-centred signals, so it is a discriminated extra rather than a required column.
    #
    # It exists because the "unblocked" notification needs an exact dedupe key. Matching on the
    # request number inside `message` would work until somebody rewords the message, and this whole
    # slice is about states that were only knowable by reading prose. ON DELETE SET NULL, because
    # #325's reopen hard-deletes a still-PENDING pull and the notification is still a true record of
    # something that happened.
    pull_request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="SET NULL"), nullable=True
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
