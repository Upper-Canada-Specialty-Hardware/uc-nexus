"""Preview channel discovery: the relay learning which PR environments exist instead of being told.

#414 let the relay hold more than one backend URL and #456 let that list change without a restart, but
the list itself still came from a TOML file on this one workstation - edited by hand, on a machine
nobody testing is sitting at. Railway creates a preview environment per PR automatically, so anything
created after the last edit was invisible, and every PR needing a real GP channel waited on somebody
walking over here.

The relay now asks the production backend which previews exist and unions the answer with its file.
That means an answer from the network decides what a GP-credentialed process dials, so the checks that
matter here are the ones that keep that answer from meaning too much:

- it can only ADD to what config.toml names, never replace or reorder it
- only the exact preview hostname shape is accepted, so no answer can name an arbitrary host
- a discovered URL can never become the primary channel, so it always inherits the sandbox company pin
- an unreachable backend keeps the last good list rather than retiring live channels
"""

import asyncio
import json

import pytest

from ucnexus_relay import channel
from ucnexus_relay.config import PRODUCTION_BACKEND_URL

PR_URL = "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"
OTHER_PR_URL = "wss://backend-uc-nexus-pr-510.up.railway.app/relay-link"


@pytest.fixture(autouse=True)
def _reset_discovery_state():
    channel._discovered = None
    channel._discovered_at = 0.0
    yield
    channel._discovered = None
    channel._discovered_at = 0.0


class _Settings:
    def __init__(self, secret="enrolled-secret", enabled=True):
        self.channel = type("C", (), {"discover_preview_backends": enabled})()
        self.auth = type("A", (), {"shared_secret": secret})()


def _serve(monkeypatch, urls, *, settings=None, record=None):
    """Point discovery at a canned /relay-channels answer."""
    resolved = settings or _Settings()
    monkeypatch.setattr(channel, "get_settings", lambda: resolved)

    def _fetch(primary, secret):
        if record is not None:
            record.append((primary, secret))
        return list(urls)

    monkeypatch.setattr(channel, "_fetch_discovered_urls", _fetch)


def _discover(configured):
    """Kick a refresh, let it finish, then read what the reconcile loop would see.

    Two steps because discovery is deliberately never awaited on the reconcile path - the loop reads
    the last known list and picks a new one up on a later tick.
    """

    async def _run():
        task = channel._maybe_refresh_discovery(configured)
        if task is not None:
            await task
        return channel._discovered_urls()

    return asyncio.run(_run())


# --- the endpoint the relay derives ---------------------------------------------------------------


def test_the_channel_list_is_read_off_the_production_backend():
    # Derived rather than configured: another URL to keep in step is another thing to get wrong, and
    # the relay already knows production's address as a baked-in constant.
    assert (
        channel._discovery_endpoint(PRODUCTION_BACKEND_URL)
        == "https://backend-production-7866.up.railway.app/relay-channels"
    )


# --- what a discovered answer may contain ---------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "wss://attacker.example.com/relay-link",
        "wss://backend-uc-nexus-pr-554.attacker.example.com/relay-link",
        "ws://backend-uc-nexus-pr-554.up.railway.app/relay-link",  # downgraded to plaintext
        "wss://backend-uc-nexus-pr-554.up.railway.app/something-else",
        "wss://backend-production-7866.up.railway.app/relay-link",  # production, which must stay primary-by-config
        "https://backend-uc-nexus-pr-554.up.railway.app/relay-link",
    ],
)
def test_only_the_preview_hostname_shape_is_accepted(monkeypatch, hostile):
    # This is the load-bearing check on the relay side: the process holds GP credentials, so "the
    # backend said so" is not on its own a reason to dial a host.
    monkeypatch.setattr(
        channel.urllib.request,
        "urlopen",
        _canned_response({"urls": [hostile, PR_URL]}),
    )
    assert channel._fetch_discovered_urls(PRODUCTION_BACKEND_URL, "secret") == [PR_URL]


def test_a_malformed_body_discovers_nothing_rather_than_raising(monkeypatch):
    monkeypatch.setattr(channel.urllib.request, "urlopen", _canned_response({"unexpected": True}))
    assert channel._fetch_discovered_urls(PRODUCTION_BACKEND_URL, "secret") is None


