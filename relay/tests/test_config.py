"""Tolerant config loading for the single-file model: a missing config.toml means "unenrolled" (build
from the baked defaults with an empty secret), not a crash. get_settings takes an explicit path so each
test uses a unique one - it's @lru_cache-d by path."""

from ucnexus_relay.config import ChannelCfg, UpdateCfg, get_settings


def test_missing_config_returns_unenrolled_defaults(tmp_path):
    s = get_settings(str(tmp_path / "does-not-exist" / "config.toml"))
    assert s.auth.shared_secret == ""  # unenrolled - no secret yet
    assert s.sql.server == "10.0.0.246,1435"  # infra is baked into the defaults
    assert s.sql.system_db == "DYNAMICS"  # where the company master is read from
    assert s.channel.backend_url.startswith("wss://")


def test_a_config_written_before_company_discovery_still_loads(tmp_path):
    # Every deployed workstation's config.toml still names a default and an allowed company list. Those
    # keys mean nothing now (the companies come from GP), but an updated relay that refused to boot on
    # them would take that workstation's production channel down until somebody edited the file by hand.
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        """
[auth]
shared_secret = "s3cret"

[gp]
default_company = "TUBC"
allowed_companies = ["TUBC"]
""",
        encoding="utf-8",
    )
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == "s3cret"
    assert s.gp.custom_db["UBC"] == "PMUBC"  # the section still parses; the dead keys are ignored


def test_loads_a_real_config_with_secret(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[auth]\nshared_secret = "plain-dev-secret"\n', encoding="utf-8")
    s = get_settings(str(cfg))
    assert s.auth.shared_secret == "plain-dev-secret"  # plaintext (dev) passes dpapi.unprotect unchanged


# --- retired pushed preview channels (#868) --------------------------------------------------------


def test_a_config_still_naming_the_retired_preview_keys_loads(tmp_path):
    # A workstation's config.toml is edited by hand and nobody is going to visit every one of them to
    # delete a key, so the retired keys must be ignored rather than fail the load.
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[channel]\naccept_pushed_preview_backends = true\ndiscover_preview_backends = false\n", encoding="utf-8"
    )
    s = get_settings(str(cfg))
    assert not hasattr(s.channel, "accept_pushed_preview_backends")
    assert s.channel.backend_urls == ChannelCfg().backend_urls


# --- update channel ---------------------------------------------------------------------------------


def test_the_update_channel_defaults_to_stable():
    # A workstation only takes a build somebody has already promoted; "latest" is opt-in per machine.
    assert UpdateCfg().channel == "stable"
    assert get_settings("does-not-exist.toml").update.channel == "stable"


def test_the_update_channel_can_be_set_to_latest(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[update]\nchannel = "latest"\n', encoding="utf-8")
    assert get_settings(str(cfg)).update.channel == "latest"


def test_an_unknown_update_channel_loads_and_reads_as_stable(tmp_path, caplog, monkeypatch):
    # A typo here must not make config.toml unreadable (that would keep serve from starting), so the
    # model accepts it and the updater falls back to stable, loudly.
    import ucnexus_relay.config as config
    from ucnexus_relay import updater

    cfg = tmp_path / "config.toml"
    cfg.write_text('[update]\nchannel = "beta"\n', encoding="utf-8")
    assert get_settings(str(cfg)).update.channel == "beta"

    monkeypatch.setattr(config, "DEFAULT_CONFIG_PATH", cfg)
    get_settings.cache_clear()
    try:
        with caplog.at_level("WARNING"):
            assert updater.update_channel() == "stable"
        assert any("unknown [update] channel" in r.getMessage() for r in caplog.records)
    finally:
        get_settings.cache_clear()
