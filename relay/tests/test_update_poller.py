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


def _counters(*, jobs=0, job_ago=None, writes=0, write_ago=None) -> dict:
    return {
        "channel": {
            "jobs_in_flight": jobs,
            "last_job_finished_ago": job_ago,
            "writes_in_flight": writes,
            "last_write_finished_ago": write_ago,
        }
    }


def test_reads_finishing_all_day_do_not_keep_the_relay_busy():
    # #1927: the backend's own loops read from the relay every few seconds, so a busy rule that counted
    # them saw a job finish inside the grace window on every check, and a scheduled update never happened.
    assert update_poller.is_busy(_counters(jobs=1, job_ago=3, writes=0, write_ago=None)) is False
    assert update_poller.is_busy(_counters(jobs=0, job_ago=1, writes=0, write_ago=600)) is False


def test_a_write_in_flight_or_just_finished_still_holds_the_update_back():
    assert update_poller.is_busy(_counters(jobs=1, writes=1)) is True
    assert update_poller.is_busy(_counters(jobs=0, job_ago=5, writes=0, write_ago=5)) is True


def test_the_scheduled_handoff_waits_for_a_write_but_not_a_read(monkeypatch):
    monkeypatch.setattr(update_poller, "_read_health", lambda: _counters(jobs=2, job_ago=1))
    assert update_poller.ready_for_scheduled_handoff() is True
    monkeypatch.setattr(update_poller, "_read_health", lambda: _counters(jobs=1, writes=1))
    assert update_poller.ready_for_scheduled_handoff() is False


def test_the_manual_handoff_waits_for_a_write_but_not_a_read(monkeypatch):
    monkeypatch.setattr(update_poller, "_read_health", lambda: _counters(jobs=2))
    assert update_poller.ready_for_manual_handoff() is True
    monkeypatch.setattr(update_poller, "_read_health", lambda: _counters(jobs=1, writes=1))
    assert update_poller.ready_for_manual_handoff() is False


def test_every_op_is_either_a_read_or_a_listed_write():
    # The op audit WRITE_OPS points at: a write left off the list would be swapped out from under.
    from ucnexus_relay import channel

    reads = ("list_", "get_", "read_", "sync_")
    for op in channel._OPS:
        if op in channel.WRITE_OPS:
            continue
        assert op.startswith(reads) or op in ("job_setup_health", "server_load"), (
            f"{op} is not in channel.WRITE_OPS; if it writes to GP add it, if it reads add it here"
        )
    assert channel.WRITE_OPS <= set(channel._OPS)
    assert not channel.WRITE_OPS & channel.BACKGROUND_OPS


def test_unreachable_health_counts_as_busy():
    # Fail-safe: "cannot tell" must never authorise killing a relay that might be mid-eConnect.
    assert update_poller.is_busy({}) is True
    assert update_poller.is_busy({"running": False}) is True


# --- next_delay ---------------------------------------------------------------------------------------


def test_delays_stay_within_their_windows():
    rng = random.Random(7)
    first = update_poller.next_delay(rng, first=True)
    assert (
        update_poller.FIRST_DELAY_SECONDS
        <= first
        <= (update_poller.FIRST_DELAY_SECONDS + update_poller.FIRST_JITTER_SECONDS)
    )
    later = update_poller.next_delay(rng)
    assert (
        update_poller.INTERVAL_SECONDS
        <= later
        <= (update_poller.INTERVAL_SECONDS + update_poller.INTERVAL_JITTER_SECONDS)
    )


# --- run ----------------------------------------------------------------------------------------------


class _FakeApp:
    def __init__(self, tmp_path):
        self._dir = tmp_path
        self.staged: list[tuple] = []

    def _install_dir(self):
        return self._dir

    def begin_update(self, url, build=None, ready_to_hand_off=None):
        self.ready = ready_to_hand_off
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


def test_run_hands_off_under_the_fail_safe_busy_rule(monkeypatch, tmp_path):
    # #1212: the scheduled path keeps the fail-safe rule, so an unanswered /health holds the handoff back.
    app = _FakeApp(tmp_path)
    monkeypatch.setattr(update_poller, "_read_health", lambda: {"channel": {"jobs_in_flight": 0}})
    monkeypatch.setattr(updater, "check_update", lambda: _check())
    monkeypatch.setattr(updater, "read_ledger", lambda d: {})
    monkeypatch.setattr(updater, "cancel_requested", lambda d: False)

    update_poller.run(app, _NoWait(3))

    assert app.ready is update_poller.ready_for_scheduled_handoff
    monkeypatch.setattr(update_poller, "_read_health", lambda: {})
    assert update_poller.ready_for_scheduled_handoff() is False


def test_manual_handoff_refuses_only_a_job_known_to_be_running(monkeypatch):
    for health, ready in (
        ({}, True),  # not answering: a person may be updating precisely to fix that
        ({"channel": {"jobs_in_flight": 0, "last_job_finished_ago": 5}}, True),
        ({"channel": {"jobs_in_flight": 2}}, False),
    ):
        monkeypatch.setattr(update_poller, "_read_health", lambda h=health: h)
        assert update_poller.ready_for_manual_handoff() is ready


