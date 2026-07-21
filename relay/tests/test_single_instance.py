"""Single-instance primitives: the version-decision logic, the app.lock plumbing, the loopback control
channel (real sockets, no GUI), and the promote-to-installed swap. No window, no frozen exe."""

import subprocess
import time

from ucnexus_relay import single_instance as si

BUILD5 = "relay-v0.1.0-build.5"
BUILD6 = "relay-v0.1.0-build.6"


# --- version logic ------------------------------------------------------------------------------------


def test_build_is_newer():
    assert si.build_is_newer(BUILD6, BUILD5) is True
    assert si.build_is_newer(BUILD5, BUILD6) is False
    assert si.build_is_newer(BUILD5, BUILD5) is False
    assert si.build_is_newer("dev", BUILD5) is False  # dev is build -1, never newer than a real build


def test_decide_action_matrix():
    assert si.decide_action(BUILD5, BUILD5) == "focus"  # same -> focus
    assert si.decide_action(BUILD6, BUILD5) == "replace"  # newer -> replace
    assert si.decide_action(BUILD5, BUILD6) == "focus"  # older -> focus
    assert si.decide_action("dev", BUILD5) == "focus"  # dev over real -> focus
    assert si.decide_action("dev", BUILD5, force=True) == "replace"  # --force always replaces


# --- lockfile -----------------------------------------------------------------------------------------


def test_lockfile_roundtrip_and_clear(tmp_path):
    assert si.read_lock(tmp_path) is None  # nothing written yet
    si.write_lock(tmp_path, pid=111, build=BUILD5, exe_path="C:/x.exe", control_port=5555, nonce="abc")
    lock = si.read_lock(tmp_path)
    assert lock == {"pid": 111, "build": BUILD5, "exe_path": "C:/x.exe", "control_port": 5555, "nonce": "abc"}
    si.clear_lock(tmp_path)
    assert si.read_lock(tmp_path) is None
    si.clear_lock(tmp_path)  # idempotent - no error when already gone


def test_read_lock_tolerates_corrupt(tmp_path):
    si.lockfile_path(tmp_path).write_text("{ not json", encoding="utf-8")
    assert si.read_lock(tmp_path) is None


# --- loopback control channel -------------------------------------------------------------------------


def _wait(pred, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def test_control_server_ping_show_quit_and_nonce(tmp_path):
    events = {"show": 0, "quit": 0}
    server = si.ControlServer(
        build=BUILD5,
        nonce="secret",
        on_show=lambda: events.__setitem__("show", events["show"] + 1),
        on_quit=lambda: events.__setitem__("quit", events["quit"] + 1),
    )
    port = server.start()
    try:
        pong = si._send(port, "secret", "ping")
        assert pong["ok"] is True and pong["build"] == BUILD5 and pong["pid"] > 0

        assert si._send(port, "WRONG", "ping") == {"ok": False, "error": "bad nonce"}

        assert si.send_show(port, "secret") is True
        assert _wait(lambda: events["show"] == 1)

        assert si.send_quit(port, "secret") is True
        assert _wait(lambda: events["quit"] == 1)
    finally:
        server.stop()


def test_live_owner_and_wait_for_release(tmp_path):
    server = si.ControlServer(build=BUILD5, nonce="n", on_show=lambda: None, on_quit=lambda: None)
    port = server.start()
    si.write_lock(tmp_path, pid=222, build=BUILD5, exe_path="x", control_port=port, nonce="n")
    try:
        owner = si.live_owner(tmp_path)
        assert owner is not None and owner["build"] == BUILD5 and owner["port"] == port
        assert si.wait_for_release(tmp_path, timeout=0.5) is False  # still live
    finally:
        server.stop()
    assert _wait(lambda: si.live_owner(tmp_path) is None)  # ping fails once the socket is closed
    assert si.wait_for_release(tmp_path, timeout=1.0) is True


def test_live_owner_none_without_lock(tmp_path):
    assert si.live_owner(tmp_path) is None


# --- evict --------------------------------------------------------------------------------------------


def test_evict_graceful(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(si, "send_quit", lambda p, n: calls.append("quit") or True)
    monkeypatch.setattr(si, "wait_for_release", lambda d, **k: True)
    killed = []
    monkeypatch.setattr(si, "force_kill_pid", lambda pid: killed.append(pid))
    assert si.evict({"port": 1, "nonce": "n", "pid": 9}, tmp_path) is True
    assert calls == ["quit"] and killed == []  # graceful quit released it; no force-kill


def test_evict_force_kills_when_graceful_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "send_quit", lambda p, n: True)
    releases = iter([False, True])  # first wait times out, second (after kill) succeeds
    monkeypatch.setattr(si, "wait_for_release", lambda d, **k: next(releases))
    killed = []
    monkeypatch.setattr(si, "force_kill_pid", lambda pid: killed.append(pid))
    assert si.evict({"port": 1, "nonce": "n", "pid": 9}, tmp_path) is True
    assert killed == [9]


# --- installed-exe resolution -------------------------------------------------------------------------


def test_installed_build_reads_print_build(monkeypatch, tmp_path):
    si.installed_exe_path(tmp_path).write_text("exe", encoding="utf-8")

    class _R:
        stdout = BUILD6 + "\n"

    monkeypatch.setattr(si.subprocess, "run", lambda *a, **k: _R())
    assert si.installed_build(tmp_path) == BUILD6


def test_installed_build_none_when_missing(tmp_path):
    assert si.installed_build(tmp_path) is None  # no installed exe


def test_installed_build_none_on_subprocess_error(monkeypatch, tmp_path):
    si.installed_exe_path(tmp_path).write_text("exe", encoding="utf-8")

    def _boom(*a, **k):
        raise subprocess.SubprocessError("nope")

    monkeypatch.setattr(si.subprocess, "run", _boom)
    assert si.installed_build(tmp_path) is None


def test_acquire_mutex_non_windows(monkeypatch):
    monkeypatch.setattr(si.sys, "platform", "linux")
    r = si.acquire_mutex()
    assert r.acquired is True and r.handle is None
    si.release_mutex(r)  # no-op, no error
