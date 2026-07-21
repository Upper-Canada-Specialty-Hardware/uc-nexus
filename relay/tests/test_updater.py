"""Updater: release discovery over the public GitHub API, the current-vs-latest comparison, and the
download + rename-swap that applies an update. No network (urlopen/urlretrieve mocked), no real exe."""

import json
import logging
import os
from pathlib import Path

from ucnexus_relay import setup, updater

_LOG = logging.getLogger("relay-test-update")  # throwaway; the helper only writes to it


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_current_build_falls_back_to_dev():
    # a dev checkout has no _build.py (CI stamps it); the fallback keeps the updater always "behind"
    assert updater.current_build() == "dev"


def test_latest_release_picks_highest_build_not_list_order(monkeypatch):
    # regression: GitHub's /releases list is NOT reliably newest-first - the real API returned
    # build.9, build.8, build.7, build.10 in that order. Picking the first entry gives build.9 and
    # would offer a DOWNGRADE to anyone on build.10. Pick by build number, not position.
    payload = [
        {"tag_name": "some-other-v1", "assets": []},
        {
            "tag_name": "relay-v0.1.0-build.9",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build9.exe"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.8",
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build8.exe"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.10",  # newest, but appears AFTER the older ones in the list
            "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "https://x/build10.exe"}],
            "published_at": "t10",
        },
    ]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    r = updater.latest_release()
    assert r["tag"] == "relay-v0.1.0-build.10"
    assert r["url"].endswith("build10.exe")


def test_latest_release_returns_empty_when_no_relay_release(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp([{"tag_name": "some-other-v1", "assets": []}]))
    assert updater.latest_release() == {}


def test_latest_release_skips_releases_without_the_exe_asset(monkeypatch):
    payload = [{"tag_name": "relay-v0.1.0-build.9", "assets": [{"name": "notes.txt", "browser_download_url": "u"}]}]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert updater.latest_release() == {}


def test_check_update_reports_available(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.7")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "https://x/e.exe"})
    r = updater.check_update()
    assert r["ok"] is True
    assert r["update_available"] is True
    assert r["latest"] == "relay-v0.1.0-build.9"
    assert r["url"].endswith("e.exe")


def test_check_update_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.9")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "u"})
    assert updater.check_update()["update_available"] is False


def test_check_update_never_offers_a_downgrade(monkeypatch):
    # installed build is NEWER than what discovery returns (e.g. GitHub API lag) -> must NOT offer to
    # "update" to the older build.
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.10")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "u"})
    assert updater.check_update()["update_available"] is False


def test_check_update_from_dev_offers_any_release(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "dev")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.1", "url": "u"})
    assert updater.check_update()["update_available"] is True


def test_check_update_no_release(monkeypatch):
    monkeypatch.setattr(updater, "latest_release", lambda: {})
    assert updater.check_update()["ok"] is False


def test_apply_update_swaps_and_restarts(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD-EXE")

    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    stopped, started = {}, {}

    def _stop(d):
        stopped["d"] = d
        return {"ok": True}

    def _start(e, d):
        started["exe"] = e
        return {"ok": True}

    monkeypatch.setattr(setup, "stop_serve", _stop)
    monkeypatch.setattr(setup, "start_serve", _start)

    r = updater.apply_update("https://x/e.exe", tmp_path)
    assert r["ok"] is True
    assert exe.read_bytes()[:1] == b"N"  # exe now holds the new bytes
    assert not (tmp_path / "ucnexus-relay.exe.old").exists()  # cleaned up after a successful swap
    assert not (tmp_path / "ucnexus-relay.exe.new").exists()  # moved into place
    assert started["exe"] == exe  # serve restarted from the new exe
    assert stopped["d"] == tmp_path


def test_apply_update_restarts_serve_even_when_the_swap_fails(tmp_path, monkeypatch):
    # regression: a failed swap must NOT leave the relay stopped (it took GP down once).
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    started = []
    monkeypatch.setattr(setup, "stop_serve", lambda d: {"ok": True})
    monkeypatch.setattr(setup, "start_serve", lambda e, d: started.append(e) or {"ok": True})

    def _raise(a, b):
        raise OSError("locked")

    monkeypatch.setattr(updater.os, "replace", _raise)
    r = updater.apply_update("u", tmp_path)
    assert r["ok"] is False
    assert "swap failed" in r["error"]
    assert started == [exe]  # serve was restarted on the current version despite the failure


def test_apply_update_rejects_a_tiny_download(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))
    monkeypatch.setattr(setup, "stop_serve", lambda d: {"ok": True})

    r = updater.apply_update("u", tmp_path)
    assert r["ok"] is False
    assert "too small" in r["error"]
    assert exe.read_bytes() == b"OLD"  # left untouched on a bad download


def test_stage_update_downloads_seeds_ledger_and_spawns_the_helper(tmp_path, monkeypatch):
    # NO batch file anymore: staging downloads the exe, seeds the attempt ledger, and spawns the
    # windowless `ucnexus-relay update-apply` helper (never `cmd /c a .bat`, never a taskkill /im).
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    calls = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, cwd: calls.append((args, cwd)))
    exe = tmp_path / "ucnexus-relay.exe"

    r = updater.stage_update("u", tmp_path, 4242, target_build="relay-v0.1.0-build.11")
    assert r["ok"] is True
    assert not (tmp_path / "update-helper.bat").exists()  # the .bat is gone
    assert (tmp_path / "ucnexus-relay.exe.new").exists()  # downloaded, not yet swapped

    ledger = updater.read_ledger(tmp_path)
    assert ledger["status"] == "staging"
    assert ledger["target_build"] == "relay-v0.1.0-build.11"
    assert ledger["attempts"] == 0

    assert len(calls) == 1
    args, _ = calls[0]
    assert args == [str(exe), "update-apply", "--pid", "4242"]  # windowless helper, waits for the app pid


