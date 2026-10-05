import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models.enums import NotificationType
from app.models.notification import Notification


def create_notification(
    session: Session,
    project_id: uuid.UUID,
    recipient_role: str | None,
    notification_type: NotificationType,
    message: str,
    pull_request_id: uuid.UUID | None = None,
    recipient_user_id: str | None = None,
) -> Notification:
    """Raise a notification for an audience (`recipient_role`, a key of AUDIENCE_ROLES) or for one
    person (`recipient_user_id`, a Clerk user id). Exactly one of the two (#1111)."""
    if (recipient_role is None) == (recipient_user_id is None):
        raise ValueError("A notification is for an audience or for one person, not both or neither")
    if recipient_role is not None and recipient_role not in AUDIENCE_ROLES:
        raise ValueError(f"Unknown notification audience {recipient_role!r}")
    notification = Notification(
        id=uuid.uuid4(),
        project_id=project_id,
        recipient_role=recipient_role,
        recipient_user_id=recipient_user_id,
        type=notification_type,
        message=message,
        pull_request_id=pull_request_id,
        is_read=False,
        created_at=datetime.utcnow(),
    )
    session.add(notification)
    return notification


# Who a notification is for (#1111). `recipient_role` holds one of the audiences below, and the bell
# shows it to the people holding one of that audience's roles, in the notification's company. A
# signal owed to one person carries that person's Clerk user id in `recipient_user_id` instead. A
# TENANT OWNER and a UC NEXUS ADMIN hold every module role inside their company, so they see every
# audience; nobody but the person sees a person-targeted one.

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

# Recipient role for "a counted receive is waiting on approval". The manager audience rather than the
# whole warehouse, for the same reason as the shop-assembly one above: approving is a decision only
# managers can make, and the person who submitted it already knows it is there.
WAREHOUSE_MANAGER_RECIPIENT_ROLE = "WAREHOUSE_MANAGER"

# Recipient role for a shop-assembly pull that was fulfilled or cancelled (#1111). The pull records
# its requester by name only, so the audience is the module the requester works in.
SHOP_ASSEMBLY_RECIPIENT_ROLE = "SHOP_ASSEMBLY"

# Which roles see each audience. The names match app/auth.py and the User Management page.
AUDIENCE_ROLES: dict[str, frozenset[str]] = {
    PO_RECIPIENT_ROLE: frozenset({"PO User", "PO Manager"}),
    SHIPPING_RECIPIENT_ROLE: frozenset({"Shipping Out", "Shipping Manager"}),
    SHOP_ASSEMBLY_RECIPIENT_ROLE: frozenset({"Shop Assembly User", "Shop Assembly Manager"}),
    SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE: frozenset({"Shop Assembly Manager"}),
    WAREHOUSE_RECIPIENT_ROLE: frozenset({"Warehouse Staff", "Warehouse Manager"}),
    WAREHOUSE_MANAGER_RECIPIENT_ROLE: frozenset({"Warehouse Manager"}),
}

# Roles that see every audience: they hold every module role inside their company.
ALL_AUDIENCE_ROLES = frozenset({"UC Nexus Admin", "Tenant Owner"})


def pull_audience(source) -> str:
    """Who hears that a pull was fulfilled or cancelled: the module that asked for it. The pull keeps
    its requester's name only, never a user id, so the person cannot be addressed directly."""
    value = getattr(source, "value", source)
    return SHIPPING_RECIPIENT_ROLE if value == "SHIPPING_OUT" else SHOP_ASSEMBLY_RECIPIENT_ROLE


def audiences_for(roles) -> list[str] | None:
    """The audiences a caller holding these roles sees, or None for every audience."""
    held = set(roles or ())
    if held & ALL_AUDIENCE_ROLES:
        return None
    return sorted(audience for audience, members in AUDIENCE_ROLES.items() if held & members)


def has_unread_notification_for_pull(
    session: Session,
    pull_request_id: uuid.UUID,
    notification_type: NotificationType,
    recipient_role: str | None = None,
) -> bool:
    """Whether this pull already has an *open* (unread) notification of this type.

    `recipient_role` narrows it to one audience (#1241). INVENTORY_SHORTFALL is raised to two: the
    PO backfill signal to purchasing, and the count-below-reserved notice to warehouse managers
    (#1124), both keyed to the pull. Unfiltered, an unread manager notice suppressed purchasing's
    backfill signal for the very short pick it predicted.

    The dedupe primitive behind the pick-time PO backfill signal (`INVENTORY_SHORTFALL`, #367): a
    short pick is resumable, so a picker keying a big sheet in three sittings would otherwise raise
    three identical backfill notifications for the same gap. Keying on `pull_request_id` rather than
    on text inside `message` is what makes it exact.

    Unread rather than "ever" is the deliberate choice: once somebody has read it, the signal has
    done its job, and if the pull goes short again (stock written off under it) that is genuinely new
    information and deserves to be raised again.

    One EXISTS against the partial index; no rows are loaded.
    """
    conditions = [
        Notification.pull_request_id == pull_request_id,
        Notification.type == notification_type,
        Notification.is_read == False,
    ]
    if recipient_role is not None:
        conditions.append(Notification.recipient_role == recipient_role)
    return bool(session.scalar(select(exists().where(*conditions))))


