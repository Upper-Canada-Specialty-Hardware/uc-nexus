"""Cloning production into a preview environment (app/preview_clone.py).

Nothing here touches a database or runs pg_dump. What is worth pinning is the part that decides
whether the clone happens at all and what it does to the copy afterwards:

- the source URL is composed from production's public-proxy coordinates, and is None - not a broken
  string - the moment either half is missing, because that is the "boot empty" signal;
- the refusal off a preview environment, since the clone OVERWRITES the database it runs against and
  the only thing standing between it and production's own is that check;
- the sanitize pass, which is the reason a cloned database is safe to point at the same relay: a GP
  write production had queued must never leave a second time through the preview's channel;
- the argv the two processes are spawned with, because pg_restore's exit code turns a missing flag
  into "the clone failed" on an otherwise perfect restore.
"""

import logging
import subprocess

import pytest
from sqlalchemy.dialects import postgresql

from app import config, preview_clone


@pytest.fixture(autouse=True)
def _proxy_coordinates(monkeypatch):
    """Production's db-admin proxy coordinates, which are what the source URL is built from."""
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(config, "PG_DIRECT_PORT", "28233")
    monkeypatch.setattr(config, "PG_DIRECT_DBNAME", "railway")
    monkeypatch.setattr(config, "PG_DIRECT_SSLMODE", "require")
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", "s3cret-token")


# --- the source URL ------------------------------------------------------------------------------


