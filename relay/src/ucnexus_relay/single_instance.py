"""Single-instance ownership for the desktop `app` process.

The relay's top-level user-launched process is always `app` (double-click / shortcut / autostart); `serve`
is only ever its child. Nothing stopped a second `app` from opening a second window + tray icon over the
same serve. This module makes `app` single-instance and version-aware:

  - the running owner writes app.lock (next to config.toml) with its pid, build, and a loopback control
    port + nonce, and runs a tiny 127.0.0.1 control server (ping / show / quit_for_upgrade);
  - a newcomer reads app.lock, pings the owner, and either focuses it, evicts + replaces it (a newer
    build), or defers to it (older / dev), per decide_action();
  - a session-local named mutex serialises two simultaneous cold starts so exactly one becomes owner.

The installed exe is resolved through the onedir `current` junction (see layout.installed_exe); updates
swap versions by repointing that junction (see updater), not by copying an exe, so there is no
promote-from-Downloads path here anymore.

Everything is import-safe without a GUI backend - app.py wires the show / quit callbacks to the window -
so the decision logic and the lockfile plumbing unit-test without opening a window.
"""

import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import layout, updater
from .logging_setup import get_logger

logger = get_logger()

LOCKFILE_NAME = "app.lock"
MUTEX_NAME = "Local\\UCNexusRelay.App"
ASSET_NAME = "ucnexus-relay.exe"
WINDOW_TITLE = "UC Nexus Relay"
_PING_TIMEOUT = 2.0

_DETACHED = 0x00000008  # DETACHED_PROCESS
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


# --- build comparison ---------------------------------------------------------------------------------


def current_build() -> str:
    return updater.current_build()


def new_nonce() -> str:
    return secrets.token_hex(16)


def build_is_newer(candidate: str, other: str) -> bool:
    """True if `candidate` is a strictly higher build than `other`. 'dev' is build -1 (updater.build_number),
    so a dev build is never newer than a real one - only --force overrides that (see decide_action)."""
    return updater.build_number(candidate) > updater.build_number(other)


def decide_action(new_build: str, running_build: str, force: bool = False) -> str:
    """What a newcomer should do about a LIVE owner: 'replace' (evict + take over) or 'focus' (surface the
    owner's window and exit). Newer -> replace; same / older / dev -> focus; --force always replaces."""
    if force:
        return "replace"
    return "replace" if build_is_newer(new_build, running_build) else "focus"


# --- lockfile -----------------------------------------------------------------------------------------


def lockfile_path(config_dir) -> Path:
    return Path(config_dir) / LOCKFILE_NAME


def read_lock(config_dir) -> dict | None:
    """Parse app.lock, or None if it's missing / unreadable / corrupt. Liveness is a separate ping (a lock
    can outlive the process that wrote it if the app was killed) - see live_owner()."""
    try:
        return json.loads(lockfile_path(config_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_lock(config_dir, *, pid: int, build: str, exe_path: str, control_port: int, nonce: str) -> None:
    p = lockfile_path(config_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"pid": pid, "build": build, "exe_path": exe_path, "control_port": control_port, "nonce": nonce}),
        encoding="utf-8",
    )


def clear_lock(config_dir) -> None:
    try:
        lockfile_path(config_dir).unlink()
    except OSError:
        pass


# --- loopback control channel -------------------------------------------------------------------------


def _recv_line(conn) -> bytes:
    buf = bytearray()
    while b"\n" not in buf:
        try:
            chunk = conn.recv(4096)
        except OSError:
            break
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > 65536:  # a command line is tiny; cap to avoid an unbounded read
            break
    return bytes(buf)


