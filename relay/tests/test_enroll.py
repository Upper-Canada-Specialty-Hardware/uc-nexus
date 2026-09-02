"""Enrollment config-rewrite (the non-network part). The backend call is stubbed; a real enrollment is
exercised manually during setup."""

import tomllib

import pytest

from ucnexus_relay import enroll
from ucnexus_relay.enroll import write_secret_to_config


def _enrolled_ok(monkeypatch):
    """Stub the one-time-token exchange, so what is under test is what lands on disk."""
    monkeypatch.setattr(
        enroll,
        "_post_graphql",
        lambda url, query, variables: {"data": {"enrollRelayInstall": {"ok": True, "installId": "install-1"}}},
    )


def test_write_secret_replaces_shared_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "OLD_VALUE"\n\n[gp]\nmode = "sql"\n', encoding="utf-8")
    write_secret_to_config(cfg, "NEW_SECRET_xyz")
    text = cfg.read_text(encoding="utf-8")
    assert 'shared_secret = "NEW_SECRET_xyz"' in text
    assert "OLD_VALUE" not in text
    assert 'mode = "sql"' in text  # rest of the file preserved


def test_write_secret_errors_when_no_shared_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gp]\nmode = "sql"\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        write_secret_to_config(cfg, "NEW")


def test_enroll_writes_a_config_when_the_workstation_has_none(tmp_path, monkeypatch):
    # The Setup tab has no "save configuration" step any more (there is nothing left to choose - the
    # companies come from GP), so enrolling has to be able to start from an empty machine.
    _enrolled_ok(monkeypatch)
    cfg = tmp_path / "UCNexusRelay" / "config.toml"

    result = enroll.enroll_relay(
        token="one-time", backend_url="https://backend/graphql", config_path=cfg, encrypt=False
    )

    assert result["ok"] is True
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    secret = data["auth"]["shared_secret"]
    assert secret and secret != "REPLACE_ME_RANDOM_TOKEN"  # the real minted secret replaced the placeholder


def test_enroll_still_refuses_a_config_that_has_no_secret_line(tmp_path, monkeypatch):
    # An existing file is somebody's own; a missing [auth] shared_secret in it is a mistake to report,
    # not something to paper over by rewriting the file.
    _enrolled_ok(monkeypatch)
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gp]\nmode = "sql"\n', encoding="utf-8")

    with pytest.raises(SystemExit):
        enroll.enroll_relay(token="one-time", backend_url="https://backend/graphql", config_path=cfg, encrypt=False)

    assert cfg.read_text(encoding="utf-8") == '[gp]\nmode = "sql"\n'  # left exactly as it was
