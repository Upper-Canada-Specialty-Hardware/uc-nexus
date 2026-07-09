"""Tray-app supervision logic (no window, no tray, no GUI backend). The pywebview/pystray run() path is
verified from the frozen exe; here we cover the serve supervision, the shutdown sequence, the X-close
decision, and the Api methods that reach the app."""

from ucnexus_relay import app as appmod
from ucnexus_relay import setup, ui


def test_ensure_serve_noop_when_already_running(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(a, "_serve_running", lambda: True)
    started = []
    monkeypatch.setattr(setup, "start_serve", lambda *args: started.append(args))
    a.ensure_serve()
    assert started == []


def test_restart_serve_stops_then_starts_when_frozen(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(appmod.time, "sleep", lambda s: None)
    monkeypatch.setattr(appmod.sys, "frozen", True, raising=False)
    seq = []
    monkeypatch.setattr(setup, "stop_serve", lambda d: seq.append("stop"))
    monkeypatch.setattr(setup, "start_serve", lambda e, d: seq.append("start"))
    a.restart_serve()
    assert seq == ["stop", "start"]


def test_shutdown_stops_serve_then_tray_then_window_and_is_idempotent(monkeypatch):
    a = appmod.RelayApp()
    order = []
    monkeypatch.setattr(setup, "stop_serve", lambda d: order.append("serve"))

    class _Tray:
        def stop(self):
            order.append("tray")

    class _Win:
        def destroy(self):
            order.append("window")

    a._tray = _Tray()
    a._window = _Win()
    a.shutdown()
    assert order == ["serve", "tray", "window"]
    a.shutdown()  # already shutting down -> no-op
    assert order == ["serve", "tray", "window"]


def test_on_closing_cancels_when_not_confirmed(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(a, "_confirm_shutdown", lambda: False)
    assert a._on_closing() is False


def test_on_closing_proceeds_when_confirmed(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(a, "_confirm_shutdown", lambda: True)
    stopped = []
    monkeypatch.setattr(a, "_stop_relay_and_tray", lambda: stopped.append(True))
    assert a._on_closing() is True
    assert stopped == [True]


def test_api_restart_relay_uses_the_running_app(monkeypatch):
    a = appmod.RelayApp()
    called = []
    monkeypatch.setattr(a, "restart_serve", lambda: called.append(True))
    monkeypatch.setattr(appmod, "_APP", a)
    assert ui.Api().restart_relay() == {"ok": True}
    assert called == [True]


def test_api_shutdown_app_errors_when_not_in_app_mode(monkeypatch):
    monkeypatch.setattr(appmod, "_APP", None)
    r = ui.Api().shutdown_app()
    assert r["ok"] is False
    assert "desktop app" in r["error"]
