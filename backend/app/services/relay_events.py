"""Recording relay connection-slot transitions, from paths that must not be slowed or broken by it.

Every call site here sits on the relay socket path - the /relay-link route and the gateway - and two
rules follow from that, both load-bearing:

- **The DB write never happens on the event loop.** `asyncio.to_thread` hands it to a worker, so a
  slow or unreachable database cannot stall the socket, the heartbeat, or an in-flight relay_call. The
  whole feature is diagnostics; it must never be able to cause the outage it exists to explain.
- **Nothing raised here reaches the socket.** A failed insert is logged and dropped. Losing an event
  row costs a line of history; letting it propagate would tear down a live relay connection.

REFUSED_SECRET is throttled because it is the one kind an outsider controls the rate of: a relay
dialling with a drifted secret retries every few seconds forever (42 rejected handshakes in a few
minutes, observed), and one row per retry would bury every other event in the table. One row per ten
minutes says the same thing - that this is happening, and since when.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models.enums import RelayEventKind
from app.repositories import relay_event_repository

logger = logging.getLogger(__name__)

# How long a row is kept. Long enough to answer "how often did it drop last month", short enough that
# a table nothing indexes by anything but time never becomes a scan worth thinking about.
RETENTION_DAYS = 30

# Floor between prune passes. Ridden off the write path rather than a task of its own: the table only
# grows when something is written to it, so the write is exactly when a sweep is worth its cost.
PRUNE_INTERVAL_SECONDS = 3600.0

# At most one REFUSED_SECRET row per this window. See the module docstring.
REFUSED_SECRET_THROTTLE_SECONDS = 600.0

_lock = threading.Lock()
_last_refused_secret: float | None = None
_last_prune: float | None = None

# Strong references to in-flight fire-and-forget writes. asyncio only holds a weak reference to a
# task, so without this the garbage collector can eat one mid-write.
_in_flight: set[asyncio.Task] = set()


def _throttled(kind: RelayEventKind) -> bool:
    """Whether this event is being dropped as a repeat. Only REFUSED_SECRET is ever throttled."""
    global _last_refused_secret
    if kind is not RelayEventKind.REFUSED_SECRET:
        return False
    now = time.monotonic()
    with _lock:
        if _last_refused_secret is not None and now - _last_refused_secret < REFUSED_SECRET_THROTTLE_SECONDS:
            return True
        _last_refused_secret = now
    return False


def _prune_due() -> bool:
    global _last_prune
    now = time.monotonic()
    with _lock:
        if _last_prune is not None and now - _last_prune < PRUNE_INTERVAL_SECONDS:
            return False
        _last_prune = now
    return True


def _insert(
    kind: RelayEventKind,
    at: datetime,
    install_id: uuid.UUID | None,
    build: str | None,
    companies: Sequence[str] | None,
    reason: str | None,
    detail: dict | None,
) -> None:
    with SessionLocal() as session:
        relay_event_repository.record(
            session,
            kind=kind,
            at=at,
            install_id=install_id,
            build=build,
            companies=companies,
            reason=reason,
            detail=detail,
        )
        if _prune_due():
            relay_event_repository.prune(session, older_than=datetime.utcnow() - timedelta(days=RETENTION_DAYS))
        session.commit()


async def write(
    kind: RelayEventKind,
    *,
    at: datetime | None = None,
    install_id: uuid.UUID | None = None,
    build: str | None = None,
    companies: Sequence[str] | None = None,
    reason: str | None = None,
    detail: dict | None = None,
) -> None:
    """Write one event off the event loop. Never raises."""
    if _throttled(kind):
        return
    try:
        await asyncio.to_thread(
            _insert,
            kind,
            at or datetime.utcnow(),
            install_id,
            build,
            list(companies) if companies is not None else None,
            reason,
            detail,
        )
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("could not record relay event %s: %s", kind.value, e)


def record(
    kind: RelayEventKind,
    *,
    at: datetime | None = None,
    install_id: uuid.UUID | None = None,
    build: str | None = None,
    companies: Sequence[str] | None = None,
    reason: str | None = None,
    detail: dict | None = None,
) -> None:
    """Fire-and-forget `write`, for the synchronous call sites inside the gateway.

    A no-op when no event loop is running. That case is a unit test or a script calling the gateway
    directly, never production - every real transition happens inside the /relay-link route's task -
    and it keeps a test that merely exercises register/unregister from opening a database connection."""
    at = at or datetime.utcnow()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(
        write(
            kind,
            at=at,
            install_id=install_id,
            build=build,
            companies=companies,
            reason=reason,
            detail=detail,
        )
    )
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


def reset() -> None:
    """Drop the throttle and prune floors. Tests only."""
    global _last_refused_secret, _last_prune
    with _lock:
        _last_refused_secret = None
        _last_prune = None
