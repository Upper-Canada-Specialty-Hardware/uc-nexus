"""The background auto-update poller (#353 PR D).

Health + logic only, never GP and never a real download. Every policy decision is a pure function
over dicts precisely so it can be pinned here: the failure modes that matter (re-staging a build that
has already burned its attempt budget, and swapping the exe out from under an in-flight GP write) are
both invisible until they bite somebody at a workstation nobody can reach."""

import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ucnexus_relay import layout, update_poller, updater


def _check(**overrides) -> dict:
    base = {
        "ok": True,
        "current": "relay-v0.1.0-build.40",
        "latest": "relay-v0.1.0-build.41",
        "update_available": True,
        "url": "https://example.invalid/ucnexus-relay.zip",
    }
    base.update(overrides)
    return base


# --- should_stage -------------------------------------------------------------------------------------


def test_stages_when_an_update_is_available_and_the_ledger_is_clean():
    stage, reason = update_poller.should_stage(_check(), {}, cancel_requested=False)
    assert stage is True
    assert "build.41" in reason


def test_does_not_stage_when_the_check_failed():
    stage, _ = update_poller.should_stage({"ok": False, "error": "no network"}, {}, cancel_requested=False)
    assert stage is False


def test_does_not_stage_when_already_current():
    stage, _ = update_poller.should_stage(_check(update_available=False), {}, cancel_requested=False)
    assert stage is False


def test_does_not_stage_without_a_download_url():
    stage, _ = update_poller.should_stage(_check(url=""), {}, cancel_requested=False)
    assert stage is False


def test_does_not_stage_while_a_cancel_is_pending():
    # The user closed the relay mid-update; a poller that re-staged 15 minutes later would overrule them.
    stage, _ = update_poller.should_stage(_check(), {}, cancel_requested=True)
    assert stage is False


def test_does_not_stage_while_an_update_is_already_in_progress():
    for status in ("staging", "applying"):
        stage, _ = update_poller.should_stage(_check(), {"status": status}, cancel_requested=False)
        assert stage is False, status


def test_does_not_restage_a_target_that_exhausted_its_attempts():
    # apply_staged_update refuses past MAX_ATTEMPTS; re-staging on a schedule would burn the budget and
    # leave a relay that can never update again.
    ledger = {
        "status": "failed",
        "target_build": "relay-v0.1.0-build.41",
        "attempts": updater.MAX_ATTEMPTS,
    }
    stage, reason = update_poller.should_stage(_check(), ledger, cancel_requested=False)
    assert stage is False
    assert "failed" in reason


def test_retries_a_target_that_has_attempts_left():
    ledger = {"status": "failed", "target_build": "relay-v0.1.0-build.41", "attempts": 1}
    stage, _ = update_poller.should_stage(_check(), ledger, cancel_requested=False)
    assert stage is True


def test_a_newer_build_escapes_an_exhausted_target():
    # The escape hatch: publish a fix and the relay tries again (_stage_ledger resets attempts).
    ledger = {
        "status": "failed",
        "target_build": "relay-v0.1.0-build.41",
        "attempts": updater.MAX_ATTEMPTS,
    }
    stage, _ = update_poller.should_stage(_check(latest="relay-v0.1.0-build.42"), ledger, cancel_requested=False)
    assert stage is True


# --- is_busy ------------------------------------------------------------------------------------------


def test_busy_while_a_job_is_in_flight():
    assert update_poller.is_busy({"channel": {"jobs_in_flight": 1, "last_job_finished_ago": None}}) is True


def test_busy_inside_the_grace_window_after_the_last_job():
    assert update_poller.is_busy({"channel": {"jobs_in_flight": 0, "last_job_finished_ago": 5}}) is True


def test_not_busy_once_the_grace_window_has_passed():
    assert update_poller.is_busy({"channel": {"jobs_in_flight": 0, "last_job_finished_ago": 200}}) is False


def test_not_busy_when_no_job_has_ever_run():
    assert update_poller.is_busy({"channel": {"jobs_in_flight": 0, "last_job_finished_ago": None}}) is False


def test_unreachable_health_counts_as_busy():
    # Fail-safe: "cannot tell" must never authorise killing a relay that might be mid-eConnect.
    assert update_poller.is_busy({}) is True
    assert update_poller.is_busy({"running": False}) is True


# --- next_delay ---------------------------------------------------------------------------------------


