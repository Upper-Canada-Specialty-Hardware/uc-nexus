"""Updater: release discovery over the public GitHub API, the current-vs-latest comparison, and the onedir
zip-download + junction-repoint self-update. No network (urlopen/urlretrieve mocked), no real junction."""

import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ucnexus_relay import layout, single_instance, updater

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


def _bundle_zip(dest):
    # ZIP_STORED so the archive is actually >_MIN_ZIP_BYTES (a compressed run of one byte would be tiny and
    # trip the too-small guard); mirrors a real ~27MB onedir bundle.
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("ucnexus-relay.exe", b"N" * 6_000_000)
        zf.writestr("_internal/base_library.zip", b"stub")


# --- release discovery / check_update -----------------------------------------------------------------


def test_current_build_falls_back_to_dev():
    assert updater.current_build() == "dev"


def test_latest_release_picks_highest_build_not_list_order(monkeypatch):
    # regression: GitHub's /releases list is NOT reliably newest-first. Pick by build number, not position.
    payload = [
        {"tag_name": "some-other-v1", "assets": []},
        {
            "tag_name": "relay-v0.1.0-build.9",
            "assets": [{"name": "ucnexus-relay.zip", "browser_download_url": "https://x/b9.zip"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.8",
            "assets": [{"name": "ucnexus-relay.zip", "browser_download_url": "https://x/b8.zip"}],
        },
        {
            "tag_name": "relay-v0.1.0-build.10",
            "assets": [{"name": "ucnexus-relay.zip", "browser_download_url": "https://x/b10.zip"}],
            "published_at": "t10",
        },
    ]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    r = updater.latest_release()
    assert r["tag"] == "relay-v0.1.0-build.10"
    assert r["url"].endswith("b10.zip")


def test_latest_release_requires_the_zip_bundle(monkeypatch):
    # a release with only the old onefile exe asset (no zip bundle) does not count
    payload = [
        {"tag_name": "relay-v0.1.0-build.9", "assets": [{"name": "ucnexus-relay.exe", "browser_download_url": "u"}]}
    ]
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    assert updater.latest_release() == {}


def test_check_update_reports_available(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.7")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "https://x/b.zip"})
    r = updater.check_update()
    assert r["ok"] is True and r["update_available"] is True and r["latest"] == "relay-v0.1.0-build.9"


def test_check_update_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.9")
    monkeypatch.setattr(updater, "latest_release", lambda: {"tag": "relay-v0.1.0-build.9", "url": "u"})
    assert updater.check_update()["update_available"] is False


def test_check_update_never_offers_a_downgrade(monkeypatch):
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


# --- stage_update: download + extract a new version + spawn the helper from the CURRENT exe ------------


def test_stage_update_extracts_version_seeds_ledger_and_spawns_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: _bundle_zip(dest))
    helper_exe = tmp_path / "app-old" / "ucnexus-relay.exe"
    monkeypatch.setattr(single_instance, "installed_exe_path", lambda d: helper_exe)
    calls = []
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, cwd: calls.append((args, cwd)))

    r = updater.stage_update("u", tmp_path, 4242, target_build="relay-v0.1.0-build.11")
    assert r["ok"] is True

    ver = tmp_path / "app-relay-v0.1.0-build.11"
    assert (ver / "ucnexus-relay.exe").exists()  # new version extracted ALONGSIDE the current one
    assert not (tmp_path / "ucnexus-relay-download.zip").exists()  # download cleaned up

    led = updater.read_ledger(tmp_path)
    assert led["status"] == "staging"
    assert led["target_build"] == "relay-v0.1.0-build.11"
    assert led["target_dir"] == str(ver)
    assert led["attempts"] == 0

    assert len(calls) == 1
    args, _ = calls[0]
    assert args == [str(helper_exe), "update-apply", "--pid", "4242"]  # helper runs from the CURRENT exe


def test_stage_update_rejects_a_tiny_download_and_does_not_spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: Path(dest).write_bytes(b"tiny"))

    def _no_spawn(*a, **k):
        raise AssertionError("must not spawn the helper on a bad download")

    monkeypatch.setattr(updater, "_spawn_detached", _no_spawn)
    r = updater.stage_update("u", tmp_path, 1)
    assert r["ok"] is False and "too small" in r["error"]


