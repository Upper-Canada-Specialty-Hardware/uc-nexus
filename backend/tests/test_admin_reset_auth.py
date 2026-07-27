"""POST /admin/reset-data must refuse before it can do anything destructive.

This endpoint drops and rebuilds the whole public schema. It shipped with NO auth and no environment
check on a public Railway domain, so any unauthenticated caller who knew the URL could destroy
production - including relay_installs, which silently orphans the on-prem relay and takes every GP
write down with it.

Every test here exercises a REFUSAL path only. None of them may reach the DROP SCHEMA: a test that
actually ran the reset would wipe the developer's database mid-suite.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """A client with the environment gate open, so the tests below land on the AUTH gate. The route
    does a function-local `from app.config import TESTING_ENABLED`, so patching the module attribute
    takes effect per call - no reimport of `main`, which would rebuild the app and the relay gateway
    singleton underneath the rest of the suite."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    return TestClient(main.app)


def test_reset_is_refused_when_testing_is_disabled(monkeypatch):
    """The environment gate is checked before auth, so a production deployment refuses the call
    outright rather than leaking whether the caller's token would have been good enough."""
    import app.config
    import main

    monkeypatch.setattr(app.config, "TESTING_ENABLED", False, raising=False)
    resp = TestClient(main.app).post("/admin/reset-data")

    assert resp.status_code == 403
    assert "not enabled" in resp.json()["error"].lower()


def test_reset_is_refused_without_a_token(client):
    """No Authorization header: unauthenticated, and nothing is dropped."""
    resp = client.post("/admin/reset-data")

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"


def test_reset_is_refused_with_a_garbage_token(client):
    """A malformed bearer token fails Clerk verification rather than falling through to the reset."""
    resp = client.post("/admin/reset-data", headers={"Authorization": "Bearer not-a-real-jwt"})

    assert resp.status_code == 401
    assert resp.json()["code"] == "UNAUTHENTICATED"