def test_delays_stay_within_their_windows():
    rng = random.Random(7)
    first = update_poller.next_delay(rng, first=True)
    assert update_poller.FIRST_DELAY_SECONDS <= first <= (
        update_poller.FIRST_DELAY_SECONDS + update_poller.FIRST_JITTER_SECONDS
    )
    later = update_poller.next_delay(rng)
    assert update_poller.INTERVAL_SECONDS <= later <= (
        update_poller.INTERVAL_SECONDS + update_poller.INTERVAL_JITTER_SECONDS
    )


# --- run ----------------------------------------------------------------------------------------------


class _FakeApp:
    def __init__(self, tmp_path):
        self._dir = tmp_path
        self.staged: list[tuple] = []

    def _install_dir(self):
        return self._dir

    def begin_update(self, url, build=None):
        self.staged.append((url, build))
        return {"ok": True}

    def restart_serve(self):
        # The self-check must NOT come back through here: this relaunches sys.executable, which on the
        # rollback path is the build being rolled back (see update_poller._restart_serve_from_current).
        raise AssertionError("the rollback must restart serve from the current junction, not sys.executable")


class _NoWait(threading.Event):
    """A stop event that lets the loop run `iterations` times, then stops it. wait() returns False
    (keep going) that many times and True afterwards, so the loop never actually sleeps."""

    def __init__(self, iterations: int):
        super().__init__()
        self._left = iterations

    def wait(self, timeout=None):
        # The timeout is deliberately ignored: the point is to run the loop without real sleeping.
        if self._left <= 0:
            return True
        self._left -= 1
        return False


def test_run_stages_the_release_and_stops(monkeypatch, tmp_path):
    app = _FakeApp(tmp_path)
    monkeypatch.setattr(update_poller, "_read_health", lambda: {"channel": {"jobs_in_flight": 0}})
    monkeypatch.setattr(updater, "check_update", lambda: _check())
    monkeypatch.setattr(updater, "read_ledger", lambda d: {})
    monkeypatch.setattr(updater, "cancel_requested", lambda d: False)

    update_poller.run(app, _NoWait(3))

    # Exactly once: staging hands the process off, so the loop must return rather than stage again.
    assert app.staged == [("https://example.invalid/ucnexus-relay.zip", "relay-v0.1.0-build.41")]


def test_run_defers_while_a_gp_job_is_in_flight(monkeypatch, tmp_path):
    app = _FakeApp(tmp_path)
    monkeypatch.setattr(update_poller, "_read_health", lambda: {"channel": {"jobs_in_flight": 1}})
    monkeypatch.setattr(updater, "check_update", lambda: _check())
    monkeypatch.setattr(updater, "read_ledger", lambda d: {})
    monkeypatch.setattr(updater, "cancel_requested", lambda d: False)

    update_poller.run(app, _NoWait(2))

    assert app.staged == []


def test_run_survives_an_exception_and_keeps_polling(monkeypatch, tmp_path):
    # A GitHub blip must not kill the thread: that would silently end auto-updating with no signal.
    app = _FakeApp(tmp_path)
    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("boom")
        return _check()

    monkeypatch.setattr(update_poller, "_read_health", lambda: {"channel": {"jobs_in_flight": 0}})
    monkeypatch.setattr(updater, "check_update", _flaky)
    monkeypatch.setattr(updater, "read_ledger", lambda d: {})
    monkeypatch.setattr(updater, "cancel_requested", lambda d: False)

    update_poller.run(app, _NoWait(3))

    assert calls["n"] == 2
    assert len(app.staged) == 1


def test_start_does_not_spawn_a_thread_outside_a_frozen_build(monkeypatch, tmp_path):
    spawned = []
    monkeypatch.setattr(threading, "Thread", lambda **kw: spawned.append(kw))
    stop = update_poller.start(_FakeApp(tmp_path))
    assert spawned == []
    assert isinstance(stop, threading.Event)


# --- the stuck-ledger backstop (#369) -----------------------------------------------------------------
# Startup reconciliation normally clears an abandoned ledger, but a relay that stays up for weeks never
# gets that chance, so should_stage has to be able to see past one on its own.


def _applying_ledger(seconds_ago: float) -> dict:
    stamped = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {
        "status": "applying",
        "target_build": "relay-v0.1.0-build.36",
        "attempts": 1,
        "updated_at": stamped.isoformat(timespec="seconds"),
    }