class ControlServer:
    """The 127.0.0.1 line-JSON control server the owning app runs. Every command must carry the lock's
    nonce (so only a local process that can read app.lock can drive it). Commands:
      ping             -> {ok, build, pid}
      show             -> on_show()  (surface the window)
      quit_for_upgrade -> ok, then on_quit() off-thread (tear down for a newer instance's handoff)."""

    def __init__(self, *, build: str, nonce: str, on_show, on_quit) -> None:
        self._build = build
        self._nonce = nonce
        self._on_show = on_show
        self._on_quit = on_quit
        self._sock: socket.socket | None = None
        self._port = 0
        self._stop = False

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))  # ephemeral port; recorded in app.lock so the newcomer can find us
        s.listen(8)
        self._sock = s
        self._port = s.getsockname()[1]
        threading.Thread(target=self._accept_loop, name="relay-ctl", daemon=True).start()
        return self._port

    def stop(self) -> None:
        self._stop = True
        try:
            if self._sock is not None:
                self._sock.close()
        except OSError:
            pass

    def _accept_loop(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return  # socket closed by stop()
            try:
                self._handle(conn)
            except Exception:
                logger.exception("relay control connection failed")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self, conn) -> None:
        conn.settimeout(3.0)
        try:
            req = json.loads(_recv_line(conn).decode("utf-8").strip() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reply(conn, {"ok": False, "error": "bad request"})
            return
        if req.get("nonce") != self._nonce:
            self._reply(conn, {"ok": False, "error": "bad nonce"})
            return
        cmd = req.get("cmd")
        if cmd == "ping":
            self._reply(conn, {"ok": True, "build": self._build, "pid": os.getpid()})
        elif cmd == "show":
            self._reply(conn, {"ok": True})
            self._safe(self._on_show)
        elif cmd == "quit_for_upgrade":
            self._reply(conn, {"ok": True})
            # run teardown off the accept thread so the reply flushes before the window is destroyed
            threading.Thread(target=lambda: self._safe(self._on_quit), name="relay-quit", daemon=True).start()
        else:
            self._reply(conn, {"ok": False, "error": f"unknown cmd {cmd!r}"})

    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:
            logger.exception("relay control handler failed")

    @staticmethod
    def _reply(conn, obj: dict) -> None:
        try:
            conn.sendall((json.dumps(obj) + "\n").encode("utf-8"))
        except OSError:
            pass


def _send(port, nonce: str, cmd: str, timeout: float = _PING_TIMEOUT) -> dict | None:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout) as conn:
            conn.settimeout(timeout)
            conn.sendall((json.dumps({"cmd": cmd, "nonce": nonce}) + "\n").encode("utf-8"))
            raw = _recv_line(conn)
        return json.loads(raw.decode("utf-8").strip() or "{}")
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def send_show(port, nonce) -> bool:
    r = _send(port, nonce, "show")
    return bool(r and r.get("ok"))


def send_quit(port, nonce) -> bool:
    r = _send(port, nonce, "quit_for_upgrade")
    return bool(r and r.get("ok"))


def live_owner(config_dir) -> dict | None:
    """If app.lock points at an owner that answers ping, return {port, nonce, build, pid}; else None. The
    ping (not the pid) is the authoritative liveness test, so a stale lock from a killed app reads as None."""
    lock = read_lock(config_dir)
    if not lock:
        return None
    port, nonce = lock.get("control_port"), lock.get("nonce")
    if not port or not nonce:
        return None
    pong = _send(port, nonce, "ping")
    if not (pong and pong.get("ok")):
        return None
    return {
        "port": port,
        "nonce": nonce,
        "build": pong.get("build") or lock.get("build") or "dev",
        "pid": pong.get("pid") or lock.get("pid"),
    }


def wait_for_release(config_dir, timeout: float = 15.0) -> bool:
    """Poll until app.lock has no live owner (the evicted owner exited + freed its exe lock)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if live_owner(config_dir) is None:
            return True
        time.sleep(0.3)
    return live_owner(config_dir) is None


def wait_for_owner(config_dir, timeout: float = 5.0) -> dict | None:
    """Poll until a live owner appears - used when we lost the cold-start mutex race and the winner's
    control server hasn't come up yet. None on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        owner = live_owner(config_dir)
        if owner is not None:
            return owner
        time.sleep(0.2)
    return live_owner(config_dir)