def test_stage_update_keeps_attempts_for_same_target_but_resets_for_new(tmp_path, monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlretrieve", lambda url, dest: _bundle_zip(dest))
    monkeypatch.setattr(single_instance, "installed_exe_path", lambda d: tmp_path / "cur" / "ucnexus-relay.exe")
    monkeypatch.setattr(updater, "_spawn_detached", lambda args, cwd: None)
    updater._write_ledger(tmp_path, {"status": "failed", "target_build": "relay-v0.1.0-build.11", "attempts": 2})

    updater.stage_update("u", tmp_path, 1, target_build="relay-v0.1.0-build.11")
    assert updater.read_ledger(tmp_path)["attempts"] == 2  # same still-unfinished target -> keep the count

    updater.stage_update("u", tmp_path, 1, target_build="relay-v0.1.0-build.12")
    assert updater.read_ledger(tmp_path)["attempts"] == 0  # a new target -> fresh count


# --- apply_staged_update: the helper repoints the junction + health-gates the relaunch ----------------


def _seed_staged(install_dir, *, build="relay-v0.1.0-build.11", attempts=0, make_new=True):
    ver = install_dir / layout.version_dir_name(build)
    if make_new:
        ver.mkdir(parents=True, exist_ok=True)
        (ver / layout.ASSET_NAME).write_bytes(b"NEW-EXE")
    updater._write_ledger(
        install_dir,
        {"status": "staging", "target_build": build, "target_dir": str(ver), "attempts": attempts},
    )
    return ver


def _patch_apply(monkeypatch, *, healthy, repoints):
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, deadline, log: None)
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: None)
    monkeypatch.setattr(layout, "repoint_current", lambda d, target: repoints.append(Path(target)) or True)
    monkeypatch.setattr(layout, "cleanup_old_versions", lambda d, keep: None)
    seq = iter(healthy)
    monkeypatch.setattr(updater, "_relaunch_and_wait_healthy", lambda d, deadline, log, attempts=2: next(seq))


def test_apply_staged_update_repoints_and_relaunches_healthy(tmp_path, monkeypatch):
    ver = _seed_staged(tmp_path)
    repoints = []
    _patch_apply(monkeypatch, healthy=[True], repoints=repoints)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is True
    assert repoints == [ver]  # the current junction was pointed at the new version
    assert updater.read_ledger(tmp_path)["status"] == "success"


def test_apply_staged_update_rolls_back_when_new_version_unhealthy(tmp_path, monkeypatch):
    ver = _seed_staged(tmp_path)
    old = tmp_path / "app-relay-v0.1.0-build.10"
    old.mkdir()
    repoints = []
    _patch_apply(monkeypatch, healthy=[False, False], repoints=repoints)  # new fails, then the rollback relaunch
    monkeypatch.setattr(updater, "_current_target", lambda d: old)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    assert repoints == [ver, old]  # pointed at the new version, then rolled the junction back to the old one
    assert updater.read_ledger(tmp_path)["status"] == "failed"


def test_apply_staged_update_circuit_breaker_gives_up(tmp_path, monkeypatch):
    _seed_staged(tmp_path, attempts=updater.MAX_ATTEMPTS)  # next run is attempt MAX+1
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)
    relaunches = []
    monkeypatch.setattr(
        updater, "_relaunch_and_wait_healthy", lambda d, deadline, log, attempts=2: relaunches.append(attempts) or True
    )

    def _no_repoint(*a, **k):
        raise AssertionError("circuit breaker must trip before repointing")

    monkeypatch.setattr(layout, "repoint_current", _no_repoint)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False and "gave up" in r["error"]
    assert relaunches == [1]  # relaunched the CURRENT version once, then stopped (no loop)
    assert updater.read_ledger(tmp_path)["status"] == "failed"


def test_apply_staged_update_honors_cancel(tmp_path, monkeypatch):
    _seed_staged(tmp_path)
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)

    def _no_repoint(*a, **k):
        raise AssertionError("cancel must not repoint or relaunch")

    monkeypatch.setattr(layout, "repoint_current", _no_repoint)
    updater.request_cancel(tmp_path)

    r = updater.apply_staged_update(4242, tmp_path)

    assert r.get("cancelled") is True
    assert updater.read_ledger(tmp_path)["status"] == "cancelled"
    assert not (tmp_path / updater._CANCEL_FLAG).exists()


def test_apply_staged_update_missing_staged_version(tmp_path, monkeypatch):
    _seed_staged(tmp_path, make_new=False)  # the ledger's target_dir doesn't exist
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)
    relaunches = []
    monkeypatch.setattr(
        updater, "_relaunch_and_wait_healthy", lambda d, deadline, log, attempts=2: relaunches.append(1) or True
    )

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    assert relaunches == [1]  # relaunched the current version so the relay stays up
    assert updater.read_ledger(tmp_path)["status"] == "failed"


