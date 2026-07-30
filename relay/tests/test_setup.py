"""Setup-wizard backend: config generation/writing, the read-only GP connection probe, and serve
stop-by-pid. Plus the ui.Api wizard-method guards. No real SQL, no window, no registry writes."""

import subprocess
import tomllib

from ucnexus_relay import setup, ui


def test_build_config_toml_is_minimal_company_plus_secret():
    data = tomllib.loads(setup.build_config_toml({"default_company": "TUBC", "allowed_companies": ["TUBC", "TUCSH"]}))
    assert data["gp"]["default_company"] == "TUBC"
    assert data["gp"]["allowed_companies"] == ["TUBC", "TUCSH"]
    assert data["auth"]["shared_secret"]  # placeholder present so enroll can replace it
    # infra is baked in config.py, never written to config.toml:
    assert "sql" not in data
    assert "channel" not in data
    assert "cors" not in data


def test_build_config_toml_allowed_falls_back_to_the_default_company():
    data = tomllib.loads(setup.build_config_toml({"default_company": "TUCSH"}))
    assert data["gp"]["allowed_companies"] == ["TUCSH"]


def test_write_config_writes_a_parseable_file(tmp_path):
    p = tmp_path / "config.toml"
    r = setup.write_config({"sql_server": "s", "backend_url": "wss://h/relay-link"}, p)
    assert r["ok"] is True
    assert p.exists()
    tomllib.loads(p.read_text(encoding="utf-8"))  # parses


def test_write_config_preserves_an_already_enrolled_secret(tmp_path):
    p = tmp_path / "config.toml"
    setup.write_config({"default_company": "TUBC", "shared_secret": "enc:dpapi:REAL"}, p)
    # re-running setup without a secret must NOT wipe the enrolled one
    setup.write_config({"default_company": "TUCSH"}, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["auth"]["shared_secret"] == "enc:dpapi:REAL"
    assert data["gp"]["default_company"] == "TUCSH"


def test_test_gp_connection_uses_baked_sql_when_file_has_none(tmp_path, monkeypatch):
    import pyodbc

    p = tmp_path / "config.toml"
    p.write_text('[gp]\ndefault_company = "TUBC"\n', encoding="utf-8")  # no [sql] - baked defaults apply
    captured = {}

    class _Row:
        login = "x"
        db = "TUBC"
        dyngrp = 0

    class _Cur:
        def execute(self, *a):
            return self

        def fetchone(self):
            return _Row()

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _connect(conn_str, **k):
        captured["conn_str"] = conn_str
        return _Conn()

    monkeypatch.setattr(pyodbc, "connect", _connect)
    r = setup.test_gp_connection(p)
    assert r["ok"] is True
    assert "10.0.0.246,1435" in captured["conn_str"]  # the baked SQL server was used


def test_test_gp_connection_success(tmp_path, monkeypatch):
    import pyodbc

    p = tmp_path / "config.toml"
    p.write_text('[sql]\nserver = "10.0.0.246,1435"\n[gp]\ndefault_company = "TUBC"\n', encoding="utf-8")

    class _Row:
        login = "UPPERCANADA\\jayp"
        db = "TUBC"
        dyngrp = 1

    class _Cur:
        def execute(self, *a):
            return self

        def fetchone(self):
            return _Row()

    class _Conn:
        def cursor(self):
            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(pyodbc, "connect", lambda *a, **k: _Conn())
    r = setup.test_gp_connection(p)
    assert r["ok"] is True
    assert r["connected_as"].endswith("jayp")
    assert r["database"] == "TUBC"
    assert r["is_member_dyngrp"] is True


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
        '[auth]\nshared_secret = "s3cret"\n\n[gp]\ndefault_company = "TUBC"\n'
        '\n[channel]\nextra_backend_urls = ["wss://backend-pr-414.up.railway.app/relay-link"]\n',
        encoding="utf-8",
    )
    setup.write_config({"default_company": "TUCSH", "allowed_companies": ["TUCSH"]}, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["channel"]["extra_backend_urls"] == ["wss://backend-pr-414.up.railway.app/relay-link"]
    assert data["auth"]["shared_secret"] == "s3cret"  # still preserved alongside it
    assert data["gp"]["default_company"] == "TUCSH"  # and the wizard's own change applied


def test_build_config_toml_renders_extra_backend_urls_as_a_toml_array(tmp_path):
    data = tomllib.loads(setup.build_config_toml({"extra_backend_urls": ["wss://a/relay-link"]}))
    assert data["channel"]["extra_backend_urls"] == ["wss://a/relay-link"]


def test_build_config_toml_accepts_a_bare_string_extra_url(tmp_path):
    data = tomllib.loads(setup.build_config_toml({"extra_backend_urls": "wss://a/relay-link"}))
    assert data["channel"]["extra_backend_urls"] == ["wss://a/relay-link"]
