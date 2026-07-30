"""GET /testing/clerk-sign-in must refuse anonymous callers (#422).

The endpoint mints a REAL Clerk sign-in token - every environment shares the production Clerk
instance - so an ungated call is an impersonation primitive for any staff account, Admin/Manager
included. It shipped gated on TESTING_ENABLED alone, and that variable was true on the shared
production backend, so anyone who knew the URL could sign in as anyone (#424 flipped the variable;
this pins the auth that should have been there regardless).

Two credentials open it: an existing Admin/Manager session, or the shared testing secret in
X-Testing-Secret - the bootstrap path for a fresh PR environment where no session exists yet. The
success-path tests fake the Clerk Backend API; nothing here may hit api.clerk.com.
"""

import hashlib

import pytest
from fastapi.testclient import TestClient

_SECRET = "correct-horse-battery-staple"
_SECRET_HASH = hashlib.sha256(_SECRET.encode("utf-8")).hexdigest()


@pytest.fixture
def client(monkeypatch):
    """A client with the environment gate open and the secret hash configured, so the tests below
    land on the AUTH gate. The route does a function-local `from app.config import ...`, so patching
    the module attributes takes effect per call - no reimport of `main`, which would rebuild the app
    and the relay gateway singleton underneath the rest of the suite."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    monkeypatch.setattr(app.config, "TESTING_SIGN_IN_SECRET_HASH", _SECRET_HASH, raising=False)
    return TestClient(main.app)


def test_sign_in_is_refused_when_testing_is_disabled(monkeypatch):
    """The environment gate is checked before auth, so a production deployment refuses the call
    outright rather than leaking whether the caller's credential would have been good enough."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", False, raising=False)
    resp = TestClient(main.app).get("/testing/clerk-sign-in")

    assert resp.status_code == 403
    assert "not enabled" in resp.json()["error"].lower()


def test_sign_in_is_refused_without_any_credential(client):
    resp = client.get("/testing/clerk-sign-in")

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_sign_in_is_refused_with_a_wrong_secret(client):
    resp = client.get("/testing/clerk-sign-in", headers={"X-Testing-Secret": "not-the-secret"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_sign_in_is_refused_with_a_garbage_bearer_token(client):
    resp = client.get("/testing/clerk-sign-in", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_secret_path_is_disabled_when_no_hash_is_configured(client, monkeypatch):
    """An empty TESTING_SIGN_IN_SECRET_HASH must fail CLOSED: presenting an empty-ish or any secret
    against a blank hash falls through to the admin path, it never compares equal."""
    import app.config

    monkeypatch.setattr(app.config, "TESTING_SIGN_IN_SECRET_HASH", "", raising=False)
    resp = client.get("/testing/clerk-sign-in", headers={"X-Testing-Secret": ""})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_sign_in_succeeds_with_the_correct_secret(client, monkeypatch):
    """The bootstrap path: the right preimage in X-Testing-Secret needs no session. Clerk is faked -
    the assertion is that the request got past auth and returned the token Clerk minted."""
    import httpx

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse([{"id": "user_test"}]))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"token": "tok_test", "url": "https://x"}))

    resp = client.get("/testing/clerk-sign-in", headers={"X-Testing-Secret": _SECRET})

    assert resp.status_code == 200
    assert resp.json() == {"token": "tok_test", "url": "https://x", "user_id": "user_test"}