def test_the_source_url_is_the_public_proxy_as_the_read_only_role():
    """A preview lives in its own Railway project network, so the private hostname production's own
    DATABASE_URL uses is unreachable from it - the public proxy is the whole reason this is composed
    rather than inherited."""
    assert config.preview_clone_source_url() == (
        "postgresql://preview_clone:s3cret-token@switchback.proxy.rlwy.net:28233/railway?sslmode=require"
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_no_host_means_no_clone_source(monkeypatch, blank):
    """Local dev and CI never set PG_DIRECT_HOST. That is not a misconfiguration; it is every
    environment that has no production to clone."""
    monkeypatch.setattr(config, "PG_DIRECT_HOST", blank)
    assert config.preview_clone_source_url() is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_no_password_means_no_clone_source(monkeypatch, blank):
    """A preview forked before PREVIEW_CLONE_PASSWORD was set on production inherits nothing, and
    must boot empty rather than fail."""
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", blank)
    assert config.preview_clone_source_url() is None


def test_the_password_is_url_quoted(monkeypatch):
    """The password is generated, but nothing stops somebody rotating it by hand to something with a
    `@` or a `/` in it - which would silently re-point the URL at another host or another database."""
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", "p@ss/w:rd?#x")
    url = config.preview_clone_source_url()

    assert url == (
        "postgresql://preview_clone:p%40ss%2Fw%3Ard%3F%23x@switchback.proxy.rlwy.net:28233/railway?sslmode=require"
    )
    # The host is still the host: nothing in the password escaped into the authority section.
    assert url.count("@") == 1


def test_the_password_never_reaches_the_command_line():
    """`ps` is readable by every process on the box, and this credential is production's. pg_dump
    takes it in PGPASSWORD instead."""
    url = config.preview_clone_source_url()
    sanitized, password = preview_clone._split_password(url)

    assert password == "s3cret-token"
    assert "s3cret-token" not in sanitized
    assert sanitized == "postgresql://preview_clone@switchback.proxy.rlwy.net:28233/railway?sslmode=require"


def test_the_sqlalchemy_driver_suffix_is_stripped_for_libpq():
    """`postgresql+psycopg2://` is a SQLAlchemy spelling. pg_restore is given DATABASE_URL directly
    and would reject it."""
    sanitized, password = preview_clone._split_password("postgresql+psycopg2://app:pw@db.internal:5432/railway")

    assert password == "pw"
    assert sanitized == "postgresql://app@db.internal:5432/railway"


# --- the pg_dump | pg_restore argv ----------------------------------------------------------------


class _FakeStdout:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakePopen:
    """Enough of Popen for `_run_dump_restore`: the argv and the environment are the whole point."""

    def __init__(self, args, *, stdout=None, stdin=None, stderr=None, env=None):
        self.args = args
        self.stdin = stdin
        self.env = env or {}
        self.stdout = _FakeStdout() if stdout is subprocess.PIPE else None

    def wait(self):
        return 0


@pytest.fixture
def spawned(monkeypatch):
    """Runs `_run_dump_restore` against fake processes and hands back what it tried to spawn."""
    calls: list[_FakePopen] = []

    def _popen(args, **kwargs):
        process = _FakePopen(args, **kwargs)
        calls.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", _popen)
    preview_clone._run_dump_restore(
        "postgresql://preview_clone:s3cret-token@switchback.proxy.rlwy.net:28233/railway?sslmode=require",
        "postgresql://postgres:localpw@postgres.railway.internal:5432/railway",
    )
    return calls


def test_the_restore_cleans_first_so_an_ignored_error_is_not_read_as_failure(spawned):
    """pg_restore exits NON-ZERO whenever it ignored ANY error, and a PG 11+ dump carries the `public`
    schema object - which collides with the empty `public` every target already has, because the
    entrypoint's dirty-state check and the reset both recreate it. Without --clean a healthy restore
    would fail the clone on "schema public already exists"; --if-exists keeps the DROPs no-ops when
    the dump has no schema object to drop."""
    _, restore = spawned

    assert restore.args[0] == "pg_restore"
    assert "--clean" in restore.args
    assert "--if-exists" in restore.args
    assert "--no-owner" in restore.args
    assert "--no-privileges" in restore.args
    assert restore.args[-2:] == ["-d", "postgresql://postgres@postgres.railway.internal:5432/railway"]


def test_the_dump_is_a_custom_format_read_of_production(spawned):
    dump, _ = spawned

    assert dump.args == [
        "pg_dump",
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "postgresql://preview_clone@switchback.proxy.rlwy.net:28233/railway?sslmode=require",
    ]


def test_each_side_gets_its_own_password_out_of_band(spawned):
    """Neither credential is on an argv anybody can read with `ps`, and the target's is not the
    source's - the restore writes to this preview's Postgres, not to production's."""
    dump, restore = spawned

    assert dump.env["PGPASSWORD"] == "s3cret-token"
    assert restore.env["PGPASSWORD"] == "localpw"
    assert "s3cret-token" not in " ".join(dump.args)
    assert "localpw" not in " ".join(restore.args)


def test_the_dump_is_piped_into_the_restore_rather_than_staged(spawned):
    """A preview container has no promise of disk for the whole application database."""
    dump, restore = spawned

    assert restore.stdin is dump.stdout
    # Closed in the parent once the child owns it, or an early pg_restore exit would hang pg_dump.
    assert dump.stdout.closed is True


# --- the sanitize pass ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _FakeSession:
    """Records the statement rather than running it: what matters is which rows it names."""

    def __init__(self, rowcount=3):
        self.statements = []
        self._rowcount = rowcount

    def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult(self._rowcount)


def _bound_values(statement) -> set:
    compiled = statement.compile(dialect=postgresql.dialect())
    values = set()
    for value in compiled.params.values():
        if isinstance(value, (list, tuple)):
            values.update(value)
        else:
            values.add(value)
    return values


def test_a_queued_gp_write_is_cancelled_in_the_copy():
    """The load-bearing test of this module. Production's outbox row describes a GP write production
    is still going to make; the preview holds the SAME relay credential, so left alone its worker
    would post a second receipt or a second PO into real GP."""
    session = _FakeSession(rowcount=3)

    assert preview_clone.sanitize_cloned_data(session) == 3

    statement = session.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE gp_write_outbox SET")
    values = _bound_values(statement)
    assert {"PENDING", "IN_FLIGHT"} <= values
    assert "CANCELLED" in values
    assert preview_clone.OUTBOX_CANCEL_REASON in values


def test_the_terminal_statuses_are_left_alone():
    """FAILED and CANCELLED rows drain for nobody - both need an admin to press Retry. Since Retry
    accepts a CANCELLED row just as readily as a FAILED one, rewriting FAILED here would protect
    nothing while making the preview's queue page disagree with production's."""
    assert preview_clone.NON_TERMINAL_OUTBOX_STATUSES == ("PENDING", "IN_FLIGHT")
    assert "FAILED" not in preview_clone.NON_TERMINAL_OUTBOX_STATUSES


def test_the_cancel_reason_says_where_the_row_came_from():
    """Somebody reading the preview's GP queue has to be able to tell a row that was cancelled here
    from one a person cancelled."""
    assert preview_clone.OUTBOX_CANCEL_REASON == "cancelled by preview clone: queued on production"


# --- the CLI's exit codes ------------------------------------------------------------------------


@pytest.fixture
def never_clones(monkeypatch):
    """Fails the test if the clone is actually attempted."""

    def _boom(*args, **kwargs):
        raise AssertionError("the clone must not run on this path")

    monkeypatch.setattr(preview_clone, "clone_production_into_this_database", _boom)


def test_it_refuses_outside_a_preview_environment(monkeypatch, capsys, never_clones):
    """The clone drops production's data on top of whatever database it is pointed at. Run against
    production itself it would be a self-restore; run against a developer's it would be a download of
    the company's live data. The environment name is the only thing preventing either."""
    monkeypatch.setattr(preview_clone, "is_preview_environment", lambda: False)

    assert preview_clone.main([]) == preview_clone.EXIT_NOT_A_PREVIEW
    assert "not a Railway preview environment" in capsys.readouterr().err


def test_no_source_configured_warns_and_boots_empty(monkeypatch, caplog, never_clones):
    """Exit 2, distinct from the failure code: an environment with nothing to clone from is where
    every preview stood before this existed, and it must not fail the deploy."""
    monkeypatch.setattr(preview_clone, "is_preview_environment", lambda: True)
    monkeypatch.setattr(preview_clone, "preview_clone_source_url", lambda: None)

    with caplog.at_level(logging.WARNING, logger=preview_clone.__name__):
        assert preview_clone.main([]) == preview_clone.EXIT_NO_SOURCE

    assert "booting empty" in caplog.records[-1].getMessage()


def test_a_failed_clone_exits_one_with_the_reason(monkeypatch, capsys):
    """entrypoint.sh turns this into a failed deploy. A preview that quietly booted empty would look
    healthy and be worth nothing to test against."""
    monkeypatch.setattr(preview_clone, "is_preview_environment", lambda: True)
    monkeypatch.setattr(preview_clone, "preview_clone_source_url", lambda: "postgresql://x@y/z")

    def _fail(_source):
        raise preview_clone.CloneError("pg_dump of production failed (exit 1): connection refused")

    monkeypatch.setattr(preview_clone, "clone_production_into_this_database", _fail)

    assert preview_clone.main([]) == preview_clone.EXIT_FAILED
    assert "connection refused" in capsys.readouterr().err


def test_a_successful_clone_exits_zero_and_logs_what_landed(monkeypatch, caplog):
    monkeypatch.setattr(preview_clone, "is_preview_environment", lambda: True)
    monkeypatch.setattr(preview_clone, "preview_clone_source_url", lambda: "postgresql://x@y/z")
    result = preview_clone.CloneResult(
        source_revision="104_gp_company_discovery",
        table_counts={"projects": 12, "hardware_items": 900, "notifications": 0},
        outbox_cancelled=2,
    )
    monkeypatch.setattr(preview_clone, "clone_production_into_this_database", lambda _s: result)

    with caplog.at_level(logging.INFO, logger=preview_clone.__name__):
        assert preview_clone.main([]) == preview_clone.EXIT_OK

    logged = "\n".join(r.getMessage() for r in caplog.records)
    # The source revision is what makes a branch behind production diagnosable from the deploy log.
    assert "104_gp_company_discovery" in logged
    assert "hardware_items" in logged
    assert result.total_rows == 912


# --- the branch-behind-production message ---------------------------------------------------------


def test_the_migration_gap_message_names_the_revision_and_the_fix():
    """ "Can't locate revision" on its own reads like a corrupt database, which sends people looking in
    the wrong place. The copy is fine; the branch is old."""
    assert preview_clone.migration_gap_message("104_gp_company_discovery") == (
        "production's schema is at 104_gp_company_discovery and this branch does not have it: "
        "merge master into the branch"
    )


def test_the_migration_gap_message_survives_an_unreadable_revision():
    assert "unknown" in preview_clone.migration_gap_message(None)
