"""Single entry point for the packaged relay exe (and `python -m ucnexus_relay`).

Subcommands:
  app (default)        the desktop app: window + system tray, supervising the relay (--minimized = start in
                       tray; --force = take over from a running instance even if same/older/dev)
  serve                run the relay (headless) - uvicorn on the configured [server] host/port
  enroll  ...          one-time enrollment (delegates to ucnexus_relay.enroll; pass its flags through)
  protect-secret       DPAPI-encrypt the shared_secret currently in config.toml
  health               GET the local /health endpoint and print it (exit 0 if status ok)
  print-build          print this exe's build tag (used by promote to compare against the installed exe)
  update-apply --pid N the detached self-update helper: wait for app pid N to exit, swap the staged exe,
                       relaunch (spawned by updater.stage_update; not run by hand)
  install-autostart    register a no-admin logon autostart (HKCU Run) so the relay starts at logon
  uninstall-autostart  remove that logon autostart entry
  autostart-status     print whether the logon autostart is installed (JSON)

The packaged exe bundles all of these so a workstation needs only the .exe + config.toml (no Poetry).
"""

import os
import sys


def _reattach_console() -> None:
    """The exe is built windowed (console=False) so the tray app and the detached `serve` child never pop
    a console window. The cost of a windowed build is that a CLI subcommand run from a terminal would be
    silent, and PyInstaller leaves sys.stdout/stderr as None there, so a plain print() would crash. On
    Windows, attach to the launching terminal's console if there is one - there ISN'T for the tray app
    (launched from a shortcut) or the detached serve child, so those stay windowless - and guarantee
    stdout/stderr are always writable."""
    if sys.platform == "win32":
        try:
            import ctypes

            attach_parent = ctypes.c_uint(-1).value  # ATTACH_PARENT_PROCESS (DWORD (DWORD)-1)
            if ctypes.windll.kernel32.AttachConsole(attach_parent):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
                try:
                    sys.stdin = open("CONIN$", encoding="utf-8")  # noqa: SIM115
                except OSError:
                    pass
        except OSError:
            pass
    # a windowed PyInstaller build can leave these None; keep print()/logging from crashing if no console
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _relay_already_serving(host: str, port: int) -> bool:
    """True if a relay is already answering /health on host:port. A second serve would fail the port bind
    anyway, but the OLD flow wrote relay.pid before binding and deleted it on the way out - orphaning the
    first serve (the app could no longer stop/restart it). Bailing here before touching relay.pid avoids
    that."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as r:  # noqa: S310 (localhost)
            return json.loads(r.read().decode()).get("status") == "ok"
    except (OSError, json.JSONDecodeError):
        return False


def _serve(argv: list[str]) -> int:
    import asyncio
    import os

    import uvicorn

    from . import channel
    from .config import DEFAULT_CONFIG_PATH, get_settings
    from .main import app

    s = get_settings()

    # Single-instance: if a relay is already serving on this host/port, don't start a second one (and do NOT
    # touch relay.pid - see _relay_already_serving). The app's ensure_serve/restart already gate on /health;
    # this covers a stray manual `serve`, the scheduled-task deployment, and a double logon trigger.
    if _relay_already_serving(s.server.host, s.server.port):
        print(f"relay already serving on {s.server.host}:{s.server.port}; not starting a second one", file=sys.stderr)
        return 0

    # Write a pid file next to config.toml so the UI's Stop/Restart can target THIS serve process. The ui
    # window and serve are both ucnexus-relay.exe, so a pid file is the reliable way to tell them apart.
    pid_path = DEFAULT_CONFIG_PATH.parent / "relay.pid"
    try:
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pid_path = None
    # pin loop/http so the PyInstaller bundle stays lean and deterministic: stdlib asyncio + pure-python
    # h11. this avoids bundling httptools/uvloop and the by-string "auto" loaders picking a backend
    # that isn't packaged. throughput here is a few calls, so h11 is plenty. ws="none" disables
    # uvicorn's OWN inbound websocket server - the FastAPI app has no websocket routes, so that's
    # unused; it's unrelated to `channel`, which is an outbound `websockets` CLIENT run alongside this
    # server below (a `websockets` build IS bundled for that).
    config = uvicorn.Config(app, host=s.server.host, port=s.server.port, loop="asyncio", http="h11", ws="none")
    server = uvicorn.Server(config)

    async def _run() -> None:
        # the outbound channel is additive to the existing inbound HTTP server - a blank
        # [channel].backend_url makes channel.run_forever() a no-op, so this is safe on a relay that
        # hasn't been reconfigured for it yet.
        #
        # Skip the channel entirely when unenrolled (no secret): the backend refuses it pre-accept, so
        # running it would just spam secret-rejected retries. serve still binds the local HTTP server so
        # /health answers and the app shows "running"; enrolling + restarting serve brings the channel up.
        #
        # run_forever loops indefinitely (reconnect-with-backoff), so it must be cancelled on shutdown:
        # a plain gather() would keep awaiting it after uvicorn's server.serve() returns on SIGINT /
        # service stop, hanging the process. Run it as a task and cancel it once the server exits.
        channel_task = asyncio.create_task(channel.run_forever()) if s.auth.shared_secret else None
        try:
            await server.serve()
        finally:
            if channel_task is not None:
                channel_task.cancel()
                try:
                    await channel_task
                except asyncio.CancelledError:
                    pass

    try:
        asyncio.run(_run())
    finally:
        if pid_path is not None:
            try:
                pid_path.unlink()
            except OSError:
                pass
    return 0


def _health(argv: list[str]) -> int:
    import json
    import urllib.request

    from .config import get_settings

    s = get_settings()
    url = f"http://{s.server.host}:{s.server.port}/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 (fixed localhost URL)
            body = resp.read().decode()
    except OSError as e:
        print(f"health check failed: {e}", file=sys.stderr)
        return 1
    print(body)
    try:
        return 0 if json.loads(body).get("status") == "ok" else 1
    except json.JSONDecodeError:
        return 1


def _install_autostart(argv: list[str]) -> int:
    from .autostart import default_command, install_autostart

    if getattr(sys, "frozen", False):
        command = install_autostart()
    else:
        # a dev checkout would register python.exe, which isn't a relay - refuse unless the packaged exe.
        print(
            "install-autostart is for the packaged exe (sys.frozen). In a dev checkout the Run entry would "
            f"point at python, not the relay. default command would be: {default_command()}",
            file=sys.stderr,
        )
        return 1
    print(f"autostart installed (HKCU Run '{command}'); the relay will start at your next logon.")
    return 0


def _uninstall_autostart(argv: list[str]) -> int:
    from .autostart import uninstall_autostart

    existed = uninstall_autostart()
    print("autostart removed." if existed else "autostart was not installed (nothing to remove).")
    return 0


def _autostart_status(argv: list[str]) -> int:
    import json

    from .autostart import autostart_status

    print(json.dumps(autostart_status()))
    return 0


def main(argv: list[str] | None = None) -> int:
    _reattach_console()  # windowed build: attach to the launching terminal (if any) so CLI output shows
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-"):
        cmd, rest = argv[0], argv[1:]
    else:
        # bare invocation (a double-clicked exe) opens the desktop app. The serve child (setup.start_serve)
        # and the autostart entries pass an explicit command, so only a bare double-click is affected.
        cmd, rest = "app", argv

    if cmd == "serve":
        return _serve(rest)
    if cmd == "app":
        from .app import run_app
        return run_app(minimized="--minimized" in rest, force="--force" in rest)
    if cmd == "print-build":
        from .updater import current_build

        # Write to fd 1 directly, NOT print(): the windowed build's _reattach_console rebinds sys.stdout to
        # devnull when there's no console, which is exactly how promote's `installed_build` spawns us
        # (detached, no window, output over a pipe). os.write(1) reaches that captured pipe regardless.
        data = (current_build() + "\n").encode("utf-8")
        try:
            os.write(1, data)
        except OSError:
            sys.stdout.write(data.decode("utf-8"))
        return 0
    if cmd == "update-apply":
        # the detached self-update helper (spawned by updater.stage_update). Windowless, logged to
        # update.log, bounded by a deadline + attempt ledger. --pid is the app process to wait for.
        from .config import DEFAULT_CONFIG_PATH
        from .updater import apply_staged_update

        app_pid = None
        if "--pid" in rest:
            i = rest.index("--pid")
            if i + 1 < len(rest):
                try:
                    app_pid = int(rest[i + 1])
                except ValueError:
                    app_pid = None
        apply_staged_update(app_pid, DEFAULT_CONFIG_PATH.parent)
        return 0
    if cmd == "enroll":
        from .enroll import main as enroll_main
        return enroll_main(rest)
    if cmd == "protect-secret":
        from .protect_secret import main as protect_main
        return protect_main(rest)
    if cmd == "health":
        return _health(rest)
    if cmd == "install-autostart":
        return _install_autostart(rest)
    if cmd == "uninstall-autostart":
        return _uninstall_autostart(rest)
    if cmd == "autostart-status":
        return _autostart_status(rest)

    print(
        f"unknown command: {cmd!r} (expected: serve | app | enroll | protect-secret | health | print-build | "
        "update-apply | install-autostart | uninstall-autostart | autostart-status)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
