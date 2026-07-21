"""User-level (no-admin) autostart via the HKCU Run key.

A workstation user is not necessarily a local admin (e.g. jayp on TAGGING3W10 is not), so the relay
can't rely on the admin-only Scheduled Task to launch at logon. Writing
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run needs no elevation and launches the exe at
logon as that user - which is exactly the account the relay must run as (SSPI to GP, DPAPI CurrentUser
secret). The admin Scheduled Task script is kept for IT/fleet installs ("support both"); this Run-key
path is the default for self-service setup and is what the guided-setup UI calls.

Registry ops take an overridable `subkey` so the unit tests can exercise the real winreg calls against a
throwaway HKCU key instead of the live Run key.
"""

import sys

try:
    import winreg  # Windows-only; the relay only ever runs on Windows workstations
except ImportError:  # pragma: no cover - importing on a non-Windows dev machine
    winreg = None

RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "UC Nexus Relay"


def _require_winreg() -> None:
    if winreg is None:
        raise RuntimeError("autostart requires Windows (winreg is unavailable)")


def default_command() -> str:
    """The command the Run entry launches at logon: the packaged app, started minimized to the tray. For an
    onedir install it targets the STABLE `current` junction path, so a version update (which only repoints
    the junction) needs no autostart change; it falls back to sys.executable for a dev run. Quoted so a
    path with spaces survives."""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        try:
            from . import layout
            from .config import DEFAULT_CONFIG_PATH

            cur = layout.current_link(DEFAULT_CONFIG_PATH.parent) / layout.ASSET_NAME
            if cur.exists():
                exe = str(cur)
        except Exception:  # noqa: BLE001 - fall back to sys.executable if the layout can't be resolved
            pass
    return f'"{exe}" app --minimized'


def install_autostart(command: str | None = None, subkey: str = RUN_SUBKEY) -> str:
    """Register (or overwrite) the logon Run entry. Returns the command that was written. No admin needed."""
    _require_winreg()
    command = command or default_command()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    return command


def uninstall_autostart(subkey: str = RUN_SUBKEY) -> bool:
    """Remove the Run entry. Returns True if it existed, False if there was nothing to remove."""
    _require_winreg()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False


def autostart_status(subkey: str = RUN_SUBKEY) -> dict:
    """Whether the logon Run entry is present, and the command it launches."""
    _require_winreg()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
        return {"installed": True, "command": value}
    except FileNotFoundError:
        return {"installed": False, "command": None}
