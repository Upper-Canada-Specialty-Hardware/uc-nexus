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


def _snapshot_must_not_run(*_args, **_kwargs):
    raise AssertionError("the reset reached its snapshot; a refused reset must stop before it")


def test_reset_is_refused_while_another_reset_holds_the_lock(client, monkeypatch):
    """#1319: a second reset while one is running gets 409 and never reaches the snapshot or the drop.
    Auth is waved through and the lock is reported held, so nothing here touches the database."""
    import main
    from app.services import reset_preservation

    monkeypatch.setattr(main, "require_admin_request", lambda _request: None)
    monkeypatch.setattr(main, "_acquire_reset_lock", lambda: None)
    monkeypatch.setattr(reset_preservation, "snapshot", _snapshot_must_not_run)

    resp = client.post("/admin/reset-data")

    assert resp.status_code == 409
    assert resp.json()["code"] == "CONFLICT"


def test_reset_releases_the_lock_when_it_fails(client, monkeypatch):
    """#1319: a reset that fails partway still releases its lock, so the next one is not refused for
    good. The engine refuses its first connection, before the snapshot, so no schema is touched."""
    import app.database
    import main

    class _NoConnectEngine:
        def connect(self):
            raise RuntimeError("no database in this test")

    lock_conn = object()
    released = []
    monkeypatch.setattr(main, "require_admin_request", lambda _request: None)
    monkeypatch.setattr(main, "_acquire_reset_lock", lambda: lock_conn)
    monkeypatch.setattr(main, "_release_reset_lock", released.append)
    monkeypatch.setattr(app.database, "engine", _NoConnectEngine())

    with pytest.raises(RuntimeError, match="no database in this test"):
        client.post("/admin/reset-data")

    assert released == [lock_conn]


def test_reset_lock_is_held_by_one_caller_at_a_time():
    """#1319, against Postgres: while one connection holds the reset lock, a second try gets None; once
    released, the next try gets it. Only the advisory lock is taken - no reset runs."""
    import os

    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; skipping DB-backed tests")
    import main

    first = main._acquire_reset_lock()
    assert first is not None
    try:
        assert main._acquire_reset_lock() is None
    finally:
        main._release_reset_lock(first)

    again = main._acquire_reset_lock()
    assert again is not None
    main._release_reset_lock(again)