def test_the_enrolled_secret_authenticates_the_read(monkeypatch):
    seen = {}

    def _urlopen(request, timeout=None):
        seen["auth"] = request.get_header("Authorization")
        seen["url"] = request.full_url
        return _Body({"urls": []})

    monkeypatch.setattr(channel.urllib.request, "urlopen", _urlopen)
    channel._fetch_discovered_urls(PRODUCTION_BACKEND_URL, "enrolled-secret")
    # The same credential as the channel handshake: discovery adds no new secret to distribute, and a
    # caller that could read this could already open the socket.
    assert seen["auth"] == "Bearer enrolled-secret"
    assert seen["url"].endswith("/relay-channels")


# --- how a discovered answer joins the configured one ---------------------------------------------


def test_discovered_channels_are_added_to_the_configured_ones(monkeypatch):
    _serve(monkeypatch, [PR_URL])
    assert _discover([PRODUCTION_BACKEND_URL]) == [PR_URL]


def test_discovery_needs_a_production_channel_to_ask(monkeypatch):
    # A dev checkout pointed only at localhost has nobody to ask and must not invent one.
    called = []
    _serve(monkeypatch, [PR_URL], record=called)
    assert _discover(["wss://localhost:8000/relay-link"]) == []
    assert called == []


def test_discovery_can_be_switched_off(monkeypatch):
    _serve(monkeypatch, [PR_URL], settings=_Settings(enabled=False))
    assert _discover([PRODUCTION_BACKEND_URL]) == []


def test_an_unreachable_backend_keeps_the_channels_already_known(monkeypatch):
    # Retiring a channel on a blip would drop a live preview connection and re-make it a minute later.
    _serve(monkeypatch, [PR_URL])
    assert _discover([PRODUCTION_BACKEND_URL]) == [PR_URL]

    channel._discovered_at = 0.0  # force a refresh
    monkeypatch.setattr(channel, "_fetch_discovered_urls", lambda primary, secret: None)
    assert _discover([PRODUCTION_BACKEND_URL]) == [PR_URL]


def test_discovery_never_blocks_the_reconcile_tick(monkeypatch):
    # The first tick of a fresh relay is what brings PRODUCTION's channel up. Awaiting a ten second
    # HTTP timeout there would hold that up for a test backend, which is the wrong trade every time.
    monkeypatch.setattr(channel, "get_settings", lambda: _Settings())
    started = asyncio.Event()

    def _slow(primary, secret):
        started.set()
        raise AssertionError("must not run inline on the reconcile path")

    monkeypatch.setattr(channel, "_fetch_discovered_urls", _slow)

    async def _run():
        task = channel._maybe_refresh_discovery([PRODUCTION_BACKEND_URL])
        # A task was scheduled, and nothing has run yet: the loop reads the (empty) known list and
        # carries straight on to reconciling production.
        assert task is not None
        assert not started.is_set()
        assert channel._discovered_urls() == []
        task.cancel()

    asyncio.run(_run())


def test_an_empty_answer_really_does_retire_discovered_channels(monkeypatch):
    # The other half: "asked, and every PR is closed" has to be distinguishable from "could not ask",
    # or a torn-down environment is dialled forever.
    _serve(monkeypatch, [PR_URL, OTHER_PR_URL])
    assert _discover([PRODUCTION_BACKEND_URL]) == [PR_URL, OTHER_PR_URL]

    channel._discovered_at = 0.0
    _serve(monkeypatch, [])
    assert _discover([PRODUCTION_BACKEND_URL]) == []


def test_the_backend_is_not_asked_on_every_reconcile_tick(monkeypatch):
    # The reconcile loop runs every ten seconds; the answer changes when a PR opens or closes.
    calls = []
    _serve(monkeypatch, [PR_URL], record=calls)
    for _ in range(5):
        _discover([PRODUCTION_BACKEND_URL])
    assert len(calls) == 1


# --- helpers --------------------------------------------------------------------------------------


class _Body:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _canned_response(payload):
    def _urlopen(request, timeout=None):
        return _Body(payload)

    return _urlopen
