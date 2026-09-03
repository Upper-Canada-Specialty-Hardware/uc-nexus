"""The backend's root log configuration. Without it every logger.info() under app.* is swallowed by
Python's last-resort handler (WARNING and above only), which is how a fifteen-hour GP backfill ran in
production without writing a line.

The root logger already carries pytest's own handlers, so basicConfig no-ops here by design (that is
the same guard that protects a TestClient import). These tests therefore hand _configure_logging a
clean root and check what it does with it."""

import logging
import sys

import main


def _clean_root(monkeypatch):
    """A root logger with no handlers, restored after the test - basicConfig only acts on one."""
    monkeypatch.setattr(logging.root, "handlers", [])
    monkeypatch.setattr(logging.root, "level", logging.WARNING)


def _stdout_handlers():
    return [h for h in logging.root.handlers if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout]


def test_logging_is_configured_to_stdout_at_info(monkeypatch):
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    _clean_root(monkeypatch)

    main._configure_logging()

    assert _stdout_handlers()
    assert logging.root.level == logging.INFO
    # The level is what actually matters: an INFO record from a service logger must survive.
    assert logging.getLogger("app.services.gp_po_sync").isEnabledFor(logging.INFO)


def test_log_level_env_overrides_the_default(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    _clean_root(monkeypatch)

    main._configure_logging()

    assert logging.root.level == logging.DEBUG


def test_an_unknown_log_level_falls_back_to_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    _clean_root(monkeypatch)

    main._configure_logging()

    assert logging.root.level == logging.INFO


def test_an_already_configured_root_is_left_alone(monkeypatch):
    """The pytest / TestClient case: handlers already installed, so basicConfig must not add another."""
    existing = logging.StreamHandler(sys.stderr)
    monkeypatch.setattr(logging.root, "handlers", [existing])
    monkeypatch.setattr(logging.root, "level", logging.WARNING)

    main._configure_logging()

    assert logging.root.handlers == [existing]
    assert logging.root.level == logging.WARNING
