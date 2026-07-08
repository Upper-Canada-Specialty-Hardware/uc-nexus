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


def latest_release() -> dict:
    """The newest relay-v* release that carries the exe asset, from the public releases API. {} if none."""
    req = urllib.request.Request(_RELEASES_API, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=15) as r:  # noqa: S310 (fixed public GitHub API URL)
        releases = json.loads(r.read().decode())
    for rel in releases:  # the API returns releases newest-first
        tag = rel.get("tag_name", "")
        if not tag.startswith("relay-v"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == _ASSET_NAME), None)
        if asset and asset.get("browser_download_url"):
            return {"tag": tag, "url": asset["browser_download_url"], "published_at": rel.get("published_at")}
    return {}


def check_update() -> dict:
    cur = current_build()
    try:
        latest = latest_release()
    except OSError as e:
        return {"ok": False, "error": f"could not reach GitHub releases: {e}"}
    if not latest:
        return {"ok": False, "error": "no relay release with an exe asset was found"}
    return {
        "ok": True,
        "current": cur,
        "latest": latest["tag"],
        "update_available": latest["tag"] != cur,
        "url": latest["url"],
    }


def apply_update(url: str, install_dir: str | Path) -> dict:
    """Download `url` and swap it in for the installed exe, then restart serve (rename-while-running; see
    the module docstring)."""
    from . import setup

    install_dir = Path(install_dir)
    exe = install_dir / _ASSET_NAME
    new = install_dir / (_ASSET_NAME + ".new")
    old = install_dir / (_ASSET_NAME + ".old")

    try:
        urllib.request.urlretrieve(url, str(new))  # noqa: S310 (release asset URL from latest_release)
    except OSError as e:
        return {"ok": False, "error": f"download failed: {e}"}
    if new.stat().st_size < _MIN_EXE_BYTES:
        try:
            new.unlink()
        except OSError:
            pass
        return {"ok": False, "error": "the downloaded file is too small - aborting the swap"}

    # Stop serve so its lock on the exe is released. The ui process (this one) still holds the exe image,
    # which is why we rename rather than overwrite below.
    setup.stop_serve(install_dir)

    try:
        if old.exists():
            old.unlink()  # a stale .old from a prior update whose ui window has since closed
    except OSError:
        pass  # still locked by a running ui; os.replace below will surface a clear error if it conflicts
    try:
        os.replace(exe, old)  # rename the running exe aside (Windows permits renaming a running image)
        os.replace(new, exe)  # move the new exe into place
    except OSError as e:
        return {
            "ok": False,
            "error": f"swap failed ({e}); a previous update's file may still be in use - reboot and retry",
        }

    r = setup.start_serve(exe, install_dir)
    return {"ok": True, "restarted": bool(r.get("ok")), "note": "reopen this window to load the updated UI"}
