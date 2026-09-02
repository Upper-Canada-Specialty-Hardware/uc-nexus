"""Environment overrides on config loading, and the stdout-only log file they turn on.

These exist for a run with no config.toml to write and no DPAPI to decrypt with - a dev checkout
pointed at a test backend. get_settings is @lru_cache-d, so every test clears the cache around itself.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from ucnexus_relay import logging_setup
from ucnexus_relay.config import PRODUCTION_BACKEND_URL, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_config_plus_env_is_a_complete_relay(tmp_path, monkeypatch):
    """No file at all, everything from the environment."""
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "env-secret")
    monkeypatch.setenv("UCNEXUS_RELAY_BACKEND_URL", "wss://backend-pr-999.up.railway.app/relay-link")
    monkeypatch.setenv("UCNEXUS_RELAY_LOG_FILE", "-")

    s = get_settings(str(tmp_path / "does-not-exist" / "config.toml"))

    assert s.auth.shared_secret == "env-secret"
    assert s.channel.backend_url == "wss://backend-pr-999.up.railway.app/relay-link"
    assert s.logging.file == "-"
    # No company variable: the served set is discovered from GP's own company master (companies.py).


def test_defaults_are_unchanged_without_the_env(tmp_path):
    s = get_settings(str(tmp_path / "nothing" / "config.toml"))
    assert s.channel.backend_url == PRODUCTION_BACKEND_URL
    assert s.logging.file == "relay.log"


def test_env_wins_over_the_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "from-the-file"\n', encoding="utf-8")
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "from-the-env")
    monkeypatch.setenv("UCNEXUS_RELAY_BACKEND_URL", "wss://backend-pr-999.up.railway.app/relay-link")
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == "from-the-env"
    assert s.channel.backend_url == "wss://backend-pr-999.up.railway.app/relay-link"


def test_env_secret_is_taken_verbatim_and_never_decrypted(tmp_path, monkeypatch):
    """A config.toml copied off the workstation holds a DPAPI blob this machine cannot decrypt. The
    environment secret replaces it BEFORE the decrypt, so loading never touches DPAPI."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "enc:dpapi:bm90LWEtcmVhbC1ibG9i"\n', encoding="utf-8")
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "plaintext-from-env")
    assert get_settings(str(cfg)).auth.shared_secret == "plaintext-from-env"


def test_stdout_only_log_file_writes_no_relay_log(tmp_path, monkeypatch):
    monkeypatch.setattr(logging_setup, "_CONFIGURED", False)
    monkeypatch.chdir(tmp_path)
    root = logging.getLogger()
    before = set(root.handlers)
    try:
        logging_setup.configure_logging("INFO", logging_setup.STDOUT_ONLY)
        added = [h for h in root.handlers if h not in before]
        assert added, "a stream handler is still configured"
        assert not [h for h in added if isinstance(h, RotatingFileHandler)]
        assert list(tmp_path.iterdir()) == []
    finally:
        for h in [h for h in root.handlers if h not in before]:
            root.removeHandler(h)
            h.close()
