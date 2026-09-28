"""The environment gate on db-access (db-admin-postgres-access).

The feature mints internet-reachable, read-write credentials to the whole database, so it is live
only where the public-proxy host is configured. (The per-PR preview exclusion is gone with PR
environments, #868.)
"""

from app import config


def test_disabled_without_a_host(monkeypatch):
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    assert config.db_direct_access_enabled() is False


def test_enabled_on_a_real_environment_with_a_host(monkeypatch):
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    assert config.db_direct_access_enabled() is True