def force_kill_pid(pid) -> None:
    """Last-resort taskkill BY PID (never by image name - that would also kill us, same exe). Used only if a
    graceful quit_for_upgrade didn't release the owner in time."""
    if not pid:
        return
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"], capture_output=True, text=True)  # noqa: S607
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def evict(owner: dict, config_dir) -> bool:
    """Ask a live owner to quit for a handoff and wait for it to release. Graceful first (quit_for_upgrade);
    force-kill its pid only if that times out. True once no live owner remains."""
    send_quit(owner["port"], owner["nonce"])
    if wait_for_release(config_dir):
        return True
    logger.warning("relay owner didn't quit gracefully; force-killing pid %s", owner.get("pid"))
    force_kill_pid(owner.get("pid"))
    return wait_for_release(config_dir, timeout=5.0)


# --- session-local named mutex (Windows) --------------------------------------------------------------


class MutexResult:
    def __init__(self, handle, acquired: bool) -> None:
        self.handle = handle
        self.acquired = acquired  # True if WE created it first (it didn't already exist)


def acquire_mutex(name: str = MUTEX_NAME) -> MutexResult:
    """Create the session-local named mutex. `acquired` is False when the mutex already existed (another app
    is starting / running). Off Windows (or if creation fails) `acquired` is True - the lockfile + ping
    still serialise; the mutex only tightens the two-simultaneous-cold-start race."""
    if sys.platform != "win32":
        return MutexResult(None, True)
    import ctypes

    kernel32 = ctypes.windll.kernel32
    error_already_exists = 183
    handle = kernel32.CreateMutexW(None, True, name)
    existed = kernel32.GetLastError() == error_already_exists
    if not handle:
        return MutexResult(None, True)
    return MutexResult(handle, not existed)


def release_mutex(result: MutexResult | None) -> None:
    if result is None or result.handle is None or sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.kernel32.ReleaseMutex(result.handle)
        ctypes.windll.kernel32.CloseHandle(result.handle)
    except OSError:
        pass


# --- Win32 window activation --------------------------------------------------------------------------


def allow_foreground(pid) -> None:
    """Grant `pid` permission to steal foreground, so the owner's SetForegroundWindow actually raises the
    window instead of just flashing the taskbar (Windows blocks a non-foreground process from doing that)."""
    if sys.platform != "win32" or not pid:
        return
    import ctypes

    try:
        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except (OSError, ValueError):
        pass


def bring_to_front(title: str = WINDOW_TITLE) -> bool:
    """Restore + foreground the window with this title. The owner calls this for its OWN window on `show`,
    after the newcomer granted it foreground rights via allow_foreground()."""
    if sys.platform != "win32":
        return False
    import ctypes

    user32 = ctypes.windll.user32
    sw_restore = 9
    hwnd = user32.FindWindowW(None, title)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, sw_restore)
    return bool(user32.SetForegroundWindow(hwnd))


# --- promote-to-installed -----------------------------------------------------------------------------


def installed_exe_path(config_dir) -> Path:
    """The exe to run/inspect for this install - resolved through the onedir `current` junction to the
    active app-<build>/ version (see layout.installed_exe)."""
    return layout.installed_exe(config_dir)


def same_path(a, b) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return str(a).lower() == str(b).lower()


def installed_build(config_dir, timeout: float = 8.0) -> str | None:
    """The build of the installed exe, read by running `<installed> print-build`. None if there's no
    installed exe or it didn't answer (the caller treats None as 'promote' - a fresh install)."""
    exe = installed_exe_path(config_dir)
    if not exe.exists():
        return None
    try:
        out = subprocess.run(
            [str(exe), "print-build"], capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout or "").strip() or None


def launch_installed(config_dir, minimized: bool = False) -> int | None:
    """Spawn the installed exe (via the `current` junction) as the desktop app, detached so it outlives
    this process. The relaunched exe runs the single-instance gate itself and becomes the owner.
    Autostart + shortcuts target the stable `current` path, so a version change needs no refresh here.
    Returns the launched app's pid so a caller (the updater's health-gated retry) can force it down BY PID
    if it comes up unhealthy - onedir, so the exe process IS the app process (no bootloader child)."""
    exe = installed_exe_path(config_dir)
    args = [str(exe), "app"] + (["--minimized"] if minimized else [])
    proc = subprocess.Popen(  # noqa: S603 (our own installed exe path)
        args,
        cwd=str(config_dir),
        creationflags=_DETACHED,  # DETACHED alone (GUI exe: no console either way; not paired with NO_WINDOW)
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid
