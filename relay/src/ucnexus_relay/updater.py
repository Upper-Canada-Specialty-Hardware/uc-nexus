"""Self-update from the public GitHub releases - the relay UI's third purpose (setup, updates, logs).

The repo is public, so the relay checks the releases API and downloads the build (a ucnexus-relay.zip
onedir bundle) with no auth token and no backend involvement.

Applying an update: the relay is a PyInstaller ONEDIR bundle installed under a versioned app-<build>/ folder,
fronted by a stable `current` directory junction that shortcuts + autostart target (see layout.py). An
update downloads the zip, extracts the new version alongside the current one, and hands off to a detached
helper (this exe re-invoked as `update-apply`) that - running from the OLD, already-settled version -
force-stops the old relay by pid, repoints the `current` junction to the new version, and relaunches it,
health-gated. Nothing renames or copies a running folder, and the new version's .pyd were written to disk
at extract time (so Windows Defender scans them before launch, not during it - the crash that killed the
old onefile self-update). The helper is windowless, logged to update.log, and bounded by a wall-clock
deadline + an attempt ledger (update-state.json) so it can never loop or hang.

The build identity comes from _build.py, which CI stamps into the package at build time (see
.github/workflows/relay-release.yml). A dev checkout has no _build.py, so current_build() is 'dev', which
compares unequal to any release tag (always "behind")."""

import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import layout

REPO = "Upper-Canada-Specialty-Hardware/uc-nexus"
_RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
_RELEASE_ASSET = "ucnexus-relay.zip"  # the onedir bundle published on each release
_MIN_ZIP_BYTES = 5_000_000  # a real bundle zip is ~27MB; guard against a truncated body / HTML error page
_MIN_EXE_BYTES = 5_000_000  # the extracted exe

# --- self-update helper bounds ------------------------------------------------------------------------
_STATE_FILE = "update-state.json"  # the attempt ledger the helper reads/writes and the UI surfaces
_CANCEL_FLAG = "update-cancel"  # touched by a user-initiated shutdown to abort an in-flight update
_UPDATE_LOG = "update.log"  # the helper's own log, next to config.toml
_DOWNLOAD_NAME = "ucnexus-relay-download.zip"
MAX_ATTEMPTS = 3  # circuit breaker: give up on a target build after this many helper runs
_GLOBAL_DEADLINE_SECONDS = 90.0  # hard wall-clock cap on the whole sequence
_APP_EXIT_WAIT_SECONDS = 20.0  # how long to wait for the app to exit on its own before force-killing
_HEALTH_WAIT_PER_ATTEMPT = 25.0  # per relaunch attempt, how long to wait for /health before retrying
_POLL_SECONDS = 0.5

_DETACHED_PROCESS = 0x00000008  # DETACHED alone (never paired with CREATE_NO_WINDOW - see stage/_spawn)

_monotonic = time.monotonic  # module-level seams so tests can drive the deadline/retry loops
_sleep = time.sleep


def current_build() -> str:
    try:
        from ._build import BUILD

        return BUILD
    except ImportError:
        return "dev"


def build_number(tag: str) -> int:
    """The trailing build number of a `relay-v<ver>-build.<N>` tag (-1 if none, e.g. 'dev' or a plain
    relay-v tag). Used to pick the newest release and to gate updates by version, not list order."""
    m = re.search(r"build\.(\d+)$", tag or "")
    return int(m.group(1)) if m else -1


def latest_release() -> dict:
    """The relay-v* release with the HIGHEST build number that carries the bundle zip. GitHub's /releases
    list is not reliably newest-first, so pick by build number rather than trusting list order. {} if none."""
    req = urllib.request.Request(_RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (fixed public GitHub API URL)
        releases = json.loads(r.read().decode())
    best: dict = {}
    best_n = -2
    for rel in releases:
        tag = rel.get("tag_name", "")
        if not tag.startswith("relay-v"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == _RELEASE_ASSET), None)
        if not (asset and asset.get("browser_download_url")):
            continue
        n = build_number(tag)
        if n > best_n:
            best_n = n
            best = {"tag": tag, "url": asset["browser_download_url"], "published_at": rel.get("published_at")}
    return best