def test_kill_relay_pids_uses_pid_not_image_name(tmp_path, monkeypatch):
    (tmp_path / "relay.pid").write_text("9001", encoding="utf-8")
    killed = []
    monkeypatch.setattr(single_instance, "force_kill_pid", lambda pid: killed.append(int(pid)))

    updater._kill_relay_pids(4242, tmp_path, _LOG)

    assert killed == [4242, 9001]  # app pid + serve pid, both by pid (never taskkill /im)


# --- _wait_for_health ---------------------------------------------------------------------------------


def test_wait_for_health_returns_true_on_ok(monkeypatch):
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: _Resp({"status": "ok"}))
    # drive _monotonic off a tick list that steps PAST the deadline (and no-op _sleep) so a regression that
    # stops returning True times out to False instead of spinning forever on the real clock/sleep.
    ticks = [0.0, 1.0, 2.0]
    monkeypatch.setattr(updater, "_monotonic", lambda: ticks.pop(0) if ticks else 999.0)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)
    assert updater._wait_for_health("http://127.0.0.1:7321/health", 5.0) is True


def test_wait_for_health_logs_last_error_on_timeout(monkeypatch):
    # a never-healthy probe must leave a diagnostic trail (the last swallowed error), not roll back in
    # silence - otherwise the next codec/TLS/logic regression is invisible.
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)
    ticks = [0.0, 1.0]
    monkeypatch.setattr(updater, "_monotonic", lambda: ticks.pop(0) if ticks else 999.0)
    warned = []

    class _CapLog:
        def warning(self, *args, **kwargs):
            warned.append(args)

    assert updater._wait_for_health("http://127.0.0.1:7321/health", 5.0, _CapLog()) is False
    assert warned and "connection refused" in repr(warned[-1])


def test_wait_for_health_swallows_a_probe_error_instead_of_crashing(monkeypatch):
    # regression #318: a frozen build missing the `idna` text codec made getaddrinfo raise
    # `LookupError: unknown encoding: idna`, which the probe did NOT catch (only OSError/JSONDecodeError),
    # so it propagated out of the detached update helper as an unhandled traceback. ANY probe error must be
    # treated as "not up yet" and time out to False - never crash the helper.
    def _boom(*a, **k):
        raise LookupError("unknown encoding: idna")

    monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)
    ticks = [0.0, 1.0, 2.0]  # three probes, then the next monotonic check is past the deadline
    monkeypatch.setattr(updater, "_monotonic", lambda: ticks.pop(0) if ticks else 999.0)

    assert updater._wait_for_health("http://127.0.0.1:7321/health", 5.0) is False


# --- _relaunch_and_wait_healthy -----------------------------------------------------------------------


def test_relaunch_and_wait_healthy_stops_when_health_ok(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(single_instance, "launch_installed", lambda d: launches.append(1))
    monkeypatch.setattr(updater, "_wait_for_health", lambda url, deadline, log=None: True)

    assert updater._relaunch_and_wait_healthy(tmp_path, updater._monotonic() + 30, _LOG) is True
    assert launches == [1]  # one launch, healthy - no retry


def test_relaunch_and_wait_healthy_retries_then_gives_up(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(single_instance, "launch_installed", lambda d: launches.append(1))
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: None)
    monkeypatch.setattr(updater, "_wait_for_health", lambda url, deadline, log=None: False)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)

    ok = updater._relaunch_and_wait_healthy(tmp_path, updater._monotonic() + 1000, _LOG, attempts=2)
    assert ok is False and len(launches) == 2  # tried twice within the deadline, never healthy


def test_relaunch_and_wait_healthy_kills_the_launched_app_between_retries(tmp_path, monkeypatch):
    # regression: an unhealthy-but-alive app is the single-instance owner, so the next attempt (and the
    # rollback launch) would focus-deflect to it and never re-serve. The between-attempts kill must target
    # the app pid launch_installed returned, NOT None (which would leave that owner alive).
    pids = iter([111, 222])
    monkeypatch.setattr(single_instance, "launch_installed", lambda d: next(pids))
    killed = []
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: killed.append(pid))
    monkeypatch.setattr(updater, "_wait_for_health", lambda url, deadline, log=None: False)
    monkeypatch.setattr(updater, "_sleep", lambda s: None)

    ok = updater._relaunch_and_wait_healthy(tmp_path, updater._monotonic() + 1000, _LOG, attempts=2)

    assert ok is False
    assert killed == [111, 222]  # each unhealthy attempt's own app pid is force-killed before the next


def test_apply_staged_update_rolls_back_when_the_repoint_fails(tmp_path, monkeypatch):
    # regression: a failed junction repoint (removed the link but couldn't recreate it) left `current`
    # broken; proceeding would relaunch via the newest-version fallback and record success while autostart
    # + shortcuts point at a dead junction. Must roll the junction back to the previous version + fail.
    ver = _seed_staged(tmp_path)
    old = tmp_path / "app-relay-v0.1.0-build.10"
    old.mkdir()
    monkeypatch.setattr(updater, "_update_logger", lambda d: _LOG)
    monkeypatch.setattr(updater, "_wait_for_pid_exit", lambda pid, deadline, log: None)
    monkeypatch.setattr(updater, "_kill_relay_pids", lambda pid, d, log: None)
    monkeypatch.setattr(updater, "_current_target", lambda d: old)
    repoints = []

    def _repoint(d, target):
        repoints.append(Path(target))
        return Path(target).name != ver.name  # the repoint TO the new version fails; the rollback succeeds

    monkeypatch.setattr(layout, "repoint_current", _repoint)
    relaunched = []
    monkeypatch.setattr(
        updater, "_relaunch_and_wait_healthy", lambda d, deadline, log, attempts=2: relaunched.append(1) or True
    )

    r = updater.apply_staged_update(4242, tmp_path)

    assert r["ok"] is False
    assert repoints == [ver, old]  # tried the new version, then rolled the junction back to the old one
    assert relaunched == [1]  # relaunched the rolled-back (previous) version so the relay stays up
    assert updater.read_ledger(tmp_path)["status"] == "failed"


# --- stuck-ledger reconciliation (#369) ---------------------------------------------------------------
# A helper that dies before writing its terminal status leaves the ledger on staging/applying forever,
# and update_poller.should_stage reads that as "an update is already in progress" - so the relay stops
# updating and nobody finds out. These pin the recovery, including the case that actually happened:
# the update LANDED and only the bookkeeping was lost.


def _aged_ledger(seconds_ago: float, **overrides) -> dict:
    stamped = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    led = {
        "status": "applying",
        "target_build": "relay-v0.1.0-build.36",
        "attempts": 1,
        "last_error": None,
        "updated_at": stamped.isoformat(timespec="seconds"),
    }
    led.update(overrides)
    return led


def test_reconcile_marks_a_stuck_ledger_applied_when_that_build_is_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.36")
    updater._write_ledger(tmp_path, _aged_ledger(updater.ABANDONED_AFTER_SECONDS + 60))

    assert updater.reconcile_ledger(tmp_path) == "success"
    assert updater.read_ledger(tmp_path)["status"] == "success"


def test_reconcile_marks_a_stuck_ledger_failed_when_the_build_never_took(tmp_path, monkeypatch):
    # The attempt genuinely failed, so it has to be recorded as such - forgiving it would hide a build
    # that cannot install from the MAX_ATTEMPTS circuit breaker.
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.32")
    updater._write_ledger(tmp_path, _aged_ledger(updater.ABANDONED_AFTER_SECONDS + 60))

    assert updater.reconcile_ledger(tmp_path) == "failed"
    led = updater.read_ledger(tmp_path)
    assert led["status"] == "failed"
    assert led["attempts"] == 1  # untouched, so the breaker still counts this attempt
    assert "without recording a result" in led["last_error"]


def test_reconcile_leaves_a_genuinely_in_flight_ledger_alone(tmp_path, monkeypatch):
    # This runs in the newly relaunched app while the helper that launched it is still health-probing.
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.36")
    updater._write_ledger(tmp_path, _aged_ledger(5))

    assert updater.reconcile_ledger(tmp_path) is None
    assert updater.read_ledger(tmp_path)["status"] == "applying"


def test_reconcile_ignores_settled_and_missing_ledgers(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.36")
    assert updater.reconcile_ledger(tmp_path) is None  # no file at all

    for status in ("success", "failed", "cancelled"):
        updater._write_ledger(tmp_path, _aged_ledger(updater.ABANDONED_AFTER_SECONDS + 60, status=status))
        assert updater.reconcile_ledger(tmp_path) is None, status
        assert updater.read_ledger(tmp_path)["status"] == status


def test_a_ledger_with_no_readable_timestamp_is_never_abandoned(tmp_path):
    # "Cannot tell how old it is" must read as in-flight; the other way round races a live helper.
    assert updater.ledger_is_abandoned({"status": "applying"}) is False
    assert updater.ledger_is_abandoned({"status": "applying", "updated_at": "not-a-date"}) is False
    assert updater.ledger_age_seconds({"updated_at": "not-a-date"}) is None
