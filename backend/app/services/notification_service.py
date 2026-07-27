import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.enums import NotificationType
from app.models.notification import Notification


def create_notification(
    session: Session,
    project_id: uuid.UUID,
    recipient_role: str,
    notification_type: NotificationType,
    message: str,
    pull_request_id: uuid.UUID | None = None,
) -> Notification:
    notification = Notification(
        id=uuid.uuid4(),
        project_id=project_id,
        recipient_role=recipient_role,
        type=notification_type,
        message=message,
        pull_request_id=pull_request_id,
        is_read=False,
        created_at=datetime.utcnow(),
    )
    session.add(notification)
    return notification


# `recipient_role` is an audience tag, not an access control. The notification bell queries with no
# recipient filter, so every signed-in user sees every notification; the tag says who it is *for*,
# which is what makes a targeted bell a later filtering change rather than a data migration. Two
# shapes of value live in this column: a named audience (the constants below) and, for the one
# signal that is owed to a specific person, that person's stable Clerk user id.

# Recipient role for the purchasing officer who backfills short inventory (#224).
PO_RECIPIENT_ROLE = "PO"

# Recipient role for shipping/reallocation signals (#341): hardware that arrived for a leaf which has
# already left the building is a shipping problem, not a purchasing one.
SHIPPING_RECIPIENT_ROLE = "SHIPPING"

# Recipient role for "the assignment board has work on it" (#344). Deliberately the manager audience
# and not the whole floor: a staged, unassigned opening is a decision about who should build it, and
# broadcasting it to every assembler would make the useful signals harder to see.
SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE = "SHOP_ASSEMBLY_MANAGER"

# Recipient role for warehouse-actionable signals (#344), i.e. a blocked pull that can now be
# approved. It is the warehouse that approves a pull, so it is the warehouse that needs telling.
WAREHOUSE_RECIPIENT_ROLE = "WAREHOUSE"


def has_unread_notification_for_pull(
    session: Session,
    pull_request_id: uuid.UUID,
    notification_type: NotificationType,
) -> bool:
    """Whether this pull already has an *open* (unread) notification of this type (#344).

    This is the dedupe primitive behind `PULL_UNBLOCKED`. A replacement pull can sit PENDING across
    many receives, and re-announcing it on each one would turn a useful signal into wallpaper -
    which is the failure mode that makes people stop reading the bell entirely. Keying on
    `pull_request_id` rather than on text inside `message` is what makes it exact.

    Unread rather than "ever" is the deliberate choice: once somebody has read it, the signal has
    done its job, and if the pull goes short again (stock written off under it) and is later covered
    again, that is genuinely new information and deserves to be raised again.

    One EXISTS against the partial index; no rows are loaded.
    """
    return bool(
        session.scalar(
            select(
                exists().where(
                    Notification.pull_request_id == pull_request_id,
                    Notification.type == notification_type,
                    Notification.is_read == False,
                )
            )
        )
    )


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
