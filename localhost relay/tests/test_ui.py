"""UI status-gathering (the pywebview window's data layer). Pure functions over a temp config.toml +
relay.log - no window, no network, no registry (those are monkeypatched)."""

import json

from ucnexus_relay import ui


def _cfg(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body, encoding="utf-8")
    return p


def _log(tmp_path, *events: dict):
    (tmp_path / "relay.log").write_text(
        "".join(json.dumps(e) + "\n" for e in events), encoding="utf-8"
    )


def test_config_summary_absent(tmp_path):
    p = tmp_path / "nope.toml"
    assert ui.config_summary(p) == {"present": False, "path": str(p)}


def test_config_summary_parses_fields_without_leaking_secret(tmp_path):
    p = _cfg(
        tmp_path,
        """
[server]
host = "127.0.0.1"
port = 7321
[auth]
shared_secret = "enc:dpapi:AQAAsecret"
[sql]
server = "10.0.0.246,1435"
driver = "ODBC Driver 17 for SQL Server"
[gp]
default_company = "TUBC"
allowed_companies = ["TUBC", "TUCSH"]
[channel]
backend_url = "wss://host/relay-link"
[logging]
file = "relay.log"
""",
    )
    s = ui.config_summary(p)
    assert s["present"] is True
    assert s["enrolled"] is True
    assert s["default_company"] == "TUBC"
    assert s["allowed_companies"] == ["TUBC", "TUCSH"]
    assert s["sql_server"] == "10.0.0.246,1435"
    assert s["backend_url"].endswith("/relay-link")
    assert "AQAAsecret" not in json.dumps(s)  # the secret VALUE must never appear


def test_config_summary_not_enrolled_when_secret_blank(tmp_path):
    assert ui.config_summary(_cfg(tmp_path, '[auth]\nshared_secret = ""\n'))["enrolled"] is False


def test_config_summary_parse_error(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("definitely = not [[[ valid toml", encoding="utf-8")
    s = ui.config_summary(p)
    assert s["present"] is True
    assert "parse_error" in s


def test_recent_log_events_parses_json_and_raw(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(
        tmp_path,
        {"asctime": "t1", "levelname": "INFO", "message": "channel connected"},
        {"asctime": "t2", "levelname": "WARNING", "message": "drop", "category": "secret_rejected"},
    )
    with open(tmp_path / "relay.log", "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    rows = ui.recent_log_events(p, limit=10)
    assert len(rows) == 3
    assert rows[0]["message"] == "channel connected"
    assert rows[1]["category"] == "secret_rejected"
    assert rows[2]["level"] == "RAW"


def test_recent_log_events_limit(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(tmp_path, *[{"asctime": f"t{i}", "levelname": "INFO", "message": str(i)} for i in range(50)])
    assert len(ui.recent_log_events(p, limit=10)) == 10


def test_channel_state_connected_wins_over_earlier_drop(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(
        tmp_path,
        {"asctime": "t1", "levelname": "WARNING", "message": "channel connection dropped, retrying", "category": "dropped"},
        {"asctime": "t2", "levelname": "INFO", "message": "channel connected"},
    )
    assert ui.channel_state(p)["state"] == "connected"


def test_channel_state_secret_rejected(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(tmp_path, {"asctime": "t2", "levelname": "WARNING", "message": "backend rejected the relay secret", "category": "secret_rejected"})
    assert ui.channel_state(p)["state"] == "secret_rejected"


def test_channel_state_unknown_without_log(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    assert ui.channel_state(p)["state"] == "unknown"


def test_relay_health_down_on_closed_port():
    assert ui.relay_health("127.0.0.1", 1)["running"] is False


def test_gather_status_shape(tmp_path, monkeypatch):
    p = _cfg(tmp_path, '[gp]\ndefault_company = "TUBC"\nallowed_companies = ["TUBC"]\n[logging]\nfile = "relay.log"\n')
    _log(tmp_path, {"asctime": "t1", "levelname": "INFO", "message": "channel connected"})
    monkeypatch.setattr(ui, "relay_health", lambda host="127.0.0.1", port=7321: {"running": True, "version": "0.1.0"})
    monkeypatch.setattr(ui.autostart, "autostart_status", lambda: {"installed": True, "command": "x"})
    s = ui.gather_status(p)
    assert set(s) == {"ui_version", "build", "config", "relay", "channel", "autostart"}
    assert s["channel"]["state"] == "connected"
    assert s["relay"]["running"] is True
    assert s["config"]["default_company"] == "TUBC"


def test_api_delegates(monkeypatch):
    monkeypatch.setattr(ui, "gather_status", lambda: {"ok": 1})
    monkeypatch.setattr(ui, "recent_log_events", lambda limit=200: [{"n": limit}])
    api = ui.Api()
    assert api.get_status() == {"ok": 1}
    assert api.get_logs(50) == [{"n": 50}]
