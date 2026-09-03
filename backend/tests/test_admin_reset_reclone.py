"""POST /admin/reset-data on a preview environment re-clones production instead of emptying itself.

A preview's data IS production's data, taken at first boot, so "reset" there means "take it again".
The two things worth pinning: the preview branch never runs the preservation snapshot or the GP job
sync (both exist to rescue rows the clone already brings, and the sync pass talks to a live GP), and
a deployment that is NOT a preview - or a preview with no clone source - keeps the old behaviour
exactly, because that path still guards a real database.

No database and no pg_dump: the engine, the clone and the alembic upgrade are all stood in for.
"""

import pytest
from fastapi.testclient import TestClient

import app.config
import main
from app import preview_clone


class _FakeConnection:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, *args, **kwargs):
        self.log.append(str(statement).strip())
        return None

    def commit(self):
        self.log.append("COMMIT")


class _FakeEngine:
    def __init__(self):
        self.log: list[str] = []

    def connect(self):
        return _FakeConnection(self.log)


@pytest.fixture
def preview(monkeypatch):
    """An admin-authenticated call on a preview environment that can reach production."""
    import app.database

    monkeypatch.setattr(app.config, "TESTING_ENABLED", True, raising=False)
    monkeypatch.setattr(app.config, "RAILWAY_ENVIRONMENT_NAME", "uc-nexus-pr-42")
    monkeypatch.setattr(app.config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(app.config, "PREVIEW_CLONE_PASSWORD", "s3cret")
    monkeypatch.setattr(main, "require_admin_request", lambda request: None)

    engine = _FakeEngine()
    monkeypatch.setattr(app.database, "engine", engine)
    return engine


@pytest.fixture
def cloned(monkeypatch):
    """Stands in for pg_dump | pg_restore, recording the source it was aimed at."""
    calls: list[str] = []
    result = preview_clone.CloneResult(
        source_revision="104_gp_company_discovery",
        table_counts={"projects": 12, "hardware_items": 900, "notifications": 0},
        outbox_cancelled=2,
    )

    def _clone(source_url):
        calls.append(source_url)
        return result

    monkeypatch.setattr(preview_clone, "clone_production_into_this_database", _clone)
    monkeypatch.setattr(preview_clone, "table_row_counts", lambda conn: dict(result.table_counts))

    import alembic.command

    upgrades: list[str] = []
    monkeypatch.setattr(alembic.command, "upgrade", lambda cfg, rev: upgrades.append(rev))
    return calls, upgrades


def test_a_preview_reset_re_clones_production(preview, cloned):
    calls, upgrades = cloned

    body = TestClient(main.app).post("/admin/reset-data").json()

    assert body["status"] == "ok"
    assert body["message"].startswith("re-cloned production into this PR")
    assert body["cloned"] is True
    assert body["source_revision"] == "104_gp_company_discovery"
    assert body["rows"] == 912
    assert body["tables"] == 3
    assert body["table_counts"]["hardware_items"] == 900
    assert body["gp_writes_cancelled"] == 2

    # Aimed at production's public proxy as the read-only role, not at anything local.
    assert calls == [app.config.preview_clone_source_url()]
    # The copy carries production's revision; this branch's migrations move it forward, same as boot.
    assert upgrades == ["head"]
    # The schema is emptied first so pg_restore lands on nothing.
    assert "DROP SCHEMA public CASCADE" in preview.log
    assert "CREATE SCHEMA public" in preview.log


def test_a_preview_reset_preserves_nothing_and_syncs_nothing(preview, cloned, monkeypatch):
    """reset_preservation exists to rescue the relay install, the warehouses and the buyer assignments
    from a DROP. The clone brings all three, so snapshotting them would be restoring rows over
    identical rows - and the GP job sync would re-adopt projects the clone just delivered."""
    from app.services import gp_job_sync, reset_preservation

    monkeypatch.setattr(reset_preservation, "snapshot", lambda conn: pytest.fail("must not snapshot"))
    monkeypatch.setattr(gp_job_sync, "run_once_blocking", lambda: pytest.fail("must not sync GP"))

    assert TestClient(main.app).post("/admin/reset-data").json()["status"] == "ok"


def test_a_preview_with_no_clone_source_keeps_the_old_behaviour(preview, cloned, monkeypatch):
    """A preview forked before PREVIEW_CLONE_PASSWORD existed has nothing to clone from, and must
    fall through to the drop-and-rebuild path rather than fail."""
    monkeypatch.setattr(app.config, "PREVIEW_CLONE_PASSWORD", "")
    calls, _ = cloned

    reached: list[str] = []
    monkeypatch.setattr(main, "_reset_by_recloning", lambda src: reached.append(src))
    # The old path needs a real database; stop it at the snapshot rather than let it run.
    from app.services import reset_preservation

    monkeypatch.setattr(reset_preservation, "snapshot", lambda conn: (_ for _ in ()).throw(RuntimeError("old path")))

    with pytest.raises(RuntimeError, match="old path"):
        TestClient(main.app, raise_server_exceptions=True).post("/admin/reset-data")

    assert reached == []
    assert calls == []


def test_production_never_re_clones(preview, cloned, monkeypatch):
    """The clone OVERWRITES the database it runs against. On production that would be a self-restore
    of a stale dump; the environment check is the only thing preventing it."""
    monkeypatch.setattr(app.config, "RAILWAY_ENVIRONMENT_NAME", "production")
    calls, _ = cloned

    reached: list[str] = []
    monkeypatch.setattr(main, "_reset_by_recloning", lambda src: reached.append(src))
    from app.services import reset_preservation

    monkeypatch.setattr(reset_preservation, "snapshot", lambda conn: (_ for _ in ()).throw(RuntimeError("old path")))

    with pytest.raises(RuntimeError, match="old path"):
        TestClient(main.app, raise_server_exceptions=True).post("/admin/reset-data")

    assert reached == []
    assert calls == []


def test_a_failed_re_clone_says_the_database_is_now_empty(preview, cloned, monkeypatch):
    """The schema is already dropped by then, so a bare 500 would leave somebody guessing at why the
    app is suddenly blank. The next deploy's entrypoint clones into it again."""

    def _fail(_source):
        raise preview_clone.CloneError("pg_dump of production failed (exit 1): connection refused")

    monkeypatch.setattr(preview_clone, "clone_production_into_this_database", _fail)

    resp = TestClient(main.app).post("/admin/reset-data")

    assert resp.status_code == 500
    assert resp.json()["code"] == "CLONE_FAILED"
    assert "now empty" in resp.json()["error"]