def test_stages_past_a_ledger_no_helper_could_still_be_working_on():
    ledger = _applying_ledger(updater.ABANDONED_AFTER_SECONDS + 60)
    stage, reason = update_poller.should_stage(_check(), ledger, cancel_requested=False)
    assert stage is True
    assert "build.41" in reason


def test_still_refuses_while_a_helper_could_plausibly_be_running():
    ledger = _applying_ledger(30)
    stage, reason = update_poller.should_stage(_check(), ledger, cancel_requested=False)
    assert stage is False
    assert "already in progress" in reason


# --- the post-update self-check -----------------------------------------------------------------------
# The apply helper health-gates its relaunch, but /health answers as soon as uvicorn binds - which says
# nothing about whether the new build can still reach the backend. A build that starts cleanly and never
# connects therefore records `success` and leaves the workstation dark, with nobody on site to notice.


_LANDED = "relay-v0.1.0-build.41"
_PREVIOUS = "relay-v0.1.0-build.40"


def _landed_ledger(tmp_path, **overrides) -> dict:
    led = {
        "status": "success",
        "target_build": _LANDED,
        "target_dir": str(tmp_path / layout.version_dir_name(_LANDED)),
        "attempts": 1,
        "last_error": None,
    }
    led.update(overrides)
    updater._write_ledger(tmp_path, led)
    return led


def _versions(tmp_path, *builds) -> list:
    dirs = []
    for build in builds:
        ver = tmp_path / layout.version_dir_name(build)
        ver.mkdir(parents=True, exist_ok=True)
        (ver / layout.ASSET_NAME).write_bytes(b"EXE")
        dirs.append(ver)
    return dirs


def _health(connected: bool, channels=True) -> dict:
    snapshot = {"connected": connected, "state": "connected" if connected else "disconnected"}
    snapshot["channels"] = [{"url": "wss://backend/relay-link", "primary": True, **snapshot}] if channels else []
    return {"running": True, "channel": snapshot}


def _self_check(monkeypatch, app, *, health, repoints=None, restarts=None, repoint_ok=True, elapsed=(0.0, 10_000.0)):
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)
    monkeypatch.setattr(update_poller, "_read_health", lambda: health)
    monkeypatch.setattr(
        layout,
        "repoint_current",
        lambda d, target: (repoints is not None and repoints.append(target)) or repoint_ok,
    )
    monkeypatch.setattr(
        update_poller, "_restart_serve_from_current", lambda d: restarts is not None and restarts.append(d)
    )
    ticks = iter(elapsed)
    return update_poller.self_check(app, threading.Event(), monotonic=lambda: next(ticks, 10_000.0))


def test_self_check_does_nothing_when_no_update_landed(monkeypatch, tmp_path):
    app = _FakeApp(tmp_path)

    def _no_health():
        raise AssertionError("nothing landed - there is nothing to verify")

    monkeypatch.setattr(update_poller, "_read_health", _no_health)
    assert update_poller.self_check(app, threading.Event()) is None


def test_self_check_does_nothing_for_an_update_to_a_build_that_is_not_running(monkeypatch, tmp_path):
    # The ledger says build.41 landed but this process is build.40 - the rollback already happened, or
    # somebody installed over it by hand.
    _landed_ledger(tmp_path)
    monkeypatch.setattr(updater, "current_build", lambda: _PREVIOUS)
    assert update_poller.self_check(_FakeApp(tmp_path), threading.Event()) is None


def test_self_check_passes_once_the_channel_connects(monkeypatch, tmp_path):
    _landed_ledger(tmp_path)
    _versions(tmp_path, _PREVIOUS, _LANDED)
    app = _FakeApp(tmp_path)
    repoints = []

    restarts = []
    assert _self_check(monkeypatch, app, health=_health(True), repoints=repoints, restarts=restarts) == "connected"
    assert repoints == []  # nothing rolled back
    assert restarts == []
    assert updater.read_ledger(tmp_path)["status"] == "success"


