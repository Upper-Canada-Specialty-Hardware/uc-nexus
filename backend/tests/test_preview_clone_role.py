"""Production minting the read-only login previews clone through (app/services/preview_clone_role.py).

Two things are worth holding still. It must be inert everywhere but production - a preview running
this would try to create a role on its own throwaway cluster, and a local checkout would log a warning
about a feature nobody asked for. And the DDL text must be right, because role statements cannot take
bind parameters: the password never appears in one at all, only the SCRAM verifier computed from it.

No cluster is touched here. Every test asserts on the statements the module would run.
"""

import logging

import pytest

from app import config
from app.services import preview_clone_role

PASSWORD = "preview-clone-password"


@pytest.fixture
def on_production(monkeypatch):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", PASSWORD)


# --- when it runs at all -------------------------------------------------------------------------


def test_production_with_a_password_is_the_only_case_that_runs(on_production):
    assert preview_clone_role.enabled() is True


@pytest.mark.parametrize("environment", ["uc-nexus-pr-42", "", "staging"])
def test_it_is_a_no_op_off_production(monkeypatch, environment):
    """A preview inherits PREVIEW_CLONE_PASSWORD - that is the point of putting it on production - so
    the environment check is what stops every preview from also minting a role on its own cluster."""
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", environment)
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", PASSWORD)

    assert preview_clone_role.enabled() is False


@pytest.mark.parametrize("password", ["", "   "])
def test_it_is_a_no_op_without_a_password(monkeypatch, password):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setattr(config, "PREVIEW_CLONE_PASSWORD", password)

    assert preview_clone_role.enabled() is False


def test_the_startup_hook_stays_silent_when_disabled(monkeypatch, caplog):
    """Local dev and CI import main every test run. A disabled feature must not narrate itself."""
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "")
    monkeypatch.setattr(preview_clone_role, "ensure_role", lambda: pytest.fail("must not run"))

    with caplog.at_level(logging.DEBUG, logger=preview_clone_role.__name__):
        preview_clone_role.ensure_role_on_startup()

    assert caplog.records == []


def test_a_failing_cluster_never_blocks_startup(monkeypatch, caplog, on_production):
    """What is lost is that previews cannot clone. That is a degraded preview, not a degraded
    production, and it must not stop the app from serving."""

    def _boom():
        raise RuntimeError("permission denied for role postgres")

    monkeypatch.setattr(preview_clone_role, "ensure_role", _boom)

    with caplog.at_level(logging.WARNING, logger=preview_clone_role.__name__):
        preview_clone_role.ensure_role_on_startup()  # must not raise

    assert "permission denied" in caplog.records[-1].getMessage()


# --- the DDL -------------------------------------------------------------------------------------


def _verifier() -> str:
    from app.repositories.db_access_repository import _scram_sha256_verifier

    return _scram_sha256_verifier(PASSWORD)


def test_a_missing_role_is_created_with_login_and_the_read_grant():
    statements = preview_clone_role._statements("preview_clone", _verifier(), exists=False)

    assert len(statements) == 2
    assert statements[0].startswith('CREATE ROLE "preview_clone" LOGIN PASSWORD \'SCRAM-SHA-256$')
    assert statements[1] == 'GRANT pg_read_all_data TO "preview_clone"'


def test_an_existing_role_is_altered_rather_than_recreated():
    """Startup runs on every deploy, so the create path would be a duplicate-role error on the second
    one - and a rotated password has to land on the role that already holds the grant."""
    statements = preview_clone_role._statements("preview_clone", _verifier(), exists=True)

    assert statements[0].startswith('ALTER ROLE "preview_clone" WITH LOGIN PASSWORD \'SCRAM-SHA-256$')
    # Re-granted either way: a GRANT already held is a no-op, and it repairs a hand-revoked role.
    assert statements[1] == 'GRANT pg_read_all_data TO "preview_clone"'


def test_the_password_itself_never_reaches_a_statement():
    """CREATE ROLE cannot take a bind parameter, and a plaintext literal would be disclosed by
    log_min_error_statement if the statement failed. What is interpolated is the verifier, which
    authenticates nobody."""
    for exists in (True, False):
        statements = preview_clone_role._statements("preview_clone", _verifier(), exists=exists)
        assert PASSWORD not in " ".join(statements)


def test_the_grant_is_read_only():
    """pg_read_all_data is the whole of what pg_dump needs. Nothing here hands out write, DDL or
    superuser on production's cluster."""
    assert preview_clone_role._READ_ALL_ROLE == "pg_read_all_data"
    joined = " ".join(preview_clone_role._statements("preview_clone", _verifier(), exists=False))
    assert "SUPERUSER" not in joined
    assert "CREATEDB" not in joined
    assert "CREATEROLE" not in joined


def test_an_invalid_role_name_is_refused_before_it_is_interpolated():
    """The name is the one thing interpolated into DDL besides the verifier, so it goes through the
    same regex-then-quote path db_access_repository uses."""
    from app.errors import ValidationError

    with pytest.raises(ValidationError):
        preview_clone_role._statements('evil"; DROP DATABASE railway; --', _verifier(), exists=False)
