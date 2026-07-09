"""Self-update from the public GitHub releases - the relay UI's third purpose (setup, updates, logs).

The repo is public, so the relay checks the releases API and downloads the exe with no auth token and no
backend involvement. Applying an update on Windows is the tricky part: a running exe is locked and can't
be overwritten, but it CAN be renamed. So we download the new exe, rename the current one aside, drop the
new one into its place, and restart serve. The ui process keeps running from the renamed file; reopening
the window loads the new UI.

The build identity comes from _build.py, which CI stamps into the package at build time (see
.github/workflows/relay-release.yml). A dev checkout has no _build.py, so current_build() is 'dev', which
compares unequal to any release tag (always "behind")."""

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

REPO = "Upper-Canada-Specialty-Hardware/uc-nexus"
_RELEASES_API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
_ASSET_NAME = "ucnexus-relay.exe"
_MIN_EXE_BYTES = 5_000_000  # a real exe is ~20MB; guard against a truncated body / HTML error page


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
    (rename-while-running; see the module docstring)."""
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


# A running exe can't reliably be renamed/overwritten in place, so the desktop app updates by exiting
# first: this helper waits for the app process (pid) to be gone, then moves the downloaded .new over the
# now-unlocked exe and relaunches it, retrying the move while any bootloader child is still releasing the
# image. It deletes itself at the end.
_HELPER_BAT = r"""@echo off
:waitapp
tasklist /fi "PID eq {pid}" /nh 2>nul | find /i "ucnexus-relay" >nul
if not errorlevel 1 (
  timeout /t 1 /nobreak >nul
  goto waitapp
)
set _n=0
:swap
move /y "{new}" "{exe}" >nul 2>&1
if not errorlevel 1 goto relaunch
set /a _n+=1
if %_n% geq 30 goto done
timeout /t 1 /nobreak >nul
goto swap
:relaunch
start "" "{exe}" app
:done
del "%~f0"
"""


def stage_update(url: str, install_dir: str | Path, app_pid: int) -> dict:
    """Download the new exe and spawn a detached helper that waits for `app_pid` to exit, swaps the exe
    (unlocked once the app is gone), and relaunches the app. The caller MUST then shut the app down so the
    helper can proceed - this is the desktop-app update path that avoids renaming a still-running exe."""
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

    helper = install_dir / "update-helper.bat"
    helper.write_text(_HELPER_BAT.format(pid=int(app_pid), new=str(new), exe=str(exe)), encoding="utf-8")
    detached = 0x00000008  # DETACHED_PROCESS
    no_window = 0x08000000  # CREATE_NO_WINDOW
    subprocess.Popen(  # noqa: S603 (fixed cmd + our own helper path)
        ["cmd", "/c", str(helper)],
        cwd=str(install_dir),
        creationflags=detached | no_window,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return {"ok": True, "note": "the relay will close and reopen on the new version"}