def check_update() -> dict:
    cur = current_build()
    try:
        latest = latest_release()
    except OSError as e:
        return {"ok": False, "error": f"could not reach GitHub releases: {e}"}
    if not latest:
        return {"ok": False, "error": "no relay release with a bundle was found"}
    # Only offer an update when the release is a HIGHER build than the installed one - never a downgrade.
    update_available = build_number(latest["tag"]) > build_number(cur)
    return {
        "ok": True,
        "current": cur,
        "latest": latest["tag"],
        "update_available": update_available,
        "url": latest["url"],
    }


def _unlink_quietly(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


# --- attempt ledger (update-state.json) ---------------------------------------------------------------
# One small JSON file the staging step seeds and the helper updates, so a failure is recorded (surfaced in
# the Updates tab) and repeated attempts at the SAME target build are capped. Shape:
#   {status, target_build, target_url, target_dir, attempts, last_error, first_attempt_at, updated_at}
# status in: staging | applying | success | failed | cancelled.


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_ledger(install_dir: str | Path) -> dict:
    """The current update-state.json, or {} if absent/corrupt. Public so the UI can show the last result."""
    try:
        return json.loads((Path(install_dir) / _STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_ledger(install_dir: Path, data: dict) -> None:
    try:
        (install_dir / _STATE_FILE).write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _stage_ledger(install_dir: Path, target_build: str, target_url: str, target_dir: str) -> None:
    """Seed the ledger for a fresh staging. Preserves the attempt count only when re-staging the SAME
    still-unfinished target (so hammering a failing build is capped); a new target or a prior success
    resets it to 0."""
    prev = read_ledger(install_dir)
    same = bool(target_build) and prev.get("target_build") == target_build and prev.get("status") != "success"
    _write_ledger(
        install_dir,
        {
            "status": "staging",
            "target_build": target_build,
            "target_url": target_url,
            "target_dir": target_dir,
            "attempts": prev.get("attempts", 0) if same else 0,
            "last_error": prev.get("last_error") if same else None,
            "first_attempt_at": prev.get("first_attempt_at") if same else None,
            "updated_at": _now_iso(),
        },
    )


def _finish_ledger(install_dir: Path, status: str, error: str | None) -> None:
    ledger = read_ledger(install_dir)
    ledger["status"] = status
    ledger["last_error"] = error
    ledger["updated_at"] = _now_iso()
    _write_ledger(install_dir, ledger)


# --- cancel flag --------------------------------------------------------------------------------------


def request_cancel(install_dir: str | Path) -> None:
    """Ask an in-flight update to abort WITHOUT relaunching. Written by a user-initiated shutdown so
    closing the relay mid-update is respected (see app.RelayApp.user_shutdown)."""
    try:
        (Path(install_dir) / _CANCEL_FLAG).write_text("1", encoding="utf-8")
    except OSError:
        pass


def _cancel_requested(install_dir: Path) -> bool:
    return (install_dir / _CANCEL_FLAG).exists()


def _clear_cancel(install_dir: Path) -> None:
    _unlink_quietly(install_dir / _CANCEL_FLAG)


# --- process helpers ----------------------------------------------------------------------------------


def _spawn_detached(args: list[str], cwd: str | Path) -> None:
    """Launch our own GUI-subsystem exe fully detached, windowless. DETACHED_PROCESS alone - never paired
    with CREATE_NO_WINDOW (contradictory; that pairing spawned visible consoles in the old .bat)."""
    subprocess.Popen(  # noqa: S603 (our own exe path + fixed subcommand)
        args,
        cwd=str(cwd),
        creationflags=_DETACHED_PROCESS,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


def _update_logger(install_dir: Path) -> logging.Logger:
    """A dedicated logger writing update.log next to config.toml, so a broken update is diagnosable."""
    logger = logging.getLogger("ucnexus_relay.update")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        try:
            fh = logging.FileHandler(install_dir / _UPDATE_LOG, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(fh)
        except OSError:
            logger.addHandler(logging.NullHandler())
        logger.propagate = False
    return logger


def _pid_alive(pid) -> bool:
    """True if `pid` is a live process. Windows: OpenProcess + GetExitCodeProcess (no tasklist)."""
    if not pid:
        return False
    if sys.platform != "win32":
        try:
            os.kill(int(pid), 0)
            return True
        except (OSError, ValueError):
            return False
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    k = ctypes.windll.kernel32
    handle = k.OpenProcess(process_query_limited_information, False, int(pid))
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == still_active
    finally:
        k.CloseHandle(handle)


def _read_serve_pid(install_dir: Path) -> int | None:
    try:
        return int((install_dir / "relay.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _wait_for_pid_exit(pid, deadline: float, log: logging.Logger) -> None:
    until = min(deadline, _monotonic() + _APP_EXIT_WAIT_SECONDS)
    while _monotonic() < until:
        if not _pid_alive(pid):
            log.info("app pid %s exited", pid)
            return
        _sleep(_POLL_SECONDS)
    if _pid_alive(pid):
        log.info("app pid %s still alive after %ss; will force-kill", pid, _APP_EXIT_WAIT_SECONDS)


def _kill_relay_pids(app_pid, install_dir: Path, log: logging.Logger) -> None:
    """Force any remaining relay process down BY PID (the app pid we were handed + the serve child from
    relay.pid). Never by image name - this helper IS ucnexus-relay.exe and would kill itself."""
    from . import single_instance

    if app_pid:
        single_instance.force_kill_pid(app_pid)
        log.info("force-killed app pid %s (no-op if already gone)", app_pid)
    serve_pid = _read_serve_pid(install_dir)
    if serve_pid and serve_pid != app_pid:
        single_instance.force_kill_pid(serve_pid)
        log.info("force-killed serve pid %s", serve_pid)


# --- health-gated relaunch ----------------------------------------------------------------------------


def _health_url(install_dir: Path) -> str:
    try:
        from .config import get_settings

        s = get_settings()
        return f"http://{s.server.host}:{s.server.port}/health"
    except Exception:  # noqa: BLE001 - a missing/odd config falls back to the baked default port
        return "http://127.0.0.1:7321/health"


def _wait_for_health(url: str, deadline: float, log: logging.Logger | None = None) -> bool:
    last_err: Exception | None = None
    while _monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 (localhost health URL)
                if json.loads(r.read().decode()).get("status") == "ok":
                    return True
        except Exception as e:  # noqa: BLE001 - the probe's ONLY job is "is it up yet?"; ANY failure
            # (connection refused, a partial body, or a missing text codec like #318's
            # `LookupError: unknown encoding: idna`) means not-up-yet. Swallow it and retry within the
            # deadline rather than letting it propagate out of the detached update helper as an unhandled
            # traceback (the #318 crash). Keep the last one so a never-healthy timeout still leaves a
            # diagnostic trail instead of a silent rollback with no signal.
            last_err = e
        _sleep(2.0)
    if log is not None and last_err is not None:
        log.warning("health probe %s never returned ok before the deadline; last error: %r", url, last_err)
    return False


def _relaunch_and_wait_healthy(install_dir: Path, deadline: float, log: logging.Logger, attempts: int = 2) -> bool:
    """Launch the current version and wait for /health, retrying up to `attempts` within the deadline. The
    first launch after an extract also completes Defender's scan of the new .pyd, so a retry lands clean if
    the first ever stumbles. Between attempts, kill the app we just launched AND its serve child: the app is
    single-instance, so a still-alive-but-unhealthy owner would focus-deflect (and never re-serve) the next
    launch and the rollback launch, leaving the relay down - the exact failure the health gate must prevent."""
    from . import single_instance

    url = _health_url(install_dir)
    for i in range(1, attempts + 1):
        if _monotonic() >= deadline:
            break
        app_pid = single_instance.launch_installed(install_dir)
        log.info("relaunch attempt %d of %d (pid %s)", i, attempts, app_pid)
        if _wait_for_health(url, min(deadline, _monotonic() + _HEALTH_WAIT_PER_ATTEMPT), log):
            log.info("relay healthy after relaunch")
            return True
        _kill_relay_pids(app_pid, install_dir, log)  # clear the crashed/hung app + serve before retrying
    return False


def _current_target(install_dir: Path) -> Path | None:
    """The real folder the `current` junction points at now (for rollback on a failed update)."""
    link = layout.current_link(install_dir)
    try:
        if link.exists():
            return link.resolve()
    except OSError:
        pass
    return None


# --- staging + applying -------------------------------------------------------------------------------


def _download_and_extract(url: str, install_dir: Path, target_build: str | None) -> tuple[Path | None, str | None]:
    """Download the bundle zip and extract it to a versioned app-<build>/ folder. Returns (version_dir,
    None) on success or (None, error)."""
    zip_path = install_dir / _DOWNLOAD_NAME
    try:
        urllib.request.urlretrieve(url, str(zip_path))  # noqa: S310 (release asset URL from latest_release)
    except OSError as e:
        return None, f"download failed: {e}"
    if zip_path.stat().st_size < _MIN_ZIP_BYTES:
        _unlink_quietly(zip_path)
        return None, "the downloaded file is too small - aborting the update"
    ver = layout.version_dir(install_dir, target_build or "staged")
    try:
        layout.extract_zip(zip_path, ver)
    except (OSError, zipfile.BadZipFile) as e:
        _unlink_quietly(zip_path)
        return None, f"extract failed: {e}"
    _unlink_quietly(zip_path)
    new_exe = ver / layout.ASSET_NAME
    if not new_exe.exists() or new_exe.stat().st_size < _MIN_EXE_BYTES:
        return None, "the extracted bundle is missing ucnexus-relay.exe"
    return ver, None


def stage_update(url: str, install_dir: str | Path, app_pid: int, target_build: str | None = None) -> dict:
    """Download + extract the new version alongside the current one, seed the ledger, and spawn the detached
    windowless helper from the CURRENT (settled) exe. The caller (ui.apply_update) then shuts the app down
    so the helper can repoint the junction and relaunch."""
    from . import single_instance

    install_dir = Path(install_dir)
    ver, error = _download_and_extract(url, install_dir, target_build)
    if ver is None:
        return {"ok": False, "error": error}

    _clear_cancel(install_dir)
    _stage_ledger(install_dir, target_build or "", url, str(ver))
    helper_exe = single_instance.installed_exe_path(install_dir)  # the current, already-scanned version
    _spawn_detached([str(helper_exe), "update-apply", "--pid", str(int(app_pid))], cwd=install_dir)
    return {"ok": True, "note": "the relay will close and reopen on the new version"}


def _give_up(install_dir: Path, log: logging.Logger, reason: str) -> dict:
    log.warning("update giving up: %s", reason)
    _finish_ledger(install_dir, "failed", reason)
    _relaunch_and_wait_healthy(install_dir, _monotonic() + 30.0, log, attempts=1)
    return {"ok": False, "error": reason}


def apply_staged_update(app_pid, install_dir: str | Path) -> dict:
    """The detached helper (run as `ucnexus-relay update-apply`), running from the OLD version: wait for the
    app to exit, force any remaining relay process down by pid, repoint the `current` junction to the staged
    new version, and relaunch it (health-gated). Rolls the junction back to the previous version if the new
    one doesn't come up, so the relay is never left down. Relaunches nothing on a user cancel. Bounded by a
    deadline + an attempt ledger; never loops."""
    install_dir = Path(install_dir)
    log = _update_logger(install_dir)

    ledger = read_ledger(install_dir)
    attempts = ledger.get("attempts", 0) + 1
    target = ledger.get("target_build") or "?"
    target_dir = ledger.get("target_dir")
    ledger["status"] = "applying"
    ledger["attempts"] = attempts
    ledger["updated_at"] = _now_iso()
    if not ledger.get("first_attempt_at"):
        # _stage_ledger seeds this key as None for a fresh target, so setdefault would never stamp it -
        # set it explicitly on the first apply that has no timestamp yet.
        ledger["first_attempt_at"] = _now_iso()
    _write_ledger(install_dir, ledger)
    log.info("update-apply start: target=%s attempt=%s app_pid=%s", target, attempts, app_pid)

    if attempts > MAX_ATTEMPTS:
        return _give_up(
            install_dir, log, f"gave up after {MAX_ATTEMPTS} attempts to update to {target}; reboot and retry"
        )

    if _cancel_requested(install_dir):
        log.info("cancel requested before apply; aborting without relaunch")
        _finish_ledger(install_dir, "cancelled", None)
        _clear_cancel(install_dir)
        return {"ok": False, "cancelled": True}

    new_dir = Path(target_dir) if target_dir else None
    if new_dir is None or not (new_dir / layout.ASSET_NAME).exists():
        msg = "the staged version folder is missing; nothing to apply"
        log.warning(msg)
        _finish_ledger(install_dir, "failed", msg)
        _relaunch_and_wait_healthy(install_dir, _monotonic() + 30.0, log, attempts=1)
        return {"ok": False, "error": msg}

    old_target = _current_target(install_dir)  # for rollback
    deadline = _monotonic() + _GLOBAL_DEADLINE_SECONDS

    _wait_for_pid_exit(app_pid, deadline, log)
    _kill_relay_pids(app_pid, install_dir, log)

    if _cancel_requested(install_dir):
        log.info("cancel requested during teardown; aborting without relaunch")
        _finish_ledger(install_dir, "cancelled", None)
        _clear_cancel(install_dir)
        return {"ok": False, "cancelled": True}

    if not layout.repoint_current(install_dir, new_dir):
        # The junction is the single source of truth for autostart + shortcuts (they target
        # current\ucnexus-relay.exe). A failed repoint may have removed the link without recreating it;
        # relaunching would come up via the newest-version fallback and record "success" while current is
        # broken, silently breaking the next logon's autostart. Roll back to the previous version instead.
        log.warning("could not repoint the current junction to %s; rolling back", new_dir)
        if old_target is not None and old_target != new_dir:
            layout.repoint_current(install_dir, old_target)
        _relaunch_and_wait_healthy(install_dir, _monotonic() + 30.0, log)
        _finish_ledger(install_dir, "failed", "could not repoint the current junction to the new version")
        return {"ok": False, "error": "could not repoint the current junction to the new version"}

    if _relaunch_and_wait_healthy(install_dir, deadline, log):
        _finish_ledger(install_dir, "success", None)
        layout.cleanup_old_versions(install_dir, keep={new_dir.name})
        log.info("update applied: now on %s", target)
        return {"ok": True}

    # the new version didn't come up healthy - roll the junction back and relaunch the previous version
    log.warning("the updated version did not become healthy; rolling back")
    if old_target is not None and old_target != new_dir:
        layout.repoint_current(install_dir, old_target)
    _relaunch_and_wait_healthy(install_dir, _monotonic() + 30.0, log)
    _finish_ledger(install_dir, "failed", "the updated version did not start; rolled back to the previous one")
    return {"ok": False, "error": "the updated version did not start; rolled back to the previous one"}


def apply_update(url: str, install_dir: str | Path) -> dict:
    """Standalone (non-desktop) in-process apply: download + extract the new version, stop serve, repoint
    the junction, and restart serve from it. Rolls back on a failed repoint so the relay is never left down.
    The desktop app uses stage_update + apply_staged_update instead."""
    from . import setup, single_instance

    install_dir = Path(install_dir)
    ver, error = _download_and_extract(url, install_dir, None)
    if ver is None:
        return {"ok": False, "error": error}

    old_target = _current_target(install_dir)
    setup.stop_serve(install_dir)
    ok = layout.repoint_current(install_dir, ver)
    try:
        setup.start_serve(single_instance.installed_exe_path(install_dir), install_dir)
    except Exception:  # noqa: BLE001
        pass
    if ok:
        layout.cleanup_old_versions(install_dir, keep={ver.name})
        return {"ok": True, "restarted": True, "note": "reopen the window to load the updated UI"}
    if old_target is not None:
        layout.repoint_current(install_dir, old_target)
    return {"ok": False, "error": "could not repoint to the new version; the relay stays on the current one"}
