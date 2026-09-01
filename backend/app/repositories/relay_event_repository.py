"""Reads and writes for relay_events - the durable history of the relay's connection slot."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.enums import RelayEventKind
from app.models.relay_event import RelayEvent
from app.models.relay_install import RelayInstall


def record(
    session: Session,
    *,
    kind: RelayEventKind,
    at: datetime | None = None,
    install_id: uuid.UUID | None = None,
    install_label: str | None = None,
    build: str | None = None,
    companies: Sequence[str] | None = None,
    reason: str | None = None,
    detail: dict | None = None,
) -> RelayEvent:
    """Insert one event.

    The label is snapshotted here rather than asked of the caller: this is the only moment a session is
    open anyway, and every call site is on a socket path that has deliberately stopped holding one (see
    the DetachedInstanceError rule in main.relay_link). `at` is passed in rather than defaulted for the
    same reason the CONNECTED row exists at all - the write happens after a grace period for the hello
    frame, and the event has to be stamped when the connection HAPPENED."""
    if install_label is None and install_id is not None:
        install_label = session.scalars(
            select(RelayInstall.label).where(RelayInstall.id == install_id).limit(1)
        ).first()
    event = RelayEvent(
        id=uuid.uuid4(),
        at=at or datetime.utcnow(),
        kind=kind.value,
        install_id=install_id,
        install_label=install_label,
        build=build,
        companies=list(companies) if companies is not None else None,
        reason=reason,
        detail=detail,
    )
    session.add(event)
    session.flush()
    return event


def list_events(session: Session, limit: int = 50) -> list[RelayEvent]:
    """The newest `limit` events, newest first."""
    return list(session.scalars(select(RelayEvent).order_by(RelayEvent.at.desc()).limit(limit)).all())


def prune(session: Session, *, older_than: datetime) -> int:
    """Delete events stamped before `older_than`. Returns how many went."""
    return session.execute(delete(RelayEvent).where(RelayEvent.at < older_than)).rowcount or 0
