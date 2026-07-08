"""Single entry point for the packaged relay exe (and `python -m ucnexus_relay`).

Subcommands:
  serve (default)      run the relay - uvicorn on the configured [server] host/port
  ui                   open the native desktop window (status + event log; setup/updates land here)
  enroll  ...          one-time enrollment (delegates to ucnexus_relay.enroll; pass its flags through)
  protect-secret       DPAPI-encrypt the shared_secret currently in config.toml
  health               GET the local /health endpoint and print it (exit 0 if status ok)
  install-autostart    register a no-admin logon autostart (HKCU Run) so the relay starts at logon
  uninstall-autostart  remove that logon autostart entry
  autostart-status     print whether the logon autostart is installed (JSON)

The packaged exe bundles all of these so a workstation needs only the .exe + config.toml (no Poetry).
"""

import sys


def _serve(argv: list[str]) -> int:
    import asyncio
    import os

    import uvicorn

    from . import channel
    from .config import DEFAULT_CONFIG_PATH, get_settings
    from .main import app

    s = get_settings()

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
        # run_forever loops indefinitely (reconnect-with-backoff), so it must be cancelled on shutdown:
        # a plain gather() would keep awaiting it after uvicorn's server.serve() returns on SIGINT /
        # service stop, hanging the process. Run it as a task and cancel it once the server exits.
        channel_task = asyncio.create_task(channel.run_forever())
        try:
            await server.serve()
        finally:
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
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-"):
        cmd, rest = argv[0], argv[1:]
    else:
        cmd, rest = "serve", argv  # bare invocation (or only flags) defaults to serving

    if cmd == "serve":
        return _serve(rest)
    if cmd == "ui":
        from .ui import run_ui
        return run_ui()
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
        f"unknown command: {cmd!r} (expected: serve | ui | enroll | protect-secret | health | "
        "install-autostart | uninstall-autostart | autostart-status)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
