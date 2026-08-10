"""Which preview backends the workstation relay should also be dialling.

The relay holds a list of backend URLs and reconciles it every ten seconds (#456), so the set of
channels it serves is already dynamic at runtime. What was never dynamic is where that list comes
from: a TOML file on one GP-credentialed workstation, edited by hand. Railway creates a preview
environment per pull request, automatically, at an address nobody has seen before - so the two halves
ran on different clocks, and every PR that needed a real GP channel waited on somebody walking to that
machine. Environments created after the last edit were simply invisible.

This closes that loop from the backend side. Production asks Railway which preview environments exist
right now and hands the relay the derived channel URLs; the relay unions them with its own file. A
preview environment that appears is dialled within a tick, and one that is torn down stops being
listed, so teardown is as automatic as setup.

Three properties make this safe to do without a human vetting each address:

- Only PRODUCTION discovers. `RAILWAY_API_TOKEN` is set on production alone, and a backend without one
  answers an empty list. A preview environment therefore cannot advertise other preview environments.
- The derived URL shape is fixed and validated on BOTH sides. Nothing here can name an arbitrary host,
  and the relay re-checks the pattern before dialling rather than trusting this answer.
- A discovered channel can never be the primary one. `is_primary_backend_url` in the relay decides
  that by identity against its own baked-in production URL, so every discovered channel inherits the
  sandbox company pin (`NON_PRIMARY_ALLOWED_COMPANIES`). The worst a rogue entry could do is offer a
  channel that may only touch TUBC.

Discovery failing is not an error state. The relay keeps whatever it last knew and its config file
still works, which is exactly where things stood before this existed.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import httpx

from app.config import RAILWAY_API_TOKEN, RAILWAY_API_URL, RAILWAY_PROJECT_ID

logger = logging.getLogger(__name__)

# Railway names a pull request's environment `uc-nexus-pr-<N>`, not `pr-<N>`. Anchored: this is the
# only thing standing between "an environment exists" and "the relay will dial it", so a name that
# merely contains the prefix must not match.
PREVIEW_ENVIRONMENT_RE = re.compile(r"^uc-nexus-pr-(\d+)$")

# Public hostnames are `<service>-<environment>.up.railway.app`, and the backend service is `backend`
# in every environment. Derived rather than looked up because the derivation is total: any environment
# matching the name pattern above has exactly this address, and asking Railway for domains as well
# would be a second round trip that can fail on its own.
_CHANNEL_URL = "wss://backend-{environment}.up.railway.app/relay-link"

# Long enough that a relay reconciling every ten seconds does not turn into ten Railway calls a minute,
# short enough that a newly opened PR is dialled while somebody is still looking at it.
_CACHE_SECONDS = 60.0

_QUERY = """
query PreviewEnvironments($projectId: String!) {
  environments(projectId: $projectId) {
    edges { node { id name } }
  }
}
"""

# Railway has served the environment list under both shapes. Trying the second only after the first
# errors costs nothing on the happy path and keeps a schema change from silently emptying the list.
_QUERY_FALLBACK = """
query PreviewEnvironments($projectId: String!) {
  project(id: $projectId) {
    environments { edges { node { id name } } }
  }
}
"""

_lock = threading.Lock()
_cache: tuple[float, list[str]] | None = None


def channel_url_for(environment_name: str) -> str:
    """The relay channel URL for a preview environment name."""
    return _CHANNEL_URL.format(environment=environment_name)


def _environment_names(payload: dict) -> list[str]:
    """Environment names out of either response shape, tolerating a missing branch rather than raising.

    Written defensively on purpose: this walks a third party's response, and the cost of a shape we did
    not expect should be an empty list plus a log line, never a 500 on the route that serves it.
    """
    data = payload.get("data") or {}
    container = data.get("environments") or (data.get("project") or {}).get("environments") or {}
    edges = container.get("edges") or []
    names = []
    for edge in edges:
        name = ((edge or {}).get("node") or {}).get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _fetch_environment_names() -> list[str] | None:
    """Every environment name in this Railway project, or None if the API could not be read."""
    headers = {"Authorization": f"Bearer {RAILWAY_API_TOKEN}", "Content-Type": "application/json"}
    variables = {"projectId": RAILWAY_PROJECT_ID}
    last_errors: object = None
    for query in (_QUERY, _QUERY_FALLBACK):
        try:
            response = httpx.post(
                RAILWAY_API_URL,
                json={"query": query, "variables": variables},
                headers=headers,
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as e:
            logger.warning(
                "could not reach the Railway API for preview channel discovery",
                extra={"error": str(e), "url": RAILWAY_API_URL},
            )
            return None
        if payload.get("errors"):
            last_errors = payload["errors"]
            continue
        return _environment_names(payload)
    logger.warning(
        "the Railway API refused both environment queries; preview channel discovery is off until "
        "this is fixed, and the relay keeps whatever it already had",
        extra={"errors": str(last_errors)[:500]},
    )
    return None


def discover_preview_channels(*, force: bool = False) -> list[str]:
    """Channel URLs for every live preview environment, newest PR first.

    Empty - never an exception - when discovery is off or unavailable. `force` skips the cache and is
    for tests; callers on the request path should take the cached answer.
    """
    global _cache

    if not RAILWAY_API_TOKEN or not RAILWAY_PROJECT_ID:
        return []

    with _lock:
        now = time.monotonic()
        if not force and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
            return list(_cache[1])

        names = _fetch_environment_names()
        if names is None:
            # Serve the last good answer rather than an empty one: a blip in Railway's API should not
            # tear down working channels on the relay, and the relay's own merge treats an empty list
            # as "discovered nothing", which is indistinguishable from "every PR closed".
            if _cache is not None:
                return list(_cache[1])
            return []

        matched = sorted(
            (name for name in names if PREVIEW_ENVIRONMENT_RE.match(name)),
            key=lambda name: int(PREVIEW_ENVIRONMENT_RE.match(name).group(1)),
            reverse=True,
        )
        urls = [channel_url_for(name) for name in matched]
        if _cache is None or _cache[1] != urls:
            logger.info(
                "preview relay channels discovered",
                extra={"count": len(urls), "environments": matched},
            )
        _cache = (now, urls)
        return list(urls)


def reset_cache() -> None:
    """Drop the memoized answer. Tests only."""
    global _cache
    with _lock:
        _cache = None