def test_self_check_rolls_back_a_build_whose_channel_never_connects(monkeypatch, tmp_path):
    _landed_ledger(tmp_path)
    previous, landed = _versions(tmp_path, _PREVIOUS, _LANDED)
    monkeypatch.setattr(layout, "current_target", lambda d: landed)
    app = _FakeApp(tmp_path)
    repoints, restarts = [], []

    verdict = _self_check(monkeypatch, app, health=_health(False), repoints=repoints, restarts=restarts)
    assert verdict == "rolled_back"
    assert repoints == [previous]  # the junction goes back to the version before the update
    assert restarts == [tmp_path]  # ...and serve is restarted onto it, or the relay stays down
    led = updater.read_ledger(tmp_path)
    assert led["status"] == "rolled_back"
    assert _LANDED in led["last_error"] and _PREVIOUS in led["last_error"]


def test_a_rolled_back_build_is_not_staged_again():
    # Otherwise the workstation walks through the same install, the same five minutes offline, and the
    # same rollback every day.
    ledger = {"status": "rolled_back", "target_build": "relay-v0.1.0-build.41", "attempts": 1}
    stage, reason = update_poller.should_stage(_check(), ledger, cancel_requested=False)
    assert stage is False
    assert "rolled back" in reason


def test_a_newer_build_escapes_a_rollback():
    ledger = {"status": "rolled_back", "target_build": "relay-v0.1.0-build.41", "attempts": 1}
    stage, _ = update_poller.should_stage(_check(latest="relay-v0.1.0-build.42"), ledger, cancel_requested=False)
    assert stage is True


def test_self_check_leaves_the_build_in_place_when_there_is_nothing_to_roll_back_to(monkeypatch, tmp_path):
    # A broken channel beats no relay at all: with one version on disk there is no bootable fallback.
    _landed_ledger(tmp_path)
    (landed,) = _versions(tmp_path, _LANDED)
    monkeypatch.setattr(layout, "current_target", lambda d: landed)
    app = _FakeApp(tmp_path)
    repoints = []

    restarts = []
    verdict = _self_check(monkeypatch, app, health=_health(False), repoints=repoints, restarts=restarts)
    assert verdict == "no_previous_version"
    assert repoints == []
    assert restarts == []
    assert updater.read_ledger(tmp_path)["status"] == "success"


def test_self_check_does_not_judge_a_relay_that_dials_nothing(monkeypatch, tmp_path):
    # An unenrolled relay runs no channel by design (cli._serve skips it with no secret), so "not
    # connected" is not a verdict on the build and a rollback would fix nothing.
    _landed_ledger(tmp_path)
    _versions(tmp_path, _PREVIOUS, _LANDED)
    repoints = []

    verdict = _self_check(monkeypatch, _FakeApp(tmp_path), health=_health(False, channels=False), repoints=repoints)
    assert verdict == "no_channel"
    assert repoints == []


def test_self_check_runs_once_per_update(monkeypatch, tmp_path):
    # A workstation that boots offline must not re-judge a build that has been fine for a week.
    _landed_ledger(tmp_path)
    _versions(tmp_path, _PREVIOUS, _LANDED)
    app = _FakeApp(tmp_path)

    restarts = []
    assert _self_check(monkeypatch, app, health=_health(True), restarts=restarts) == "connected"
    assert updater.read_ledger(tmp_path)["self_check"] == "connected"
    assert _self_check(monkeypatch, app, health=_health(False), restarts=restarts) is None
    assert restarts == []


def test_the_rollback_restarts_serve_from_the_junction_not_the_running_exe(monkeypatch, tmp_path):
    # sys.executable IS the build being rolled back, so starting serve from it would put the new build
    # straight back on GP and the rollback would not land until the next logon.
    from ucnexus_relay import setup, single_instance

    calls = []
    monkeypatch.setattr(update_poller, "_sleep", lambda s: None)
    monkeypatch.setattr(setup, "stop_serve", lambda d: calls.append(("stop", Path(d))))
    monkeypatch.setattr(setup, "start_serve", lambda exe, d: calls.append(("start", Path(exe))))
    monkeypatch.setattr(single_instance, "installed_exe_path", lambda d: tmp_path / "current" / layout.ASSET_NAME)

    update_poller._restart_serve_from_current(tmp_path)

    assert calls == [("stop", tmp_path), ("start", tmp_path / "current" / layout.ASSET_NAME)]


def test_self_check_never_takes_the_app_down_with_it(monkeypatch, tmp_path):
    _landed_ledger(tmp_path)
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)

    def _boom():
        raise OSError("health socket exploded")

    monkeypatch.setattr(update_poller, "_read_health", _boom)
    assert update_poller.self_check(_FakeApp(tmp_path), threading.Event()) is None
