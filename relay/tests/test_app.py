"""Tray-app supervision logic (no window, no tray, no GUI backend). The pywebview/pystray run() path is
verified from the frozen exe; here we cover the serve supervision, the shutdown sequence, the X-close
decision, and the Api methods that reach the app."""

import threading

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


def test_api_apply_update_stages_then_shuts_down_in_app_mode(monkeypatch):
    import os

    from ucnexus_relay import updater

    a = appmod.RelayApp()
    shut = []
    monkeypatch.setattr(a, "shutdown", lambda: shut.append(True))
    monkeypatch.setattr(appmod, "_APP", a)
    monkeypatch.setattr(ui, "_frozen", lambda: True)
    # The staging sequence now lives in RelayApp.begin_update (the update poller runs the same one),
    # so the frozen guard is checked there too.
    monkeypatch.setattr(appmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(os, "_exit", lambda code: None)  # neutralize the hard-exit fallback timer
    passed = {}
    monkeypatch.setattr(
        updater, "stage_update", lambda url, d, pid, target_build=None: passed.update(build=target_build) or {"ok": True}
    )
    r = ui.Api().apply_update("https://x/e.exe", "relay-v0.1.0-build.11")
    assert r["ok"] is True
    assert shut == [True]  # the app shut itself down so the helper can swap the unlocked exe
    assert a._updating is True  # marked as the update handoff, so a later teardown isn't a user cancel
    assert passed["build"] == "relay-v0.1.0-build.11"  # target build threaded through to the ledger


def test_api_apply_update_does_not_shut_down_on_a_failed_stage(monkeypatch):
    from ucnexus_relay import updater

    a = appmod.RelayApp()
    shut = []
    monkeypatch.setattr(a, "shutdown", lambda: shut.append(True))
    monkeypatch.setattr(appmod, "_APP", a)
    monkeypatch.setattr(ui, "_frozen", lambda: True)
    monkeypatch.setattr(appmod.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        updater, "stage_update", lambda url, d, pid, target_build=None: {"ok": False, "error": "download failed"}
    )
    r = ui.Api().apply_update("https://x/e.exe")
    assert r["ok"] is False
    assert shut == []  # a failed stage must NOT close the app
    assert a._updating is False  # not marked updating, so a later user shutdown still cancels normally


def test_begin_update_refuses_outside_a_frozen_build(monkeypatch):
    # A dev checkout has no exe to swap; the poller and the UI both reach this guard.
    a = appmod.RelayApp()
    monkeypatch.setattr(appmod.sys, "frozen", False, raising=False)
    r = a.begin_update("https://x/e.exe", "relay-v0.1.0-build.11")
    assert r["ok"] is False
    assert "packaged exe" in r["error"]


def test_stop_relay_and_tray_stops_the_update_poller_first(monkeypatch):
    # Ordering matters: a poll that began staging during teardown would hand this process off to the
    # apply helper while it is already on its way down.
    a = appmod.RelayApp()
    order = []
    stop = threading.Event()
    monkeypatch.setattr(stop, "set", lambda: order.append("poller"))
    a._update_poller_stop = stop
    monkeypatch.setattr(setup, "stop_serve", lambda d: order.append("serve"))
    monkeypatch.setattr(a, "_release_single_instance", lambda: None)
    a._stop_relay_and_tray()
    assert order == ["poller", "serve"]


def test_user_shutdown_cancels_a_pending_update(monkeypatch, tmp_path):
    from ucnexus_relay import updater

    a = appmod.RelayApp()
    monkeypatch.setattr(a, "_install_dir", lambda: tmp_path)
    monkeypatch.setattr(a, "shutdown", lambda: None)
    updater._write_ledger(tmp_path, {"status": "applying", "target_build": "b", "attempts": 1})
    a.user_shutdown()
    assert (tmp_path / updater._CANCEL_FLAG).exists()  # user closing mid-update signals the helper to abort


def test_update_handoff_shutdown_does_not_cancel_itself(monkeypatch, tmp_path):
    from ucnexus_relay import updater

    a = appmod.RelayApp()
    a._updating = True  # this teardown IS the update handoff
    monkeypatch.setattr(a, "_install_dir", lambda: tmp_path)
    updater._write_ledger(tmp_path, {"status": "applying", "target_build": "b", "attempts": 1})
    a._cancel_update_if_pending()
    assert not (tmp_path / updater._CANCEL_FLAG).exists()  # must not cancel the update it just started


# --- single-instance gate ----------------------------------------------------------------------------

from ucnexus_relay import single_instance as si  # noqa: E402

BUILD5 = "relay-v0.1.0-build.5"
BUILD6 = "relay-v0.1.0-build.6"


def _fake_control(store):
    class _Ctl:
        def __init__(self, **kw):
            store["kw"] = kw

        def start(self):
            return 5555

    return _Ctl


def test_acquire_focuses_a_running_same_build(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "current_build", lambda: BUILD5)
    monkeypatch.setattr(si, "live_owner", lambda d: {"port": 1, "nonce": "n", "build": BUILD5, "pid": 123})
    sent = []
    monkeypatch.setattr(si, "allow_foreground", lambda pid: sent.append(("af", pid)))
    monkeypatch.setattr(si, "send_show", lambda p, n: sent.append(("show", p, n)) or True)
    assert a._acquire_single_instance(force=False) is False  # bowed out to the running instance
    assert ("af", 123) in sent and ("show", 1, "n") in sent
    assert a._control is None


def test_acquire_becomes_owner_when_none_running(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "current_build", lambda: BUILD5)
    monkeypatch.setattr(si, "live_owner", lambda d: None)
    monkeypatch.setattr(si, "acquire_mutex", lambda: si.MutexResult(None, True))
    store = {}
    monkeypatch.setattr(si, "ControlServer", _fake_control(store))
    monkeypatch.setattr(si, "new_nonce", lambda: "nonce")
    locks = []
    monkeypatch.setattr(si, "write_lock", lambda d, **kw: locks.append(kw))
    assert a._acquire_single_instance(force=False) is True
    assert locks[0]["control_port"] == 5555 and locks[0]["nonce"] == "nonce" and locks[0]["build"] == BUILD5
    assert a._control is not None and a._mutex is not None


def test_acquire_evicts_an_older_owner_then_takes_over(monkeypatch):
    a = appmod.RelayApp()
    owner = {"port": 1, "nonce": "n", "build": BUILD5, "pid": 123}
    monkeypatch.setattr(si, "current_build", lambda: BUILD6)
    monkeypatch.setattr(si, "live_owner", lambda d: owner)
    evicted = []
    monkeypatch.setattr(si, "evict", lambda o, d: evicted.append(o) or True)
    monkeypatch.setattr(si, "acquire_mutex", lambda: si.MutexResult(None, True))
    monkeypatch.setattr(si, "ControlServer", _fake_control({}))
    monkeypatch.setattr(si, "new_nonce", lambda: "nonce")
    monkeypatch.setattr(si, "write_lock", lambda d, **kw: None)
    assert a._acquire_single_instance(force=False) is True
    assert evicted == [owner]


def test_acquire_defers_when_it_loses_the_cold_start_race(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "current_build", lambda: BUILD5)
    monkeypatch.setattr(si, "live_owner", lambda d: None)
    monkeypatch.setattr(si, "acquire_mutex", lambda: si.MutexResult(None, False))  # someone created it first
    monkeypatch.setattr(si, "wait_for_owner", lambda d: {"port": 9, "nonce": "z", "build": BUILD5, "pid": 7})
    sent = []
    monkeypatch.setattr(si, "allow_foreground", lambda pid: sent.append(pid))
    monkeypatch.setattr(si, "send_show", lambda p, n: sent.append((p, n)) or True)
    monkeypatch.setattr(si, "release_mutex", lambda m: None)
    assert a._acquire_single_instance(force=False) is False
    assert 7 in sent and (9, "z") in sent


def test_cleanup_old_versions_keeps_running_drops_others(monkeypatch, tmp_path):
    from ucnexus_relay import layout

    a = appmod.RelayApp()
    monkeypatch.setattr(a, "_install_dir", lambda: tmp_path)
    for name in ("app-relay-v0.1.0-build.26", "app-relay-v0.1.0-build.27", "app-old"):
        (tmp_path / name).mkdir()
    running = tmp_path / "app-relay-v0.1.0-build.27"
    monkeypatch.setattr(layout, "running_version_dir", lambda: running)

    a._cleanup_old_versions()

    remaining = sorted(p.name for p in tmp_path.glob("app-*"))
    assert remaining == ["app-relay-v0.1.0-build.27"]  # kept the running version, dropped the rest
