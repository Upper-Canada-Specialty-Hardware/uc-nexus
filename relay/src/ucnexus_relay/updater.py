"""Self-update from the public GitHub releases - the relay UI's third purpose (setup, updates, logs).

The repo is public, so the relay checks the releases API and downloads the exe with no auth token and no
backend involvement. Applying an update on Windows is the tricky part: a running exe is locked and can't
be overwritten, but it CAN be renamed. So we download the new exe, rename the current one aside, drop the
new one into its place, and restart.

The desktop app can't swap the exe it is running from and keep running, so it hands the swap to a detached
helper: it stages the download, then exits, and a SEPARATE process (this exe re-invoked as `update-apply`)
waits for the app to go, swaps the exe, and relaunches. That helper used to be a fire-and-forget .bat that
could resurrect a closed app, kill every relay process by image name, spawn visible consoles, and loop with
no timeout or record. It is now `apply_staged_update()` below: windowless, logged to update.log, bounded by
a wall-clock deadline and an attempt ledger (update-state.json), killing only by pid and relaunching
exactly once. See the module-level constants for the bounds.

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
from datetime import datetime, timezone
from pathlib import Path

REPO = "Upper-Canada-Specialty-Hardware/uc-nexus"
_RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
_ASSET_NAME = "ucnexus-relay.exe"
_MIN_EXE_BYTES = 5_000_000  # a real exe is ~20MB; guard against a truncated body / HTML error page

# --- self-update helper bounds ------------------------------------------------------------------------
_STATE_FILE = "update-state.json"  # the attempt ledger the helper reads/writes and the UI surfaces
_CANCEL_FLAG = "update-cancel"     # touched by a user-initiated shutdown to abort an in-flight update
_UPDATE_LOG = "update.log"         # the helper's own log, next to config.toml
MAX_ATTEMPTS = 3                   # circuit breaker: give up on a target build after this many helper runs
_GLOBAL_DEADLINE_SECONDS = 90.0    # hard wall-clock cap on the whole wait+kill+swap sequence
_APP_EXIT_WAIT_SECONDS = 20.0      # how long to wait for the app to exit on its own before force-killing
_SWAP_RETRY_SECONDS = 1.0          # pause between swap attempts while Windows releases the exe handle
_POLL_SECONDS = 0.5                # app-exit poll interval

# Windows process-creation flags. DETACHED_PROCESS alone (NOT combined with CREATE_NO_WINDOW - the two are
# contradictory and that pairing is what made the old .bat helper's cmd children pop visible consoles).
_DETACHED_PROCESS = 0x00000008

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
    """The relay-v* release with the HIGHEST build number that carries the exe asset. GitHub's /releases
    list is not reliably newest-first (a newer build can appear mid-list), so pick by build number rather
    than trusting list order. {} if none."""
    req = urllib.request.Request(_RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (fixed public GitHub API URL)
        releases = json.loads(r.read().decode())
    best: dict = {}
    best_n = -2
    for rel in releases:
        tag = rel.get("tag_name", "")
        if not tag.startswith("relay-v"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == _ASSET_NAME), None)
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
        return {"ok": False, "error": "no relay release with an exe asset was found"}
    # Only offer an update when the release is a HIGHER build than the installed one - never a downgrade.
    # 'dev' has build number -1, so any real release is an update from a dev checkout.
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


def _free_old_path(install_dir: Path) -> Path:
    """A '.old' path to rename the running exe aside to that isn't currently locked. A prior update's
    '.old' may still be held by an app/ui window that hasn't closed; picking a free variant instead of
    reusing a locked one is what keeps a second update from failing the swap."""
    base = install_dir / (_ASSET_NAME + ".old")
    for candidate in [base, *(install_dir / f"{_ASSET_NAME}.old.{i}" for i in range(1, 20))]:
        _unlink_quietly(candidate)  # clear a stale one if we can
        if not candidate.exists():
            return candidate
    return install_dir / (_ASSET_NAME + ".old.x")  # last resort


def _cleanup_old(install_dir: Path) -> None:
    for p in install_dir.glob(_ASSET_NAME + ".old*"):
        _unlink_quietly(p)


def apply_update(url: str, install_dir: str | Path) -> dict:
    """Download `url` and swap it in for the installed exe, then restart serve. The relay is ALWAYS
    restarted on the way out, so a failed swap leaves it running on the CURRENT version rather than down
    (rename-while-running; see the module docstring). This is the STANDALONE (non-desktop) path; the
    desktop app uses stage_update + apply_staged_update instead."""
    from . import setup

    install_dir = Path(install_dir)
    exe = install_dir / _ASSET_NAME
    new = install_dir / (_ASSET_NAME + ".new")

    try:
        urllib.request.urlretrieve(url, str(new))  # noqa: S310 (release asset URL from latest_release)
    except OSError as e:
        return {"ok": False, "error": f"download failed: {e}"}
    if new.stat().st_size < _MIN_EXE_BYTES:
        _unlink_quietly(new)
        return {"ok": False, "error": "the downloaded file is too small - aborting the swap"}

    # Stop serve (releases its exe lock), swap, then ALWAYS restart serve in the finally so GP comes back
    # up even if the swap fails. The app/ui process still holds the exe image, hence rename-not-overwrite.
    setup.stop_serve(install_dir)
    old = _free_old_path(install_dir)
    swapped = False
    error = None
    try:
        os.replace(exe, old)  # rename the running exe aside (Windows permits renaming a running image)
        os.replace(new, exe)  # move the new exe into place
        swapped = True
    except OSError as e:
        error = str(e)
        if not exe.exists() and old.exists():  # renamed aside but couldn't drop the new one -> roll back
            try:
                os.replace(old, exe)
            except OSError:
                pass
    finally:
        setup.start_serve(exe, install_dir)

    if swapped:
        _cleanup_old(install_dir)
        return {"ok": True, "restarted": True, "note": "reopen the window to load the updated UI"}
    _unlink_quietly(new)
    return {
        "ok": False,
        "error": f"swap failed ({error}); the relay was restarted on the current version - reboot and retry",
    }


# --- attempt ledger (update-state.json) ---------------------------------------------------------------
# One small JSON file the staging step seeds and the helper updates, so a failure is recorded (surfaced in
# the Updates tab) and repeated attempts at the SAME target build are capped. Shape:
#   {status, target_build, target_url, attempts, last_error, first_attempt_at, updated_at}
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


def _stage_ledger(install_dir: Path, target_build: str, target_url: str) -> None:
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


# --- the detached helper ------------------------------------------------------------------------------


def _spawn_detached(args: list[str], cwd: str | Path) -> None:
    """Launch our own GUI-subsystem exe fully detached, windowless. DETACHED_PROCESS alone - never paired
    with CREATE_NO_WINDOW (contradictory; that pairing spawned the visible consoles in the old .bat)."""
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
    """A dedicated logger writing update.log next to config.toml, so a broken update is diagnosable
    (the old .bat swallowed everything with >nul 2>&1)."""
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
    """True if `pid` is a live process. Windows: OpenProcess + GetExitCodeProcess (no tasklist, which the
    old helper piped through find and which flashed consoles)."""
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
    """Wait (bounded by both _APP_EXIT_WAIT_SECONDS and the global deadline) for the app to exit on its
    own, so a clean shutdown can finish before we force anything."""
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


def _swap_new_over_exe(exe: Path, new: Path, install_dir: Path, deadline: float, log: logging.Logger):
    """Rename the (now-unlocked) exe aside and drop the new one in, retrying while Windows releases the
    handle, until the deadline. On a partial failure (renamed aside but couldn't move the new one in) the
    old exe is put back, so the relay is never left without an exe. Returns (swapped: bool, error|None)."""
    error = None
    while True:
        old = _free_old_path(install_dir)
        try:
            os.replace(exe, old)  # rename running/held image aside (permitted on Win10/11)
        except OSError as e:
            error = f"rename-aside failed: {e}"
        else:
            try:
                os.replace(new, exe)  # move the new bytes into place
                return True, None
            except OSError as e:
                error = f"move-new-in failed: {e}"
                if not exe.exists():  # roll back so we never leave the relay without its exe
                    try:
                        os.replace(old, exe)
                    except OSError:
                        pass
        if _monotonic() >= deadline:
            return False, error
        log.info("swap retry (%s)", error)
        _sleep(_SWAP_RETRY_SECONDS)


def _relaunch(exe: Path, log: logging.Logger) -> None:
    """Relaunch the desktop app from `exe`, exactly once. Reuses the single-instance detached launcher."""
    from . import single_instance

    try:
        single_instance.launch_installed(exe.parent)
        log.info("relaunched %s app", exe.name)
    except Exception:
        log.exception("failed to relaunch %s", exe.name)


def stage_update(url: str, install_dir: str | Path, app_pid: int, target_build: str | None = None) -> dict:
    """Download the new exe, seed the attempt ledger, and spawn the detached windowless helper
    (`ucnexus-relay update-apply`). The caller (ui.apply_update) then shuts the app down so the helper can
    swap the now-unlocked exe and relaunch. No batch file, no image-name kills, no visible console."""
    install_dir = Path(install_dir)
    exe = install_dir / _ASSET_NAME
    new = install_dir / (_ASSET_NAME + ".new")

    try:
        urllib.request.urlretrieve(url, str(new))  # noqa: S310 (release asset URL from latest_release)
    except OSError as e:
        return {"ok": False, "error": f"download failed: {e}"}
    if new.stat().st_size < _MIN_EXE_BYTES:
        _unlink_quietly(new)
        return {"ok": False, "error": "the downloaded file is too small - aborting the update"}

    _clear_cancel(install_dir)
    _stage_ledger(install_dir, target_build or "", url)
    _spawn_detached([str(exe), "update-apply", "--pid", str(int(app_pid))], cwd=install_dir)
    return {"ok": True, "note": "the relay will close and reopen on the new version"}


def apply_staged_update(app_pid, install_dir: str | Path) -> dict:
    """The detached helper (run as `ucnexus-relay update-apply`): wait for the app to exit, force any
    remaining relay process down by pid, swap the staged exe in, and relaunch exactly once - all bounded
    by a wall-clock deadline and an attempt ledger, all logged to update.log. Relaunches the NEW exe on a
    clean swap, the CURRENT exe on failure (so the relay is never left down), and NOTHING on a user
    cancel. Never loops and never re-enters staging."""
    install_dir = Path(install_dir)
    exe = install_dir / _ASSET_NAME
    new = install_dir / (_ASSET_NAME + ".new")
    log = _update_logger(install_dir)

    ledger = read_ledger(install_dir)
    attempts = ledger.get("attempts", 0) + 1
    target = ledger.get("target_build") or "?"
    ledger["status"] = "applying"
    ledger["attempts"] = attempts
    ledger["updated_at"] = _now_iso()
    ledger.setdefault("first_attempt_at", _now_iso())
    _write_ledger(install_dir, ledger)
    log.info("update-apply start: target=%s attempt=%s app_pid=%s", target, attempts, app_pid)

    # circuit breaker: never keep retrying the same failing target forever
    if attempts > MAX_ATTEMPTS:
        msg = f"gave up after {MAX_ATTEMPTS} attempts to update to {target}; reboot and retry"
        log.warning(msg)
        _finish_ledger(install_dir, "failed", msg)
        _unlink_quietly(new)
        _relaunch(exe, log)
        return {"ok": False, "error": msg}

    if _cancel_requested(install_dir):
        log.info("cancel requested before apply; aborting without relaunch")
        _finish_ledger(install_dir, "cancelled", None)
        _clear_cancel(install_dir)
        _unlink_quietly(new)
        return {"ok": False, "cancelled": True}

    if not new.exists():
        msg = "staged update file (.new) is missing; nothing to apply"
        log.warning(msg)
        _finish_ledger(install_dir, "failed", msg)
        _relaunch(exe, log)
        return {"ok": False, "error": msg}

    deadline = _monotonic() + _GLOBAL_DEADLINE_SECONDS
    _wait_for_pid_exit(app_pid, deadline, log)
    _kill_relay_pids(app_pid, install_dir, log)

    if _cancel_requested(install_dir):
        log.info("cancel requested during teardown; aborting without relaunch")
        _finish_ledger(install_dir, "cancelled", None)
        _clear_cancel(install_dir)
        _unlink_quietly(new)
        return {"ok": False, "cancelled": True}

    swapped, error = _swap_new_over_exe(exe, new, install_dir, deadline, log)
    if swapped:
        _cleanup_old(install_dir)
        _finish_ledger(install_dir, "success", None)
        log.info("update applied: now on %s; relaunching", target)
        _relaunch(exe, log)
        return {"ok": True}

    _unlink_quietly(new)
    _finish_ledger(install_dir, "failed", error)
    log.warning("swap failed (%s); relaunching current build so the relay stays up", error)
    _relaunch(exe, log)
    return {"ok": False, "error": error}