def test_stage_update_rejects_a_tiny_download_and_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))

    def _no_spawn(*a, **k):
        raise AssertionError("must not spawn the helper on a bad download")

    monkeypatch.setattr(updater, "_spawn_detached", _no_spawn)
    r = updater.stage_update("u", tmp_path, 1)
    assert r["ok"] is False
    assert "too small" in r["error"]


def test_stage_update_keeps_attempts_for_the_same_target_but_resets_for_a_new_one(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"N" * 6_000_000))
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, cwd: None)
    # a prior FAILED attempt at build.11 (attempts already 2)
    updater._write_ledger(tmp_path, {"status": "failed", "target_build": "relay-v0.1.0-build.11", "attempts": 2})

    updater.stage_update("u", tmp_path, 1, target_build="relay-v0.1.0-build.11")
    assert updater.read_ledger(tmp_path)["attempts"] == 2  # same still-unfinished target -> keep the count

    updater.stage_update("u", tmp_path, 1, target_build="relay-v0.1.0-build.12")
    assert updater.read_ledger(tmp_path)["attempts"] == 0  # a new target -> fresh count


# --- apply_staged_update: the detached helper state machine -------------------------------------------


def _seed_stage(install_dir, *, build="relay-v0.1.0-build.11", attempts=0, new_bytes=b"NEW-EXE"):
    (install_dir / "ucnexus-relay.exe").write_bytes(b"OLD-EXE")
    if new_bytes is not None:
        (install_dir / "ucnexus-relay.exe.new").write_bytes(new_bytes)
    updater._write_ledger(install_dir, {"status": "staging", "target_build": build, "attempts": attempts})


def _patch_helper_side_effects(monkeypatch, *, relaunches):
    """Stub the process-touching steps so the orchestration is testable off-Windows and without real
    processes. Records every relaunch target."""
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, deadline, log: None)
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: None)
    monkeypatch.setattr(updater, "_relaunch", lambda exe, log: relaunches.append(Path(exe)))


def test_apply_staged_update_swaps_and_relaunches_once(tmp_path, monkeypatch):
    _seed_stage(tmp_path)
    relaunches = []
    _patch_helper_side_effects(monkeypatch, relaunches=relaunches)  # real swap runs (os.replace on tmp files)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is True
    exe = tmp_path / "ucnexus-relay.exe"
    assert exe.read_bytes() == b"NEW-EXE"  # new bytes swapped in
    assert not (tmp_path / "ucnexus-relay.exe.new").exists()  # consumed
    assert not list(tmp_path.glob("ucnexus-relay.exe.old*"))  # cleaned up
    assert relaunches == [exe]  # exactly ONE relaunch, of the new exe
    assert updater.read_ledger(tmp_path)["status"] == "success"


def test_apply_staged_update_relaunches_current_exe_when_the_swap_fails(tmp_path, monkeypatch):
    _seed_stage(tmp_path)
    relaunches = []
    _patch_helper_side_effects(monkeypatch, relaunches=relaunches)
    monkeypatch.setattr(updater, "_swap_new_over_exe", lambda exe, new, d, deadline, log: (False, "locked"))

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    exe = tmp_path / "ucnexus-relay.exe"
    assert exe.read_bytes() == b"OLD-EXE"  # left on the current version, never down
    assert relaunches == [exe]  # relaunched exactly once (the current exe)
    assert not (tmp_path / "ucnexus-relay.exe.new").exists()  # bad staging cleared
    led = updater.read_ledger(tmp_path)
    assert led["status"] == "failed" and led["last_error"] == "locked"


