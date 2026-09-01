"""A preview environment announcing itself to production (#654).

The other half of the registry. What has to hold here is that it is genuinely best effort: production
being unreachable, refusing, or slow must never delay this backend's startup or its shutdown, because
what fails is only "the workstation relay is not told about this preview".

No network: every test drives the module's own httpx call site.
"""

import asyncio

import pytest

from app import config
from app.services import preview_announce

ORIGIN = "https://backend-production-7866.up.railway.app"
SECRET = "preview-registry-secret-value"


class _Response:
    def __init__(self, status_code=204):
        self.status_code = status_code
        self.text = ""


class _FakeClient:
    """Records the calls an AsyncClient would have made."""

    def __init__(self, calls, response=None, error=None, **kwargs):
        self.calls = calls
        self.response = response or _Response()
        self.error = error
        self.init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json, headers))
        if self.error:
            raise self.error
        return self.response

    async def delete(self, url, headers=None):
        self.calls.append(("DELETE", url, None, headers))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def calls(monkeypatch):
    recorded: list[tuple] = []
    monkeypatch.setattr(preview_announce, "PREVIEW_REGISTRY_SECRET", SECRET)
    monkeypatch.setattr(preview_announce, "PRODUCTION_BACKEND_ORIGIN", ORIGIN)
    monkeypatch.setattr(preview_announce, "RAILWAY_ENVIRONMENT_NAME", "uc-nexus-pr-9")
    monkeypatch.setattr(
        preview_announce.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(recorded, **kwargs),
    )
    return recorded


def test_an_announcement_names_this_environment_and_carries_the_secret(calls):
    assert asyncio.run(preview_announce.announce_once()) is True
    method, url, body, headers = calls[0]
    assert (method, url) == ("POST", f"{ORIGIN}/preview-channels")
    assert body == {"environment": "uc-nexus-pr-9"}
    assert headers == {"X-Preview-Registry-Secret": SECRET}


def test_a_withdrawal_addresses_this_environment(calls):
    assert asyncio.run(preview_announce.withdraw_once()) is True
    method, url, _, headers = calls[0]
    assert (method, url) == ("DELETE", f"{ORIGIN}/preview-channels/uc-nexus-pr-9")
    assert headers == {"X-Preview-Registry-Secret": SECRET}


def test_an_unreachable_production_is_not_an_error(calls, monkeypatch, caplog):
    # Startup must not depend on production answering. What fails is that the relay is not told about
    # this preview, which is exactly where things stood before any of this existed.
    monkeypatch.setattr(
        preview_announce.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(calls, error=RuntimeError("getaddrinfo failed"), **kwargs),
    )
    with caplog.at_level("WARNING", logger=preview_announce.__name__):
        assert asyncio.run(preview_announce.announce_once()) is False
    # The reason has to be IN the message: the backend logs through the stdlib's default formatter,
    # which drops every `extra` field, and a Railway deploy log is the only place this is read.
    assert "getaddrinfo failed" in caplog.records[-1].getMessage()


def test_a_refusal_is_reported_and_swallowed(calls, monkeypatch):
    monkeypatch.setattr(
        preview_announce.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(calls, response=_Response(401), **kwargs),
    )
    assert asyncio.run(preview_announce.announce_once()) is False


def test_a_failing_withdrawal_never_holds_up_shutdown(calls, monkeypatch):
    monkeypatch.setattr(
        preview_announce.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeClient(calls, error=RuntimeError("connection reset"), **kwargs),
    )
    assert asyncio.run(preview_announce.withdraw_once()) is False


def test_nothing_is_sent_without_a_registry_secret(monkeypatch, caplog):
    monkeypatch.setattr(preview_announce, "PREVIEW_REGISTRY_SECRET", "")

    def _explode(**kwargs):  # pragma: no cover - must never run
        raise AssertionError("a preview with no secret must not call production")

    monkeypatch.setattr(preview_announce.httpx, "AsyncClient", _explode)
    with caplog.at_level("WARNING", logger=preview_announce.__name__):
        assert asyncio.run(preview_announce.announce_once()) is False
    assert "PREVIEW_REGISTRY_SECRET" in caplog.records[-1].getMessage()
    assert asyncio.run(preview_announce.withdraw_once()) is False


def test_the_request_timeout_is_short(calls):
    # Nothing downstream waits on this call, and a hung request at shutdown would hold the deploy.
    asyncio.run(preview_announce.announce_once())
    assert preview_announce.REQUEST_TIMEOUT_SECONDS <= 5.0


@pytest.mark.parametrize(
    ("environment", "real_relay", "expected"),
    [
        ("uc-nexus-pr-9", True, True),
        ("uc-nexus-pr-9", False, False),  # the default preview runs its own stub; nothing to ask for
        ("production", True, False),  # production never announces itself to itself
        ("", True, False),  # local dev
    ],
)
def test_only_a_preview_that_wants_the_real_relay_announces(monkeypatch, environment, real_relay, expected):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", environment)
    monkeypatch.setattr(preview_announce, "PREVIEW_REAL_RELAY", real_relay)
    assert preview_announce.enabled() is expected
