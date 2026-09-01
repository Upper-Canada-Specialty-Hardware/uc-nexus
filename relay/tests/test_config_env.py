"""Environment overrides on config loading, and the stdout-only log file they turn on.

These exist for the containerised relay: it has no config.toml to write and no DPAPI to decrypt with,
so everything it needs has to be expressible as an environment variable. get_settings is @lru_cache-d,
so every test clears the cache around itself.
"""

import logging
from logging.handlers import RotatingFileHandler

import pytest

from ucnexus_relay import logging_setup
from ucnexus_relay.config import DEFAULT_FIXTURE_PATH, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_missing_config_plus_env_is_a_complete_relay(tmp_path, monkeypatch):
    """The container's whole configuration: no file at all, everything from the environment."""
    monkeypatch.setenv("UCNEXUS_RELAY_MODE", "fixture")
    monkeypatch.setenv("UCNEXUS_RELAY_FIXTURE_PATH", "/app/fixtures/gp-snapshot.json")
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "container-secret")
    monkeypatch.setenv("UCNEXUS_RELAY_BACKEND_URL", "wss://backend-pr-999.up.railway.app/relay-link")
    monkeypatch.setenv("UCNEXUS_RELAY_COMPANIES", "TUCSH, TUBC")
    monkeypatch.setenv("UCNEXUS_RELAY_LOG_FILE", "-")

    s = get_settings(str(tmp_path / "does-not-exist" / "config.toml"))

    assert s.gp.mode == "fixture"
    assert s.gp.fixture_path == "/app/fixtures/gp-snapshot.json"
    assert s.auth.shared_secret == "container-secret"
    assert s.channel.backend_url == "wss://backend-pr-999.up.railway.app/relay-link"
    # first entry of the list is the default company, and the whole list is what's allowed
    assert s.gp.allowed_companies == ["TUCSH", "TUBC"]
    assert s.gp.default_company == "TUCSH"
    assert s.logging.file == "-"


def test_defaults_are_unchanged_without_the_env(tmp_path):
    s = get_settings(str(tmp_path / "nothing" / "config.toml"))
    assert s.gp.mode == "sql"
    assert s.gp.fixture_path is None
    assert s.gp.allowed_companies == ["TUBC"]
    assert s.logging.file == "relay.log"


def test_env_wins_over_the_file(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[auth]\nshared_secret = "from-the-file"\n\n[gp]\nallowed_companies = ["UBC"]\ndefault_company = "UBC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "from-the-env")
    monkeypatch.setenv("UCNEXUS_RELAY_COMPANIES", "TUBC")
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == "from-the-env"
    assert s.gp.allowed_companies == ["TUBC"]


def test_env_secret_is_taken_verbatim_and_never_decrypted(tmp_path, monkeypatch):
    """An enrolled config.toml carried into a Linux image holds a DPAPI blob that cannot be decrypted
    there. The environment secret replaces it BEFORE the decrypt, so loading never touches DPAPI."""
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "enc:dpapi:bm90LWEtcmVhbC1ibG9i"\n', encoding="utf-8")
    monkeypatch.setenv("UCNEXUS_RELAY_SHARED_SECRET", "plaintext-from-env")
    assert get_settings(str(cfg)).auth.shared_secret == "plaintext-from-env"


def test_blank_companies_list_is_ignored(tmp_path, monkeypatch):
    # An empty variable must not leave the relay allowed to serve nothing at all.
    monkeypatch.setenv("UCNEXUS_RELAY_COMPANIES", " , ")
    s = get_settings(str(tmp_path / "config.toml"))
    assert s.gp.allowed_companies == ["TUBC"]


def test_bundled_fixture_path_resolves_to_the_checked_in_snapshot():
    assert DEFAULT_FIXTURE_PATH.name == "gp-snapshot.json"
    assert DEFAULT_FIXTURE_PATH.exists()


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
