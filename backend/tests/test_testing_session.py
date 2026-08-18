"""GET /testing/session - the hands-off preview sign-in link, and the gates that keep it a
preview-only door to one dedicated account (preview-env autonomy plan).

The link sits in a public PR comment, so its safety rests on two properties this file pins: it mints
ONLY the e2e account (never a caller-chosen email, unlike /testing/clerk-sign-in), and it answers only
on a preview environment, behind a per-env key. The production refusal of the account it mints is the
other half, pinned in test_e2e_account_production_deny.py. The success test fakes the Clerk Backend
API; nothing here may hit api.clerk.com.
"""

import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

_KEY = "correct-horse-battery-staple"
_KEY_HASH = hashlib.sha256(_KEY.encode("utf-8")).hexdigest()
_E2E_USER = "user_e2e_tester"


@pytest.fixture
def client(monkeypatch):
    """A preview environment with testing on, the key hash and the e2e account configured, so each
    test lands on the gate it names rather than an earlier one. The route does function-local
    `from app.config import ...`, so patching the module attributes takes effect per call - no reimport
    of main, which would rebuild the app and the relay gateway singleton under the rest of the suite."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    monkeypatch.setattr(app.config, "RAILWAY_ENVIRONMENT_NAME", "uc-nexus-pr-999", raising=False)
    monkeypatch.setattr(app.config, "TESTING_SESSION_KEY_HASH", _KEY_HASH, raising=False)
    monkeypatch.setattr(app.config, "E2E_CLERK_USER_ID", _E2E_USER, raising=False)
    return TestClient(main.app)


def _fake_mint(monkeypatch):
    """Fake the one Clerk call the success path makes, capturing the body it posted."""
    calls: dict = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"token": "tok_test"}

    def _post(url, headers=None, json=None):
        calls["url"] = url
        calls["json"] = json
        return _Resp()

    monkeypatch.setattr(httpx, "post", _post)
    return calls


def test_refused_when_testing_disabled(client, monkeypatch):
    import app.config

    monkeypatch.setattr(app.config, "TESTING_ENABLED", False, raising=False)
    resp = client.get("/testing/session", params={"key": _KEY}, follow_redirects=False)

    assert resp.status_code == 403
    assert "not enabled" in resp.json()["error"].lower()


def test_refused_on_a_non_preview_environment_even_with_a_valid_key(client, monkeypatch):
    """The load-bearing environment gate. Production shares the Clerk instance, so this route must not
    answer there however its variables are set - and a correct key buys nothing past it."""
    import app.config

    monkeypatch.setattr(app.config, "RAILWAY_ENVIRONMENT_NAME", "production", raising=False)
    resp = client.get("/testing/session", params={"key": _KEY}, follow_redirects=False)

    assert resp.status_code == 403
    assert "preview" in resp.json()["error"].lower()


def test_refused_with_a_wrong_key(client):
    resp = client.get("/testing/session", params={"key": "not-the-key"}, follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_refused_with_no_key(client):
    resp = client.get("/testing/session", follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_key_path_is_closed_when_no_hash_is_configured(client, monkeypatch):
    """An empty TESTING_SESSION_KEY_HASH must fail CLOSED: any key against a blank hash never compares
    equal, so a preview with the variable unset stays shut rather than opening to an empty key."""
    import app.config

    monkeypatch.setattr(app.config, "TESTING_SESSION_KEY_HASH", "", raising=False)
    resp = client.get("/testing/session", params={"key": ""}, follow_redirects=False)

    assert resp.status_code == 401


def test_a_missing_e2e_account_is_a_500_not_a_401(client, monkeypatch):
    """The key checked out; the environment simply has no account to mint. That is a provisioning gap
    on this backend, and must not read back as a bad key."""
    import app.config

    monkeypatch.setattr(app.config, "E2E_CLERK_USER_ID", "", raising=False)
    resp = client.get("/testing/session", params={"key": _KEY}, follow_redirects=False)

    assert resp.status_code == 500


def test_success_mints_the_e2e_account_only_and_redirects_to_this_previews_frontend(client, monkeypatch):
    calls = _fake_mint(monkeypatch)
    resp = client.get("/testing/session", params={"key": _KEY}, follow_redirects=False)

    assert resp.status_code == 302
    # Minted for the e2e account and nothing the caller chose - no email, no other selectable id.
    assert calls["json"]["user_id"] == _E2E_USER
    assert "email" not in calls["json"]
    # Bounced to THIS environment's frontend, derived from the env name, carrying the Clerk ticket.
    location = resp.headers["location"]
    assert location.startswith("https://frontend-uc-nexus-pr-999.up.railway.app/?__clerk_ticket=tok_test")
