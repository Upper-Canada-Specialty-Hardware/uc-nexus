import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Enum, ForeignKey, Index, String, text
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
        # The bell's newest-first read (#1224): the company scope filters on project_id and the read
        # orders by created_at, so one index serves both and a LIMIT 5 stops early.
        Index("ix_notifications_project_created_at", "project_id", "created_at"),
        # A person-targeted notification is looked up by its one recipient (#1111).
        Index("ix_notifications_recipient_user_id", "recipient_user_id"),
        # Every notification is for exactly one of: an audience, or a person (#1111).
        CheckConstraint(
            "(recipient_role IS NULL) <> (recipient_user_id IS NULL)",
            name="ck_notifications_one_recipient",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    # Who it is for (#1111): an audience from notification_service.AUDIENCE_ROLES, or one person's
    # Clerk user id in recipient_user_id. Exactly one of the two is set.
    recipient_role: Mapped[str | None] = mapped_column(String, nullable=True)
    recipient_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
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
    # Read by at least one person. Each person's own read state is a NotificationRead row (#1111);
    # this flag stays because the pull dedupe keys on "has anybody seen it yet".
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)


class NotificationRead(Base):
    """One person has read one notification (#1111). Read state used to be one flag per row, so the
    first person to open a notification cleared it for everybody else."""

    __tablename__ = "notification_reads"

    notification_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    read_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
