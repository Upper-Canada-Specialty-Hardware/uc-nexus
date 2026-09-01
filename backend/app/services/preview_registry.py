"""Which preview backends the workstation relay should also be dialling (#654).

The relay holds a list of backend URLs and reconciles it every ten seconds, so the set of channels it
serves has always been dynamic at runtime. What was never dynamic is where that list comes from: a
TOML file on one GP-credentialed workstation, edited by hand. Railway creates a preview environment
per pull request at an address nobody has seen before, so every PR that needed a real GP channel
waited on somebody walking to that machine.

The first attempt at closing that loop had production ask the Railway API which environments existed
and serve the answer on a GET the relay polled once a minute. Two things were wrong with it. The poll
carried its own copy of the relay credential, drifting from the one the live socket had already
proven - which is how #654 ended with every fresh preview relay-dark while the socket itself was
perfectly healthy. And discovery depended on a write-capable Railway API token whose failure mode was
silent: a token that stopped working returned an empty list, indistinguishable from "every PR closed".

So the direction is inverted. A preview environment ANNOUNCES itself to production
(app/services/preview_announce.py), production holds those announcements here, and the list is PUSHED
down the socket the relay already holds (relay_gateway.push_channels). No second credential on the
relay side, no third-party API, and an environment that stops announcing ages out of the list on its
own - which is what makes teardown as automatic as setup, without anything having to notice a PR was
closed.

Three properties keep this safe without a human vetting each address:

- Only PRODUCTION registers. The routes 404 anywhere else, so a preview cannot advertise other
  previews, and the registry is empty everywhere it is not needed.
- The name shape is fixed and validated on BOTH sides. Nothing here can name an arbitrary host: the
  URL is derived from a `uc-nexus-pr-<N>` name, and the relay re-checks the pattern before dialling.
- A pushed channel can never be the primary one. The relay decides that by identity against its own
  baked-in production URL, so every announced channel inherits the sandbox company pin. The worst a
  rogue entry could do is offer a channel that may only touch TUBC.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time

from app.config import is_production_environment
from app.services.relay_gateway import gateway

logger = logging.getLogger(__name__)

# Railway names a pull request's environment `uc-nexus-pr-<N>`, not `pr-<N>`. Anchored: this is the
# only thing standing between "something posted a name" and "the relay will dial it", so a name that
# merely contains the prefix must not match.
PREVIEW_ENVIRONMENT_RE = re.compile(r"^uc-nexus-pr-(\d+)$")

# Public hostnames are `<service>-<environment>.up.railway.app`, and the backend service is `backend`
# in every environment. Derived rather than looked up because the derivation is total: any environment
# matching the name pattern above has exactly this address.
_CHANNEL_URL = "wss://backend-{environment}.up.railway.app/relay-link"

# How long an announcement stands without a heartbeat. Comfortably longer than the announce interval
# (120s) so a preview that misses one - a redeploy, a cold start, a blip reaching production - is not
# dropped and re-added, and short enough that a torn-down environment stops being dialled within a few
# minutes of its last breath.
ENTRY_TTL_SECONDS = 360.0

# How often the expiry sweep runs. Well under the TTL so the list a relay holds is never stale by more
# than a tick beyond it.
PRUNE_INTERVAL_SECONDS = 30.0

_lock = threading.Lock()
# environment name -> monotonic stamp of its last announcement. Monotonic so a clock adjustment on the
# host cannot expire the whole list at once.
_entries: dict[str, float] = {}


def channel_url_for(environment_name: str) -> str:
    """The relay channel URL for a preview environment name."""
    return _CHANNEL_URL.format(environment=environment_name)


def is_preview_environment_name(name: str) -> bool:
    """Whether `name` is exactly a Railway preview environment name for this project."""
    return bool(PREVIEW_ENVIRONMENT_RE.match((name or "").strip()))


def enabled() -> bool:
    """Whether this deployment keeps a registry at all. Production only - see the module docstring."""
    return is_production_environment()


def note_announcement(environment: str) -> bool:
    """Record a preview's heartbeat. Returns whether the channel LIST changed, which is the only thing
    worth pushing over the socket for - a heartbeat from an environment already listed changes
    nothing."""
    with _lock:
        changed = environment not in _entries
        _entries[environment] = time.monotonic()
    if changed:
        logger.info("preview channel registered: %s", environment)
    return changed


def forget(environment: str) -> bool:
    """Drop a preview that said goodbye. Returns whether it was listed."""
    with _lock:
        existed = _entries.pop(environment, None) is not None
    if existed:
        logger.info("preview channel unregistered: %s", environment)
    return existed


def prune() -> bool:
    """Drop announcements that have gone quiet. Returns whether anything expired.

    Expiry rather than an explicit teardown call being the load-bearing half is deliberate: a preview
    environment is deleted by Railway, and nothing runs in it afterwards to say so. The DELETE is the
    fast path for a clean shutdown, not the mechanism."""
    cutoff = time.monotonic() - ENTRY_TTL_SECONDS
    with _lock:
        expired = [name for name, seen in _entries.items() if seen <= cutoff]
        for name in expired:
            del _entries[name]
    if expired:
        logger.info("preview channels expired after %ss without a heartbeat: %s", int(ENTRY_TTL_SECONDS), expired)
    return bool(expired)


def environments() -> list[str]:
    """Every announced preview environment, newest PR first - the environment somebody is waiting on is
    almost always the newest one, and the relay logs the list it was handed."""
    with _lock:
        names = list(_entries)
    return sorted(names, key=lambda name: int(PREVIEW_ENVIRONMENT_RE.match(name).group(1)), reverse=True)


def channels() -> list[str]:
    """The channel URLs to hand the relay. Empty off production, where nothing ever registers."""
    return [channel_url_for(name) for name in environments()]


async def publish() -> None:
    """Push the current list down the live relay socket. A no-op when no relay is connected or the
    connected one predates the channels feature - see relay_gateway.push_channels."""
    await gateway.push_channels(channels())


async def run_prune_forever() -> None:
    """Lifespan task: age out announcements and push the shortened list when one goes."""
    while True:
        await asyncio.sleep(PRUNE_INTERVAL_SECONDS)
        try:
            if prune():
                await publish()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A sweep that fails must not end the loop: the next tick is 30 seconds away and the
            # registry is diagnostics-grade state, not something worth taking the process down for.
            logger.exception("preview channel expiry sweep failed")


def reset() -> None:
    """Drop every announcement. Tests only."""
    with _lock:
        _entries.clear()
