"""CLI dispatch + the windowed-build console-reattach shim. The exe is built windowed (console=False) so
no console window pops for the tray app / detached serve; the shim's job is to keep CLI subcommands
printable and to never leave stdout/stderr as None (a windowed PyInstaller build can), which would crash
print()/logging."""

import sys

from ucnexus_relay import cli


def test_reattach_console_never_leaves_streams_none(monkeypatch):
    # the crash-safety net: a windowed build with no console leaves stdout/stderr None. Force the
    # non-win32 path so no real console API is touched, then prove the streams are backfilled + writable.
    monkeypatch.setattr(cli.sys, "platform", "linux")
    monkeypatch.setattr(cli.sys, "stdout", None)
    monkeypatch.setattr(cli.sys, "stderr", None)
    cli._reattach_console()
    assert cli.sys.stdout is not None
    assert cli.sys.stderr is not None
    cli.sys.stdout.write("")  # writable - does not raise
    cli.sys.stderr.write("")


def test_reattach_console_leaves_present_streams_untouched(monkeypatch):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    out, err = sys.stdout, sys.stderr
    cli._reattach_console()
    assert cli.sys.stdout is out
    assert cli.sys.stderr is err


def test_main_unknown_command_returns_2(monkeypatch):
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)  # don't touch the real console under pytest
    assert cli.main(["definitely-not-a-command"]) == 2


def test_main_dispatches_health(monkeypatch):
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)
    called = {}
    monkeypatch.setattr(cli, "_health", lambda rest: called.setdefault("rest", rest) or 0)
    assert cli.main(["health"]) == 0
    assert called["rest"] == []


def _fake_run_app(store):
    def _run(minimized=False, force=False):
        store["minimized"] = minimized
        store["force"] = force
        return 0

    return _run


def test_bare_invocation_defaults_to_app(monkeypatch):
    # single-file model: a double-clicked exe (no args) opens the desktop app, not headless serve.
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)
    from ucnexus_relay import app as app_mod

    called = {}
    monkeypatch.setattr(app_mod, "run_app", _fake_run_app(called))
    assert cli.main([]) == 0
    assert called["minimized"] is False


def test_flags_only_invocation_defaults_to_app_minimized(monkeypatch):
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)
    from ucnexus_relay import app as app_mod

    called = {}
    monkeypatch.setattr(app_mod, "run_app", _fake_run_app(called))
    assert cli.main(["--minimized"]) == 0
    assert called["minimized"] is True


def test_app_passes_force_through(monkeypatch):
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)
    from ucnexus_relay import app as app_mod

    called = {}
    monkeypatch.setattr(app_mod, "run_app", _fake_run_app(called))
    assert cli.main(["app", "--force"]) == 0
    assert called["force"] is True and called["minimized"] is False


def test_main_dispatches_print_build(monkeypatch, capfd):
    # capfd (fd-level), not capsys: print-build writes to fd 1 directly so it survives the windowed build's
    # devnull stdout when spawned over a pipe by promote's installed_build.
    monkeypatch.setattr(cli, "_reattach_console", lambda: None)
    from ucnexus_relay import updater

    monkeypatch.setattr(updater, "current_build", lambda: "relay-v0.1.0-build.7")
    assert cli.main(["print-build"]) == 0
    assert "relay-v0.1.0-build.7" in capfd.readouterr().out


def test_relay_already_serving_true(monkeypatch):
    import json
    import urllib.request

    class _Resp:
        def read(self):
            return json.dumps({"status": "ok"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert cli._relay_already_serving("127.0.0.1", 7321) is True


def test_relay_already_serving_false_when_unreachable(monkeypatch):
    import urllib.request

    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert cli._relay_already_serving("127.0.0.1", 7321) is False
