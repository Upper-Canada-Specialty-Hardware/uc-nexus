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


def test_api_apply_update_stages_then_shuts_down_in_app_mode(monkeypatch):
    from ucnexus_relay import updater

    a = appmod.RelayApp()
    shut = []
    monkeypatch.setattr(a, "shutdown", lambda: shut.append(True))
    monkeypatch.setattr(appmod, "_APP", a)
    monkeypatch.setattr(ui, "_frozen", lambda: True)
    monkeypatch.setattr(updater, "stage_update", lambda url, d, pid: {"ok": True, "note": "restarting"})
    r = ui.Api().apply_update("https://x/e.exe")
    assert r["ok"] is True
    assert shut == [True]  # the app shut itself down so the helper can swap the unlocked exe


def test_api_apply_update_does_not_shut_down_on_a_failed_stage(monkeypatch):
    from ucnexus_relay import updater

    a = appmod.RelayApp()
    shut = []
    monkeypatch.setattr(a, "shutdown", lambda: shut.append(True))
    monkeypatch.setattr(appmod, "_APP", a)
    monkeypatch.setattr(ui, "_frozen", lambda: True)
    monkeypatch.setattr(updater, "stage_update", lambda url, d, pid: {"ok": False, "error": "download failed"})
    r = ui.Api().apply_update("https://x/e.exe")
    assert r["ok"] is False
    assert shut == []  # a failed stage must NOT close the app


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


def test_maybe_promote_skips_when_launched_from_install_dir(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "same_path", lambda x, y: True)
    monkeypatch.setattr(si, "installed_build", lambda d: BUILD5)
    monkeypatch.setattr(si, "current_build", lambda: BUILD5)
    assert a._maybe_promote(force=False) is False


def test_maybe_promote_delegates_when_installed_is_current(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "same_path", lambda x, y: False)
    monkeypatch.setattr(si, "installed_build", lambda d: BUILD6)
    monkeypatch.setattr(si, "current_build", lambda: BUILD5)  # we're older -> delegate to installed
    monkeypatch.setattr(si, "live_owner", lambda d: None)
    launched = []
    monkeypatch.setattr(si, "launch_installed", lambda d, **k: launched.append(True))
    assert a._maybe_promote(force=False) is True
    assert launched == [True]


def test_maybe_promote_swaps_and_relaunches_when_newer(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "same_path", lambda x, y: False)
    monkeypatch.setattr(si, "installed_build", lambda d: BUILD5)
    monkeypatch.setattr(si, "current_build", lambda: BUILD6)  # newer -> promote
    monkeypatch.setattr(si, "live_owner", lambda d: None)
    swapped = []
    monkeypatch.setattr(si, "promote_swap", lambda src, d: swapped.append(src) or {"ok": True})
    monkeypatch.setattr(si, "refresh_autostart_if_present", lambda d: None)
    launched = []
    monkeypatch.setattr(si, "launch_installed", lambda d, **k: launched.append(True))
    assert a._maybe_promote(force=False) is True
    assert swapped and launched == [True]


def test_maybe_promote_runs_in_place_when_swap_fails(monkeypatch):
    a = appmod.RelayApp()
    monkeypatch.setattr(si, "same_path", lambda x, y: False)
    monkeypatch.setattr(si, "installed_build", lambda d: BUILD5)
    monkeypatch.setattr(si, "current_build", lambda: BUILD6)
    monkeypatch.setattr(si, "live_owner", lambda d: None)
    monkeypatch.setattr(si, "promote_swap", lambda src, d: {"ok": False, "error": "locked"})
    launched = []
    monkeypatch.setattr(si, "launch_installed", lambda d, **k: launched.append(True))
    assert a._maybe_promote(force=False) is False  # fall back to running in place
    assert launched == []
