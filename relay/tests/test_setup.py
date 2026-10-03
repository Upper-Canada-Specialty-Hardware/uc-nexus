"""Setup-wizard backend: config generation/writing, the read-only GP connection probe, and serve
stop-by-pid. Plus the ui.Api wizard-method guards. No real SQL, no window, no registry writes."""

import subprocess
import tomllib

import pytest

from ucnexus_relay import setup, ui


class _Cur:
    """Answers both reads test_gp_connection does: the identity row through fetchone, the company
    master through fetchall."""

    def __init__(self, row, companies):
        self._row, self._companies = row, companies

    def execute(self, *a):
        return self

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._companies


class _Conn:
    def __init__(self, row, companies=()):
        self._row, self._companies = row, list(companies)

    def cursor(self):
        return _Cur(self._row, self._companies)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _identity(login, db, dyngrp):
    return type("_Row", (), {"login": login, "db": db, "dyngrp": dyngrp})()


def _company(code, name):
    return type("_Company", (), {"id": code, "name": name})()


def test_build_config_toml_is_the_secret_and_nothing_else():
    data = tomllib.loads(setup.build_config_toml({}))
    assert data["auth"]["shared_secret"]  # placeholder present so enroll can replace it
    # infra is baked in config.py and the companies come from GP, so neither is written to config.toml:
    assert "gp" not in data
    assert "sql" not in data
    assert "channel" not in data
    assert "cors" not in data


def test_write_config_writes_a_parseable_file(tmp_path):
    p = tmp_path / "config.toml"
    r = setup.write_config({"sql_server": "s", "backend_url": "wss://h/relay-link"}, p)
    assert r["ok"] is True
    assert p.exists()
    tomllib.loads(p.read_text(encoding="utf-8"))  # parses


