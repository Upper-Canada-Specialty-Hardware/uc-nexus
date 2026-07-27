"""Admin-armed pairing window: "adopt the next relay connection" (#353 PR B).

Recovers a relay whose stored secret has drifted from the one it is actually presenting, WITHOUT
physical access to the workstation. That is not a hypothetical: `enroll` rewrites `[auth]
shared_secret` in config.toml, but an already-running relay process keeps dialling with the secret it
read at startup, so the DB and the live process disagree until someone restarts the relay. The relay
binds 127.0.0.1, so there is no remote restart path - and if nobody can reach the machine, every GP
write stays broken.

With a window armed, the next /relay-link handshake is accepted with whatever secret it presents and
that secret is bound to the named install. The relay is already dialling every ~30s, so recovery is
automatic within one reconnect cycle.

**This deliberately weakens an auth boundary while it is open.** The mitigations are all here or in
the route: admin-gated arming, a 300s TTL, single use, WARNING-level logging of who armed it,
adopted_at/adopted_by stamped on the row forever, and a 5s hello-frame gate on the adopted socket.

The armed state is module-level and in-memory on purpose. Railway runs a single replica, the same
constraint that already governs relay_gateway's single-socket registry, and a window that survived a
deploy would be a window nobody remembers arming - a restart clearing it is the desired behaviour,
not a limitation."""

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

ADOPT_TTL_SECONDS = 300


@dataclass(frozen=True)
class ArmedWindow:
    install_id: uuid.UUID
    label: str
    expires_at: datetime
    armed_by: str


# The /relay-link route coroutine and the GraphQL resolvers can touch this from different threads
# (uvicorn runs sync resolvers on a threadpool), so guard the swap rather than relying on the GIL to
# make a check-then-clear atomic.
_LOCK = threading.Lock()
_window: ArmedWindow | None = None


def arm(install_id: uuid.UUID, label: str, armed_by: str) -> ArmedWindow:
    """Open a window on one install, replacing any existing one. One window at a time, scoped to a
    single install id: two simultaneous windows would double the exposure for no operational gain."""
    global _window
    window = ArmedWindow(
        install_id=install_id,
        label=label,
        expires_at=datetime.utcnow() + timedelta(seconds=ADOPT_TTL_SECONDS),
        armed_by=armed_by,
    )
    with _LOCK:
        _window = window
    logger.warning(
        "relay adopt window armed - the next /relay-link connection presenting ANY secret will be "
        "bound to this install",
        extra={
            "install_id": str(install_id),
            "label": label,
            "armed_by": armed_by,
            "expires_at": window.expires_at.isoformat(),
        },
    )
    return window


def peek() -> ArmedWindow | None:
    """The currently armed window, or None. An expired window is cleared here rather than left for a
    reaper: expiry is only ever observed on a read, so a lazy clear is exact."""
    global _window
    with _LOCK:
        window = _window
        if window is not None and window.expires_at <= datetime.utcnow():
            _window = None
            return None
        return window


def consume(install_id: uuid.UUID) -> bool:
    """Single use: burn the window for `install_id`. Returns False when it has expired, was already
    consumed, or is armed on a different install. Consumed on the first successful adoption whether
    or not that socket then survives the hello gate - an adopted connection has already rewritten the
    credential, so leaving the window open would let a second unknown secret overwrite it again."""
    global _window
    with _LOCK:
        window = _window
        if window is None or window.install_id != install_id:
            return False
        if window.expires_at <= datetime.utcnow():
            _window = None
            return False
        _window = None
        return True


def disarm() -> bool:
    """Close the window early. Returns whether one was open."""
    global _window
    with _LOCK:
        was_armed = _window is not None
        _window = None
    if was_armed:
        logger.warning("relay adopt window disarmed")
    return was_armed
