"""The preview channel registry and its two routes (#654).

This is what replaced the Railway-API poll: a preview environment announces itself to production,
production holds the list, and the list is pushed down the relay socket instead of served on a GET the
relay polled with a second copy of its credential.

The tests that matter most are the refusals. These routes decide which hosts the one GP-credentialed
relay is told to dial, so the gate (production only, shared secret, anchored name) is the whole of the
security story, and every one of its three parts is here.

No database and no network: the registry is in-memory and the push is stubbed.
"""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.services import preview_registry
from main import app

SECRET = "preview-registry-secret-value"
PR_9 = "uc-nexus-pr-9"
PR_554 = "uc-nexus-pr-554"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_registry():
    preview_registry.reset()
    yield
    preview_registry.reset()


@pytest.fixture
def on_production(monkeypatch):
    """Production, with a registry secret configured - the only environment where these routes exist."""
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setattr(config, "PREVIEW_REGISTRY_SECRET", SECRET)


@pytest.fixture
def pushed(monkeypatch):
    """Capture what would go down the relay socket."""
    sent: list[list[str]] = []

    class _Gateway:
        async def push_channels(self, urls):
            sent.append(list(urls))

    monkeypatch.setattr(preview_registry, "gateway", _Gateway())
    return sent


def _announce(environment=PR_9, secret=SECRET):
    headers = {"X-Preview-Registry-Secret": secret} if secret is not None else {}
    return client.post("/preview-channels", json={"environment": environment}, headers=headers)


def _withdraw(environment=PR_9, secret=SECRET):
    headers = {"X-Preview-Registry-Secret": secret} if secret is not None else {}
    return client.delete(f"/preview-channels/{environment}", headers=headers)


def test_an_announcement_becomes_a_channel(on_production, pushed):
    assert _announce().status_code == 204
    assert preview_registry.channels() == ["wss://backend-uc-nexus-pr-9.up.railway.app/relay-link"]
    assert pushed == [["wss://backend-uc-nexus-pr-9.up.railway.app/relay-link"]]


def test_a_repeat_announcement_is_a_heartbeat_not_a_change(on_production, pushed):
    # The relay is told the whole list every time it changes; a heartbeat from something already listed
    # changes nothing, and pushing it anyway would be a frame every two minutes per live preview.
    _announce()
    _announce()
    _announce()
    assert len(pushed) == 1


def test_the_newest_pr_is_offered_first(on_production, pushed):
    # Ordered by PR number rather than by announcement order: the environment somebody is waiting on is
    # almost always the newest one, and the relay logs the list it was handed.
    _announce(PR_9)
    _announce(PR_554)
    assert preview_registry.channels() == [
        "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link",
        "wss://backend-uc-nexus-pr-9.up.railway.app/relay-link",
    ]


def test_a_withdrawal_removes_the_channel(on_production, pushed):
    _announce()
    assert _withdraw().status_code == 204
    assert preview_registry.channels() == []
    # The empty list is pushed too: "there are no previews" is a real answer, and the relay retires a
    # channel that stops being listed.
    assert pushed[-1] == []


def test_withdrawing_something_that_is_not_listed_is_still_a_success(on_production, pushed):
    # Idempotent: the caller's intent - stop dialling me - is satisfied either way, and a preview whose
    # entry already expired must not see an error on the way down.
    assert _withdraw().status_code == 204
    assert pushed == []  # nothing changed, so nothing is pushed


def test_the_secret_is_required(on_production):
    assert _announce(secret=None).status_code == 401
    assert _withdraw(secret=None).status_code == 401
    assert preview_registry.channels() == []


def test_a_wrong_secret_is_refused(on_production):
    assert _announce(secret=SECRET + "x").status_code == 401
    assert _announce(secret="").status_code == 401
    assert preview_registry.channels() == []


def test_a_backend_with_no_configured_secret_accepts_nothing(monkeypatch):
    # Blank config must fail CLOSED. A compare against "" would otherwise let a caller presenting ""
    # register whatever it liked.
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setattr(config, "PREVIEW_REGISTRY_SECRET", "")
    assert _announce(secret="").status_code == 401
    assert _announce(secret="anything").status_code == 401


@pytest.mark.parametrize("environment_name", ["", "uc-nexus-pr-9", "staging"])
def test_the_routes_do_not_exist_off_production(monkeypatch, environment_name):
    """A preview must not be able to advertise other previews to the workstation relay. Checked FIRST,
    ahead of the secret, so a non-production backend gives the same answer whatever is presented -
    and every preview inherits the secret from production, so the environment check is the real gate."""
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", environment_name)
    monkeypatch.setattr(config, "PREVIEW_REGISTRY_SECRET", SECRET)
    assert _announce().status_code == 404
    assert _withdraw().status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        "pr-554",  # the shape the runbook warns about; Railway does not name environments this way
        "uc-nexus-pr-554-old",
        "not-uc-nexus-pr-554",
        "uc-nexus-pr-",
        "uc-nexus-pr-abc",
        "production",
        "evil.example.com",
    ],
)
def test_a_name_that_is_not_exactly_a_pr_environment_is_refused(on_production, name):
    # The name is the ONLY thing standing between "something authorized posted a string" and "the relay
    # dials the host that string names", so it is anchored, not a prefix test.
    assert _announce(name).status_code == 400
    assert preview_registry.channels() == []


@pytest.mark.parametrize("body", [{}, {"environment": None}, {"environment": 42}, [], "not json"])
def test_a_body_without_a_usable_environment_is_a_400(on_production, body):
    response = client.post("/preview-channels", json=body, headers={"X-Preview-Registry-Secret": SECRET})
    assert response.status_code == 400


def test_a_preview_that_stops_announcing_ages_out(on_production, pushed):
    """Expiry, not the DELETE, is the load-bearing half: a preview environment is deleted by Railway,
    and nothing runs in it afterwards to say so."""
    _announce()
    # Age the entry past the TTL rather than sleeping through it. The stamp is monotonic seconds, so
    # this is exactly the state the registry would be in six minutes later.
    preview_registry._entries[PR_9] -= preview_registry.ENTRY_TTL_SECONDS + 1

    assert preview_registry.prune() is True
    assert preview_registry.channels() == []


def test_a_recent_announcement_is_not_pruned(on_production):
    _announce()
    assert preview_registry.prune() is False
    assert preview_registry.channels() == ["wss://backend-uc-nexus-pr-9.up.railway.app/relay-link"]


def test_the_expiry_window_outlasts_a_missed_announcement():
    # A preview redeploying, cold-starting, or briefly failing to reach production must survive; being
    # dropped and re-added would churn the relay's channel list for nothing.
    from app.services import preview_announce

    assert preview_registry.ENTRY_TTL_SECONDS > 2 * preview_announce.ANNOUNCE_INTERVAL_SECONDS
    assert preview_registry.PRUNE_INTERVAL_SECONDS < preview_registry.ENTRY_TTL_SECONDS


def test_the_channel_url_is_derived_not_looked_up():
    # Railway public hostnames are <service>-<environment>.up.railway.app and the backend service is
    # `backend` in every environment, so the derivation is total for any name matching the pattern.
    assert preview_registry.channel_url_for(PR_554) == "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"
