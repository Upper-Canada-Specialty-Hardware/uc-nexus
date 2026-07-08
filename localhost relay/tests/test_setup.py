"""Setup-wizard backend: config generation/writing, the read-only GP connection probe, and serve
stop-by-pid. Plus the ui.Api wizard-method guards. No real SQL, no window, no registry writes."""

import subprocess
import tomllib

from ucnexus_relay import setup, ui


def test_build_config_toml_is_valid_and_carries_fields():
    text = setup.build_config_toml(
        {
            "sql_server": "10.0.0.246,1435",
            "default_company": "TUBC",
            "allowed_companies": ["TUBC", "TUCSH"],
            "buyer_default": "mira",
            "backend_url": "wss://host/relay-link",
            "custom_db": {"UBC": "PMUBC"},
        }
    )
    data = tomllib.loads(text)
    assert data["sql"]["server"] == "10.0.0.246,1435"
    assert data["gp"]["default_company"] == "TUBC"
    assert data["gp"]["allowed_companies"] == ["TUBC", "TUCSH"]
    assert data["gp"]["custom_db"]["UBC"] == "PMUBC"
    assert data["gp"]["buyers"]["default"] == "mira"
    assert data["channel"]["backend_url"].endswith("/relay-link")
    assert data["auth"]["shared_secret"]  # a placeholder is always present so enroll can replace it


def test_build_config_toml_omits_optional_sections_when_absent():
    data = tomllib.loads(setup.build_config_toml({"sql_server": "s", "backend_url": ""}))
    assert "custom_db" not in data["gp"]
    assert "buyers" not in data["gp"]


def test_write_config_writes_a_parseable_file(tmp_path):
    p = tmp_path / "config.toml"
    r = setup.write_config({"sql_server": "s", "backend_url": "wss://h/relay-link"}, p)
    assert r["ok"] is True
    assert p.exists()
    tomllib.loads(p.read_text(encoding="utf-8"))  # parses


def test_write_config_preserves_an_already_enrolled_secret(tmp_path):
    p = tmp_path / "config.toml"
    setup.write_config({"sql_server": "s", "shared_secret": "enc:dpapi:REAL"}, p)
    # re-running setup without a secret must NOT wipe the enrolled one
    setup.write_config({"sql_server": "s2"}, p)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    assert data["auth"]["shared_secret"] == "enc:dpapi:REAL"
    assert data["sql"]["server"] == "s2"


def test_test_gp_connection_missing_server(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[gp]\ndefault_company = "TUBC"\n', encoding="utf-8")
    r = setup.test_gp_connection(p)
    assert r["ok"] is False
    assert "server" in r["error"]


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


def test_api_enroll_requires_token_and_url():
    r = ui.Api().enroll("", "")
    assert r["ok"] is False
