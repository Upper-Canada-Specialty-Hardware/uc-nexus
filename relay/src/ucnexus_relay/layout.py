"""Onedir install layout: versioned app-<build>/ folders under the data dir, fronted by a stable `current`
directory junction that shortcuts + autostart target.

Why: the relay ships as a PyInstaller ONEDIR bundle (exe + _internal/ with the C-extension .pyd as
permanent files - see ucnexus-relay.spec). A running relay holds its _internal/*.pyd open, so its folder
can't be renamed/overwritten in place, and a self-update can't run its helper from the folder it is
replacing. So each version lives in its own `app-<build>/` folder and `current` is a junction pointing at
the active one. An update extracts the new version alongside, repoints the junction, and relaunches - no
rename or copy of a running folder. Repointing a junction is safe while the old relay runs: its open .pyd
handles resolved the old real path at launch and are unaffected by swapping the reparse point.

Data (config.toml, relay.log, relay.pid, app.lock, update-state.json, update.log) lives in the data dir
itself, NOT in a version folder, so it survives updates. config._default_config_path is LOCALAPPDATA-based
(not exe-relative), so config resolves to the data dir regardless of which version is current.
"""

import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

ASSET_NAME = "ucnexus-relay.exe"  # the exe name inside a version folder
CURRENT_LINK = "current"
VERSION_PREFIX = "app-"
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def current_link(data_dir) -> Path:
    return Path(data_dir) / CURRENT_LINK


def version_dir_name(build: str) -> str:
    """The folder name for a build tag: app-<sanitized-build>, e.g. app-relay-v0.1.0-build.27."""
    return VERSION_PREFIX + (_SAFE.sub("-", build) if build else "staged")


def version_dir(data_dir, build: str) -> Path:
    return Path(data_dir) / version_dir_name(build)


def _build_number(name: str) -> int:
    m = re.search(r"build\.(\d+)$", name or "")
    return int(m.group(1)) if m else -1


def newest_version_dir(data_dir) -> Path | None:
    """The app-*/ version folder with the highest build number that actually contains the exe, or None."""
    candidates = [p for p in Path(data_dir).glob(VERSION_PREFIX + "*") if (p / ASSET_NAME).exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: _build_number(p.name))


def installed_exe(data_dir) -> Path:
    """The exe to run/inspect: via the `current` junction if it resolves, else the newest app-*/ version,
    else the legacy flat data_dir/ucnexus-relay.exe (a onefile install / dev checkout)."""
    data_dir = Path(data_dir)
    link_exe = current_link(data_dir) / ASSET_NAME
    if link_exe.exists():
        return link_exe
    newest = newest_version_dir(data_dir)
    if newest is not None:
        return newest / ASSET_NAME
    return data_dir / ASSET_NAME  # legacy flat layout (pre-onedir)


def running_version_dir() -> Path | None:
    """The version folder the CURRENT process runs from (resolving the `current` junction to its real
    target), or None outside a frozen onedir. Used to keep the running version during cleanup."""
    import sys

    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve().parent
    except OSError:
        return Path(sys.executable).parent


def remove_junction(link) -> None:
    """Remove the `current` junction (a directory reparse point) without touching its target. A no-op if
    it's absent. os.rmdir on a junction deletes only the reparse point; on a real non-empty dir it fails,
    which is the safe outcome (we never want to delete a real folder here)."""
    try:
        os.rmdir(Path(link))
    except OSError:
        pass


def repoint_current(data_dir, target_version_dir) -> bool:
    """Point data_dir/current at target_version_dir (create or repoint the junction). No admin needed
    (mklink /J). Returns True on success. Safe while the old relay runs - see the module docstring."""
    link = current_link(data_dir)
    remove_junction(link)
    result = subprocess.run(  # noqa: S603,S607 (fixed cmd + our own paths)
        ["cmd", "/c", "mklink", "/J", str(link), str(target_version_dir)],
        creationflags=_NO_WINDOW,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def extract_zip(zip_path, dest_dir) -> Path:
    """Extract a onedir zip (ucnexus-relay.exe + _internal/ at its root) into dest_dir, replacing any
    existing contents. Returns dest_dir."""
    dest = Path(dest_dir)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    return dest


def cleanup_old_versions(data_dir, keep) -> None:
    """Delete every app-*/ version folder except the ones named in `keep` (folder names). Best-effort: a
    folder still held open by an exiting helper is skipped and cleaned on a later pass."""
    keep_names = {Path(k).name for k in keep}
    for p in Path(data_dir).glob(VERSION_PREFIX + "*"):
        if p.is_dir() and p.name not in keep_names:
            shutil.rmtree(p, ignore_errors=True)
