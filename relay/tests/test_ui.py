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
[channel]
backend_url = "wss://host/relay-link"
[logging]
file = "relay.log"
""",
    )
    s = ui.config_summary(p)
    assert s["present"] is True
    assert s["enrolled"] is True
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


def test_tail_lines_reads_a_bounded_tail_of_a_large_log(tmp_path):
    # the UI polls the log every few seconds; a large file must be tailed from the END, not read whole,
    # and must still return the last `limit` COMPLETE (parseable) lines in order.
    log = tmp_path / "relay.log"
    events = [json.dumps({"asctime": f"t{i}", "levelname": "INFO", "message": "x" * 60, "i": i}) for i in range(5000)]
    log.write_text("\n".join(events) + "\n", encoding="utf-8")
    tail = ui._tail_lines(log, 20)
    assert len(tail) == 20
    parsed = [json.loads(t) for t in tail]  # every returned line is complete, not truncated by the offset read
    assert [row["i"] for row in parsed] == list(range(4980, 5000))  # the LAST 20 events, in order


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


def test_channel_state_clean_close_reads_as_disconnected(tmp_path):
    # issue #384: a socket that closed without raising is tagged closed_clean. An unrecognised category
    # walks further back in the log and finds the 'channel connected' that OPENED the socket which just
    # closed, so the panel would report a dead channel as connected.
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(
        tmp_path,
        {"asctime": "t1", "levelname": "INFO", "message": "channel connected"},
        {
            "asctime": "t2",
            "levelname": "WARNING",
            "message": "channel closed without an error; reconnecting",
            "category": "closed_clean",
        },
    )
    assert ui.channel_state(p)["state"] == "disconnected"


def test_channel_state_unknown_without_log(tmp_path):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    assert ui.channel_state(p)["state"] == "unknown"


def test_relay_health_down_on_closed_port():
    assert ui.relay_health("127.0.0.1", 1)["running"] is False


def test_gather_status_shape(tmp_path, monkeypatch):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(tmp_path, {"asctime": "t1", "levelname": "INFO", "message": "channel connected"})
    monkeypatch.setattr(ui, "relay_health", lambda host="127.0.0.1", port=7321: {"running": True, "version": "0.1.0"})
    monkeypatch.setattr(ui.autostart, "autostart_status", lambda: {"installed": True, "command": "x"})
    s = ui.gather_status(p)
    assert set(s) == {"ui_version", "build", "config", "relay", "channel", "autostart"}
    assert s["channel"]["state"] == "connected"
    assert s["relay"]["running"] is True
    assert s["config"]["sql_server"]


def test_relay_health_carries_the_discovered_companies(monkeypatch):
    # The Status tab's Companies row: only the serve process knows these (it reads them from GP), so
    # they ride out on /health rather than being read from config.toml the way the old list was.
    import json as _json
    from io import BytesIO

    body = _json.dumps(
        {
            "status": "ok",
            "companies": [{"id": "TUBC", "name": "Test Upper Canada"}],
            "companies_error": None,
        }
    ).encode()

    class _Resp:
        def __enter__(self):
            return BytesIO(body)

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ui.urllib.request, "urlopen", lambda url, timeout=3: _Resp())
    health = ui.relay_health()
    assert health["companies"] == [{"id": "TUBC", "name": "Test Upper Canada"}]
    assert health["companies_error"] is None


def test_api_delegates(monkeypatch):
    monkeypatch.setattr(ui, "gather_status", lambda: {"ok": 1})
    monkeypatch.setattr(ui, "recent_log_events", lambda limit=200: [{"n": limit}])
    api = ui.Api()
    assert api.get_status() == {"ok": 1}
    assert api.get_logs(50) == [{"n": 50}]


def test_config_summary_shows_baked_infra_when_file_omits_it(tmp_path):
    # config.toml now carries only [auth]; SQL server + backend must come from the baked defaults.
    p = _cfg(tmp_path, '[auth]\nshared_secret = "x"\n')
    s = ui.config_summary(p)
    assert s["sql_server"]
    assert s["backend_url"].startswith("wss://")


def test_enroll_url_derived_from_baked_backend():
    url = ui._enroll_url_from_channel()
    assert url.startswith("https://")
    assert url.endswith("/graphql")


def test_gather_status_channel_disconnected_when_serve_down(tmp_path, monkeypatch):
    # a killed serve can't have a live channel, no matter what the log's last line says
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(tmp_path, {"asctime": "t1", "levelname": "INFO", "message": "channel connected"})
    monkeypatch.setattr(ui, "relay_health", lambda host="127.0.0.1", port=7321: {"running": False})
    monkeypatch.setattr(ui.autostart, "autostart_status", lambda: {"installed": True})
    assert ui.gather_status(p)["channel"]["state"] == "disconnected"


def test_gather_status_uses_live_channel_from_health(tmp_path, monkeypatch):
    p = _cfg(tmp_path, '[logging]\nfile = "relay.log"\n')
    _log(tmp_path, {"asctime": "t1", "levelname": "INFO", "message": "channel connected"})  # stale "connected"
    monkeypatch.setattr(
        ui, "relay_health", lambda host="127.0.0.1", port=7321: {"running": True, "channel": {"connected": False, "state": "secret_rejected"}}
    )
    monkeypatch.setattr(ui.autostart, "autostart_status", lambda: {"installed": True})
    # the live /health channel wins over the stale log line
    assert ui.gather_status(p)["channel"]["state"] == "secret_rejected"