def test_write_config_preserves_an_already_enrolled_secret(tmp_path):
    p = tmp_path / "config.toml"
    setup.write_config({"shared_secret": "enc:dpapi:REAL"}, p)
    # re-running setup without a secret must NOT wipe the enrolled one
    setup.write_config({}, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["auth"]["shared_secret"] == "enc:dpapi:REAL"


def test_write_config_refuses_an_unparseable_file_instead_of_overwriting_it(tmp_path):
    # #1385: treated as empty, a broken file was rewritten with the placeholder, wiping the enrolled secret.
    p = tmp_path / "config.toml"
    broken = '[auth]\nshared_secret = "enc:dpapi:REAL"\n[channel\n'
    p.write_text(broken, encoding="utf-8")

    r = setup.write_config({}, p)

    assert r["ok"] is False and "not valid TOML" in r["error"] and "fix or remove" in r["error"]
    assert p.read_text(encoding="utf-8") == broken  # untouched: the secret survives


def test_write_config_leaves_no_temp_file_behind(tmp_path):
    # #1386: written beside the target and replaced over it, so a crash never leaves half a config.
    p = tmp_path / "config.toml"
    setup.write_config({"shared_secret": "enc:dpapi:REAL"}, p)
    assert [f.name for f in tmp_path.iterdir()] == ["config.toml"]


def test_atomic_write_keeps_the_old_file_when_the_replace_fails(tmp_path, monkeypatch):
    from ucnexus_relay import fsutil

    p = tmp_path / "config.toml"
    p.write_text("old", encoding="utf-8")

    def _boom(src, dst):
        raise OSError("power cut")

    monkeypatch.setattr(fsutil.os, "replace", _boom)
    with pytest.raises(OSError):
        fsutil.atomic_write_text(p, "new")
    assert p.read_text(encoding="utf-8") == "old"
    assert [f.name for f in tmp_path.iterdir()] == ["config.toml"]  # the temp file is cleaned up


def test_test_gp_connection_uses_baked_sql_when_file_has_none(tmp_path, monkeypatch):
    import pyodbc

    p = tmp_path / "config.toml"
    p.write_text('[gp]\nmode = "sql"\n', encoding="utf-8")  # no [sql] - baked defaults apply
    captured = {}
    row = _identity("x", "DYNAMICS", 0)

    def _connect(conn_str, **k):
        captured["conn_str"] = conn_str
        return _Conn(row)

    monkeypatch.setattr(pyodbc, "connect", _connect)
    r = setup.test_gp_connection(p)
    assert r["ok"] is True
    assert "10.0.0.246,1435" in captured["conn_str"]  # the baked SQL server was used
    assert "DATABASE=DYNAMICS" in captured["conn_str"]  # probed against the GP system database


def test_test_gp_connection_success(tmp_path, monkeypatch):
    import pyodbc

    p = tmp_path / "config.toml"
    p.write_text('[sql]\nserver = "10.0.0.246,1435"\n', encoding="utf-8")

    row = _identity("UPPERCANADA\\jayp", "DYNAMICS", 1)
    companies = [_company("TUBC", "Test Upper Canada"), _company("UBC", "Upper Canada")]

    monkeypatch.setattr(pyodbc, "connect", lambda *a, **k: _Conn(row, companies))
    r = setup.test_gp_connection(p)
    assert r["ok"] is True
    assert r["connected_as"].endswith("jayp")
    assert r["database"] == "DYNAMICS"
    assert r["is_member_dyngrp"] is True
    # the wizard is where an operator finds out which companies this workstation will serve
    assert r["companies"] == [{"id": "TUBC", "name": "Test Upper Canada"}, {"id": "UBC", "name": "Upper Canada"}]
    assert r["companies_error"] is None


def test_stop_serve_no_pid_file(tmp_path):
    assert setup.stop_serve(tmp_path)["ok"] is False


def test_stop_serve_kills_the_pid(tmp_path, monkeypatch):
    (tmp_path / "relay.pid").write_text("12345", encoding="utf-8")
    calls = {}

    def _run(args, **kwargs):
        calls["args"] = args

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()

    monkeypatch.setattr(subprocess, "run", _run)
    r = setup.stop_serve(tmp_path)
    assert r["ok"] is True
    assert r["pid"] == 12345
    assert "12345" in calls["args"]


# --- ui.Api wizard-method guards ---------------------------------------------------------------------


def test_api_install_autostart_refuses_in_dev(monkeypatch):
    monkeypatch.setattr(ui, "_frozen", lambda: False)
    r = ui.Api().install_autostart()
    assert r["ok"] is False
    assert "packaged exe" in r["error"]


def test_api_start_relay_reports_already_running(monkeypatch):
    monkeypatch.setattr(ui, "relay_health", lambda host="127.0.0.1", port=7321: {"running": True})
    assert ui.Api().start_relay() == {"ok": True, "already_running": True}


def test_api_enroll_requires_token():
    r = ui.Api().enroll("")
    assert r["ok"] is False


def test_write_config_preserves_a_hand_added_extra_backend_url(tmp_path):
    # #414: extra_backend_urls exists nowhere but config.toml, and the wizard never asks for it. A
    # re-run that dropped it would silently disconnect a PR environment mid-test.
    p = tmp_path / "config.toml"
    p.write_text(
        '[auth]\nshared_secret = "s3cret"\n'
        '\n[channel]\nextra_backend_urls = ["wss://backend-pr-414.up.railway.app/relay-link"]\n',
        encoding="utf-8",
    )
    setup.write_config({}, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["channel"]["extra_backend_urls"] == ["wss://backend-pr-414.up.railway.app/relay-link"]
    assert data["auth"]["shared_secret"] == "s3cret"  # still preserved alongside it


def test_build_config_toml_renders_extra_backend_urls_as_a_toml_array(tmp_path):
    data = tomllib.loads(setup.build_config_toml({"extra_backend_urls": ["wss://a/relay-link"]}))
    assert data["channel"]["extra_backend_urls"] == ["wss://a/relay-link"]


def test_build_config_toml_accepts_a_bare_string_extra_url(tmp_path):
    data = tomllib.loads(setup.build_config_toml({"extra_backend_urls": "wss://a/relay-link"}))
    assert data["channel"]["extra_backend_urls"] == ["wss://a/relay-link"]