def format_shortfall_lines(shortfalls) -> str:
    """One human-readable clause per shorted combo, joined by '; '. `shortfalls` is any iterable of
    objects exposing hardware_category / product_code / requested / available / short (the shared
    Shortfall from warehouse_repository), duck-typed so this stays free of a repository import."""
    return "; ".join(
        f"{s.hardware_category} {s.product_code}: need {s.requested}, {s.available} available (short {s.short})"
        for s in shortfalls
    )


def format_pick_shortfall_lines(shortfalls) -> str:
    """The short-pick frame (#367), which the creation-gate template cannot say truthfully.

    A pick's `short` is what the pull is still owed after the confirm, and its `available` is what
    the project shows free *now* - deliberately post-deduction (see `_pick_shortfalls`). Pushing
    those numbers through the gate template rendered "need 3, 6 available (short 2)": arithmetic
    that holds in the gate frame (short = need - available) and reads as nonsense in this one.
    """
    return "; ".join(
        f"{s.hardware_category} {s.product_code}: {s.requested - s.short} of {s.requested} picked - "
        f"{s.short} still owed ({s.available} free in the project now)"
        for s in shortfalls
    )


def notify_po_shortfall(
    session: Session,
    project_id: uuid.UUID,
    request_number: str | None,
    shortfalls,
    sent_short: bool = False,
    pull_request_id: uuid.UUID | None = None,
    pick_frame: bool = False,
) -> Notification:
    """PO backfill signal (#224), carrying the shortfall detail.

    Raised from three places, and the wording distinguishes the one that is not a failure:

    - the creation gate refusing a request outright, and a pick confirmed short of what the pull
      asked for (#367) - both are "couldn't be fulfilled";
    - a shop-assembly request that **was** created and deliberately sent short of what the schedule
      calls for (`sent_short=True`). Nothing failed there and nothing is blocked; purchasing is being
      told what the project is missing. Calling that "couldn't be fulfilled" would send somebody
      hunting for a stuck request that does not exist.

    `pull_request_id` links the signal to the pull it came off, which is what makes
    `has_unread_notification_for_pull` able to dedupe it (#367): a short pick is resumable, so the
    same gap can be re-reported every time the picker keys in another handful.
    """
    # #1533: no longer defaults to "A shop-assembly task" - the one caller without a pull number is the
    # creation gate, which names what it refused through notify_gate_shortfall.
    label = f"Pull Request {request_number}" if request_number else "A request"
    headline = (
        f"{label} was sent short of what the schedule calls for - backfill needed."
        if sent_short
        else f"{label} couldn't be fulfilled - backfill needed."
    )
    lines = format_pick_shortfall_lines(shortfalls) if pick_frame else format_shortfall_lines(shortfalls)
    message = f"{headline} {lines}"
    return create_notification(
        session,
        project_id=project_id,
        recipient_role=PO_RECIPIENT_ROLE,
        notification_type=NotificationType.INVENTORY_SHORTFALL,
        message=message,
        pull_request_id=pull_request_id,
    )


def notify_gate_shortfall(session: Session, error) -> Notification | None:
    """PO backfill signal for a request the creation gate refused (#342, #1533), or None when there is
    nothing to raise.

    Only the part genuinely not in the building goes to purchasing: the gate's `short` is measured against
    *available* (on-hand - deficient - reservations), so a combo short only because another request holds
    it is not a purchasing problem, and for the rest `short - reserved` is what the shelf is missing.

    The headline names what was refused - "A shipping-out request couldn't be created" - from the gate's
    own label. It used to fall back to "A shop-assembly task", which was never true on the import path and
    sent purchasing looking on the Shop Assembly board for a request that did not exist.

    A refused creation writes nothing, so there is no pull to key a dedupe on the way
    `has_unread_notification_for_pull` does. The creator retries the same selection instead, and every
    refusal used to raise another copy. So a notice is skipped while an identical one - same project, same
    audience, no pull, word for word the same message - is still unread. Unread for the same reason as the
    pull dedupe: once somebody has read it the signal has done its job, and the same gap coming back after
    that is worth raising again. A different shortfall reads differently and is raised.
    """
    from dataclasses import replace

    unstocked = [replace(s, short=max(0, s.short - s.reserved)) for s in error.shortfalls if s.short > s.reserved]
    if not unstocked:
        return None
    subject = getattr(error, "label", None)
    headline = (
        f"A {subject} couldn't be created - backfill needed."
        if subject
        else "A request couldn't be fulfilled - backfill needed."
    )
    message = f"{headline} {format_shortfall_lines(unstocked)}"
    already = session.scalar(
        select(
            exists().where(
                Notification.project_id == error.project_id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
                Notification.recipient_role == PO_RECIPIENT_ROLE,
                Notification.pull_request_id.is_(None),
                Notification.is_read == False,
                Notification.message == message,
            )
        )
    )
    if already:
        return None
    return create_notification(
        session,
        project_id=error.project_id,
        recipient_role=PO_RECIPIENT_ROLE,
        notification_type=NotificationType.INVENTORY_SHORTFALL,
        message=message,
    )
