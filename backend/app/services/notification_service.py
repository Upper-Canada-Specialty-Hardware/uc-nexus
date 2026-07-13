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


# Recipient role for the purchasing officer who backfills short inventory (#224).
PO_RECIPIENT_ROLE = "PO"


def format_shortfall_lines(shortfalls) -> str:
    """One human-readable clause per shorted combo, joined by '; '. `shortfalls` is any iterable of
    objects exposing hardware_category / product_code / requested / available / short (the shared
    Shortfall from warehouse_repository), duck-typed so this stays free of a repository import."""
    return "; ".join(
        f"{s.hardware_category} {s.product_code}: need {s.requested}, {s.available} available (short {s.short})"
        for s in shortfalls
    )


def notify_po_shortfall(
    session: Session,
    project_id: uuid.UUID,
    request_number: str | None,
    shortfalls,
) -> Notification:
    """PO "couldn't be fulfilled - backfill needed" signal (#224), carrying the shortfall detail.
    Raised by both gates: import "Start a Task" (no PR yet) and warehouse approve_pull_request."""
    label = f"Pull Request {request_number}" if request_number else "A shop-assembly task"
    message = f"{label} couldn't be fulfilled - backfill needed. {format_shortfall_lines(shortfalls)}"
    return create_notification(
        session,
        project_id=project_id,
        recipient_role=PO_RECIPIENT_ROLE,
        notification_type=NotificationType.INVENTORY_SHORTFALL,
        message=message,
    )