def test_apply_staged_update_circuit_breaker_gives_up_after_max_attempts(tmp_path, monkeypatch):
    _seed_stage(tmp_path, attempts=updater.MAX_ATTEMPTS)  # next run is attempt MAX+1
    relaunches = []
    _patch_helper_side_effects(monkeypatch, relaunches=relaunches)

    def _must_not_swap(*a, **k):
        raise AssertionError("circuit breaker must trip before attempting a swap")

    monkeypatch.setattr(updater, "_swap_new_over_exe", _must_not_swap)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    assert "gave up" in r["error"]
    assert relaunches == [tmp_path / "ucnexus-relay.exe"]  # relaunch current, then STOP (no loop)
    assert updater.read_ledger(tmp_path)["status"] == "failed"


def test_apply_staged_update_honors_the_cancel_flag_and_does_not_relaunch(tmp_path, monkeypatch):
    _seed_stage(tmp_path)
    relaunches = []
    _patch_helper_side_effects(monkeypatch, relaunches=relaunches)
    updater.request_cancel(tmp_path)  # user closed the relay mid-update

    r = updater.apply_staged_update(4242, tmp_path)

    assert r.get("cancelled") is True
    assert relaunches == []  # a deliberate close is respected: nothing is resurrected
    assert updater.read_ledger(tmp_path)["status"] == "cancelled"
    assert not (tmp_path / updater._CANCEL_FLAG).exists()  # flag cleared


def test_apply_staged_update_fails_cleanly_when_the_new_file_is_missing(tmp_path, monkeypatch):
    _seed_stage(tmp_path, new_bytes=None)  # .new never downloaded
    relaunches = []
    _patch_helper_side_effects(monkeypatch, relaunches=relaunches)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    assert relaunches == [tmp_path / "ucnexus-relay.exe"]  # relaunch current so the relay stays up
    assert updater.read_ledger(tmp_path)["status"] == "failed"


def test_kill_relay_pids_uses_pid_not_image_name(tmp_path, monkeypatch):
    (tmp_path / "relay.pid").write_text("9001", encoding="utf-8")
    killed = []
    from ucnexus_relay import single_instance

    monkeypatch.setattr(single_instance, "force_kill_pid", lambda pid: killed.append(int(pid)))

    updater._kill_relay_pids(4242, tmp_path, _LOG)

    assert killed == [4242, 9001]  # app pid + serve pid, both by pid (never taskkill /im)


# --- _swap_new_over_exe: bounded retry with rollback --------------------------------------------------


def test_swap_retries_then_succeeds(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    new = tmp_path / "ucnexus-relay.exe.new"
    new.write_bytes(b"NEWBYTES")
    real = os.replace
    calls = {"move_new": 0}

    def flaky(src, dst):
        if str(src) == str(new):  # the move-new-in step: fail twice, then let it through
            calls["move_new"] += 1
            if calls["move_new"] <= 2:
                raise OSError("handle still held")
        return real(src, dst)

    monkeypatch.setattr(updater.os, "replace", flaky)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)
    monkeypatch.setattr(updater, "_monotonic", lambda: 0.0)  # far from the deadline

    ok, err = updater._swap_new_over_exe(exe, new, tmp_path, deadline=100.0, log=_LOG)

    assert ok is True and err is None
    assert exe.read_bytes() == b"NEWBYTES"
    assert calls["move_new"] == 3  # two failures, then success


def test_swap_gives_up_at_the_deadline_and_leaves_the_exe_in_place(tmp_path, monkeypatch):
    exe = tmp_path / "ucnexus-relay.exe"
    exe.write_bytes(b"OLD")
    new = tmp_path / "ucnexus-relay.exe.new"
    new.write_bytes(b"NEWBYTES")
    real = os.replace

    def always_fail_move(src, dst):
        if str(src) == str(new):
            raise OSError("locked forever")
        return real(src, dst)  # rename-aside + rollback still work

    monkeypatch.setattr(updater.os, "replace", always_fail_move)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)
    clock = {"t": 0.0}

    def tick():
        clock["t"] += 5.0
        return clock["t"]

    monkeypatch.setattr(updater, "_monotonic", tick)

    ok, err = updater._swap_new_over_exe(exe, new, tmp_path, deadline=10.0, log=_LOG)

    assert ok is False
    assert "move-new-in failed" in err
    assert exe.read_bytes() == b"OLD"  # rolled back: the relay still has its exe
