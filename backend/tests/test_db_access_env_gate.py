"""The environment gate that excludes db-access from previews (db-admin-postgres-access).

The feature mints internet-reachable, read-write credentials to the whole database, so it must be
live only on real environments - never on a per-PR preview that inherited PG_DIRECT_HOST from the
base env. The preview-name check is the load-bearing half; these pin both halves.
"""

import pytest

from app import config


@pytest.mark.parametrize(
    "name,expected",
    [
        ("uc-nexus-pr-1", True),
        ("uc-nexus-pr-608", True),
        ("production", False),
        ("staging", False),
        ("", False),
        # A name that merely CONTAINS the prefix must not match - the regex is anchored.
        ("x-uc-nexus-pr-1", False),
        ("uc-nexus-pr-1-suffix", False),
    ],
)
def test_is_preview_environment_matches_only_the_anchored_pr_shape(name, expected, monkeypatch):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", name)
    assert config.is_preview_environment() is expected


def test_disabled_without_a_host(monkeypatch):
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    assert config.db_direct_access_enabled() is False


def test_enabled_on_a_real_environment_with_a_host(monkeypatch):
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")
    assert config.db_direct_access_enabled() is True


def test_disabled_on_a_preview_even_with_an_inherited_host(monkeypatch):
    """The trade the whole exclusion turns on: a preview inherits the base env's variables, so the
    host is present - and the name check is the only thing keeping it off."""
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "uc-nexus-pr-42")
    assert config.db_direct_access_enabled() is False
