"""Tolerant config loading for the single-file model: a missing config.toml means "unenrolled" (build
from the baked defaults with an empty secret), not a crash. get_settings takes an explicit path so each
test uses a unique one - it's @lru_cache-d by path."""

from ucnexus_relay.config import get_settings


def test_missing_config_returns_unenrolled_defaults(tmp_path):
    s = get_settings(str(tmp_path / "does-not-exist" / "config.toml"))
    assert s.auth.shared_secret == ""              # unenrolled - no secret yet
    assert s.sql.server == "10.0.0.246,1435"       # infra is baked into the defaults
    assert s.gp.default_company == "TUBC"
    assert s.channel.backend_url.startswith("wss://")


def test_loads_a_real_config_with_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "plain-dev-secret"\n', encoding="utf-8")
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == "plain-dev-secret"  # plaintext (dev) passes dpapi.unprotect unchanged