def test_run_keeps_polling_when_the_handoff_was_deferred_as_busy(monkeypatch, tmp_path):
    # #1212: became busy while staging - nothing was handed off, so the loop must not return (that would
    # end auto-updating) and the next try comes on the short busy cadence.
    app = _FakeApp(tmp_path)
    app.begin_update = lambda url, build=None, ready_to_hand_off=None: (
        app.staged.append((url, build)) or {"ok": False, "deferred": True}
    )
    monkeypatch.setattr(update_poller, "_read_health", lambda: {"channel": {"jobs_in_flight": 0}})
    monkeypatch.setattr(updater, "check_update", lambda: _check())
    monkeypatch.setattr(updater, "read_ledger", lambda d: {})
    monkeypatch.setattr(updater, "cancel_requested", lambda d: False)
    waits = []

    class _Recording(_NoWait):
        def wait(self, timeout=None):
            waits.append(timeout)
            return super().wait(timeout)

    update_poller.run(app, _Recording(2))

    assert len(app.staged) == 2  # tried again rather than stopping
    assert waits[1] == update_poller.DEFER_RETRY_SECONDS


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


class _HelperFinishes(threading.Event):
    """A stop event standing in for the apply helper: the self-check's first wait is when the helper,
    having seen this app's /health answer, writes its result to the ledger."""

    def __init__(self, tmp_path, status="success"):
        super().__init__()
        self._tmp_path, self._status, self.waits = tmp_path, status, 0

    def wait(self, timeout=None):
        self.waits += 1
        if self.waits == 1:
            updater._finish_ledger(self._tmp_path, self._status, None)
        return False


def _in_flight_ledger(tmp_path, seconds_ago=5.0) -> None:
    stamped = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    _landed_ledger(tmp_path, status="applying", updated_at=stamped.isoformat(timespec="seconds"))


def test_self_check_started_while_the_helper_is_still_applying_runs_once_it_records_success(monkeypatch, tmp_path):
    # #1926: the helper writes `success` only after this app's /health answers, so the app's first read of
    # the ledger finds `applying`. Reading once and giving up meant no self-check ever ran.
    _in_flight_ledger(tmp_path)
    previous, landed = _versions(tmp_path, _PREVIOUS, _LANDED)
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)
    monkeypatch.setattr(update_poller, "_read_health", lambda: _health(False))
    monkeypatch.setattr(layout, "current_target", lambda d: landed)
    repoints = []
    monkeypatch.setattr(layout, "repoint_current", lambda d, target: repoints.append(target) or True)
    monkeypatch.setattr(update_poller, "_restart_serve_from_current", lambda d: None)
    ticks = iter((0.0, 0.0, 10_000.0))
    stop = _HelperFinishes(tmp_path)

    verdict = update_poller.self_check(_FakeApp(tmp_path), stop, monotonic=lambda: next(ticks, 10_000.0))

    assert stop.waits >= 1  # it waited for the helper rather than reading once
    assert verdict == "rolled_back"
    assert repoints == [previous]


def test_self_check_does_not_judge_an_update_the_helper_recorded_as_failed(monkeypatch, tmp_path):
    _in_flight_ledger(tmp_path)
    _versions(tmp_path, _PREVIOUS, _LANDED)
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)

    def _no_health():
        raise AssertionError("the helper recorded a failure - there is nothing landed to verify")

    monkeypatch.setattr(update_poller, "_read_health", _no_health)

    assert update_poller.self_check(_FakeApp(tmp_path), _HelperFinishes(tmp_path, "failed")) is None


def test_self_check_settles_an_abandoned_applying_ledger_the_way_startup_does(monkeypatch, tmp_path):
    # A helper that died before writing its result: once the ledger reads as abandoned, reconcile_ledger
    # records the landed build as applied (#369), and the check goes ahead on it.
    _in_flight_ledger(tmp_path, seconds_ago=updater.ABANDONED_AFTER_SECONDS + 60)
    _versions(tmp_path, _PREVIOUS, _LANDED)
    app = _FakeApp(tmp_path)

    assert _self_check(monkeypatch, app, health=_health(True)) == "connected"
    led = updater.read_ledger(tmp_path)
    assert (led["status"], led["self_check"]) == ("success", "connected")


def test_self_check_leaves_a_ledger_it_cannot_age_in_flight_and_unjudged(monkeypatch, tmp_path):
    # No readable updated_at never reads as abandoned ("cannot tell" is in flight), so once the wait runs
    # out the check stands down rather than racing a helper that may still be working.
    _landed_ledger(tmp_path, status="applying")
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)

    def _no_health():
        raise AssertionError("an in-flight update is never judged")

    monkeypatch.setattr(update_poller, "_read_health", _no_health)
    ticks = iter((0.0, updater.ABANDONED_AFTER_SECONDS + 1))
    stop = _NoWait(5)

    assert update_poller.self_check(_FakeApp(tmp_path), stop, monotonic=lambda: next(ticks)) is None
    assert updater.read_ledger(tmp_path)["status"] == "applying"


