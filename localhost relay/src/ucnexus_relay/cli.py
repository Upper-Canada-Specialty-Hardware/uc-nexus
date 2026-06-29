"""Single entry point for the packaged relay exe (and `python -m ucnexus_relay`).

Subcommands:
  serve (default)   run the relay - uvicorn on the configured [server] host/port
  enroll  ...       one-time enrollment (delegates to ucnexus_relay.enroll; pass its flags through)
  protect-secret    DPAPI-encrypt the shared_secret currently in config.toml
  health            GET the local /health endpoint and print it (exit 0 if status ok)

The packaged exe bundles all of these so a workstation needs only the .exe + config.toml (no Poetry).
"""

import sys


def _serve(argv: list[str]) -> int:
    import uvicorn

    from .config import get_settings
    from .main import app

    s = get_settings()
    # pin loop/http/ws so the PyInstaller bundle stays lean and deterministic: stdlib asyncio + pure-python
    # h11, no websockets (the relay has none). this avoids bundling httptools/websockets/uvloop and the
    # by-string "auto" loaders picking a backend that isn't packaged. throughput here is a few calls, so
    # h11 is plenty.
    uvicorn.run(app, host=s.server.host, port=s.server.port, loop="asyncio", http="h11", ws="none")
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


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and not argv[0].startswith("-"):
        cmd, rest = argv[0], argv[1:]
    else:
        cmd, rest = "serve", argv  # bare invocation (or only flags) defaults to serving

    if cmd == "serve":
        return _serve(rest)
    if cmd == "enroll":
        from .enroll import main as enroll_main
        return enroll_main(rest)
    if cmd == "protect-secret":
        from .protect_secret import main as protect_main
        return protect_main(rest)
    if cmd == "health":
        return _health(rest)

    print(f"unknown command: {cmd!r} (expected: serve | enroll | protect-secret | health)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
