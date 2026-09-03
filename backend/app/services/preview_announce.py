"""A preview environment telling production it exists, so the workstation relay is told to dial it.

The other half of app/services/preview_registry.py. Every preview announces: a preview clones its
database from production, relay_installs rows and all, so the workstation relay's existing credential
authenticates against it with nothing seeded and there is no second kind of preview to distinguish.

Best effort throughout. Production being unreachable, misconfigured, or slow must not delay this
backend's startup or its shutdown: what fails is "the workstation relay is not told about this
preview", which is exactly where things stood before any of this existed.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import (
    PREVIEW_REGISTRY_SECRET,
    PRODUCTION_BACKEND_ORIGIN,
    RAILWAY_ENVIRONMENT_NAME,
    is_preview_environment,
)

logger = logging.getLogger(__name__)

# Well under the registry's 360s expiry, so a preview survives two missed announcements before it is
# aged out of the list.
ANNOUNCE_INTERVAL_SECONDS = 120.0

# Short: nothing downstream waits on this call, and a hung request at shutdown would hold the deploy.
REQUEST_TIMEOUT_SECONDS = 3.0

SECRET_HEADER = "X-Preview-Registry-Secret"


def enabled() -> bool:
    """Whether this deployment announces itself. Every preview environment, and nothing else -
    production never announces."""
    return is_preview_environment()


def _url(path: str) -> str:
    return f"{PRODUCTION_BACKEND_ORIGIN.rstrip('/')}{path}"


def _environment() -> str:
    return RAILWAY_ENVIRONMENT_NAME.strip()


async def announce_once() -> bool:
    """One heartbeat. Returns whether production accepted it; never raises."""
    if not PREVIEW_REGISTRY_SECRET:
        logger.warning(
            "PREVIEW_REGISTRY_SECRET is not set, so this preview cannot announce itself to production "
            "and the workstation relay will not dial it."
        )
        return False
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _url("/preview-channels"),
                json={"environment": _environment()},
                headers={SECRET_HEADER: PREVIEW_REGISTRY_SECRET},
            )
    except Exception as e:
        # Details inline rather than in `extra`: the backend logs through the stdlib's default
        # formatter, which renders the message and drops every extra field, and a Railway deploy log is
        # the only place anybody reads this from.
        logger.warning("could not announce this preview to production: %s (url=%s)", e, _url("/preview-channels"))
        return False
    if response.status_code >= 400:
        logger.warning(
            "production refused this preview's announcement: %s %s",
            response.status_code,
            response.text[:200],
        )
        return False
    logger.info("announced this preview to production as %s", _environment())
    return True


async def withdraw_once() -> bool:
    """Say goodbye on a clean shutdown. The registry expires a silent preview anyway, so this only
    shortens the window in which the relay dials a backend that is on its way down."""
    if not PREVIEW_REGISTRY_SECRET:
        return False
    path = f"/preview-channels/{_environment()}"
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.delete(_url(path), headers={SECRET_HEADER: PREVIEW_REGISTRY_SECRET})
    except Exception as e:
        logger.info("could not withdraw this preview from production: %s", e)
        return False
    if response.status_code >= 400:
        logger.info("production refused this preview's withdrawal: %s", response.status_code)
        return False
    return True


async def run_forever() -> None:
    """Lifespan task: announce at startup and every interval after."""
    while True:
        await announce_once()
        await asyncio.sleep(ANNOUNCE_INTERVAL_SECONDS)