def test_self_check_never_takes_the_app_down_with_it(monkeypatch, tmp_path):
    _landed_ledger(tmp_path)
    monkeypatch.setattr(updater, "current_build", lambda: _LANDED)

    def _boom():
        raise OSError("health socket exploded")

    monkeypatch.setattr(update_poller, "_read_health", _boom)
    assert update_poller.self_check(_FakeApp(tmp_path), threading.Event()) is None


# --- the rollback target survives a failed update (#1932) ---------------------------------------------
# Cleanup kept the two highest build folders, failed ones included, and the rollback took the highest
# folder that was not current. After 50 -> 51 (failed, back on 50) -> 52 that kept 52 and 51, deleted 50,
# and a 52 that could not reach the backend was rolled back onto 51 - the one build known not to work.


def test_after_a_failed_update_the_next_rollback_goes_to_the_build_it_replaced(monkeypatch, tmp_path):
    import logging

    from ucnexus_relay import app as appmod

    b50, b51, b52 = (f"relay-v0.1.0-build.{n}" for n in (50, 51, 52))
    (d50,) = _versions(tmp_path, b50)
    junction = {"current": d50}
    monkeypatch.setattr(layout, "current_target", lambda d: junction["current"])
    monkeypatch.setattr(layout, "repoint_current", lambda d, target: junction.update(current=Path(target)) or True)
    monkeypatch.setattr(updater, "_update_logger", lambda d: logging.getLogger("relay-test-1932"))
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, deadline, log: None)
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: None)
    # 51 never comes up and the helper relaunches 50; then 52 comes up.
    healthy = iter([False, True, True])
    monkeypatch.setattr(updater, "_relaunch_and_wait_healthy", lambda d, deadline, log, attempts=2: next(healthy))
    running = {"dir": d50}
    monkeypatch.setattr(layout, "running_version_dir", lambda: running["dir"])
    app = appmod.RelayApp()
    monkeypatch.setattr(app, "_install_dir", lambda: tmp_path)

    def _update_to(build):
        (ver,) = _versions(tmp_path, build)
        updater._stage_ledger(tmp_path, build, "https://example.invalid/ucnexus-relay.zip", str(ver))
        return ver, updater.apply_staged_update(4242, tmp_path)

    # 50 -> 51: 51 does not start, the junction goes back to 50, and the app comes up on 50 and cleans up.
    _, result = _update_to(b51)
    assert result["ok"] is False and junction["current"] == d50
    app._cleanup_old_versions()

    # 50 -> 52 lands; the helper cleans up, then the app it relaunched on 52 cleans up again.
    d52, result = _update_to(b52)
    assert result["ok"] is True and junction["current"] == d52
    running["dir"] = d52
    app._cleanup_old_versions()
    assert d50.exists()  # the build 52 replaced survives both cleanups

    # 52 never reaches the backend: back to 50, which 52 replaced, not to 51, which already failed.
    monkeypatch.setattr(updater, "current_build", lambda: b52)
    monkeypatch.setattr(update_poller, "_read_health", lambda: _health(False))
    monkeypatch.setattr(update_poller, "_restart_serve_from_current", lambda d: None)
    ticks = iter((0.0, 10_000.0))
    verdict = update_poller.self_check(app, threading.Event(), monotonic=lambda: next(ticks, 10_000.0))

    assert verdict == "rolled_back"
    assert junction["current"] == d50
    led = updater.read_ledger(tmp_path)
    assert led["previous_dir"] == str(d50)
    assert {layout.version_dir_name(b51), layout.version_dir_name(b52)} <= set(led["failed_dirs"])


def test_cleanup_does_not_count_failed_builds_toward_the_two_it_keeps(tmp_path):
    for build in ("relay-v0.1.0-build.49", "relay-v0.1.0-build.50", "relay-v0.1.0-build.51"):
        _versions(tmp_path, build)
    failed = layout.version_dir_name("relay-v0.1.0-build.51")
    updater._write_ledger(tmp_path, {"status": "failed", "failed_dirs": [failed]})

    keep = updater.versions_to_keep(tmp_path)

    assert keep == {layout.version_dir_name("relay-v0.1.0-build.50"), layout.version_dir_name("relay-v0.1.0-build.49")}


def test_cleanup_always_keeps_the_folder_the_last_update_replaced(tmp_path):
    # The first install is app-installed, which carries no build number and so never ranks in the two.
    (installed,) = _versions(tmp_path, "installed")
    _versions(tmp_path, "relay-v0.1.0-build.51", "relay-v0.1.0-build.52")
    updater._write_ledger(tmp_path, {"status": "success", "previous_dir": str(installed)})

    assert installed.name in updater.versions_to_keep(tmp_path)


def test_a_build_that_lands_after_failing_is_no_longer_recorded_as_failed(tmp_path):
    ver = tmp_path / layout.version_dir_name(_LANDED)
    updater._write_ledger(tmp_path, {"status": "applying", "target_dir": str(ver), "failed_dirs": [ver.name]})
    updater._finish_ledger(tmp_path, "success", None)
    assert updater.read_ledger(tmp_path)["failed_dirs"] == []
