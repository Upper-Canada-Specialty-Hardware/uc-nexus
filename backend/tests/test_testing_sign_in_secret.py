"""Which digest /testing/clerk-sign-in accepts.

The inherited preview copy of the digest is gone with PR environments (#868), so the only source is
the per-environment `TESTING_SIGN_IN_SECRET_HASH`.
"""

import pytest

from app import config


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "")


def test_the_explicit_secret_is_the_digest(monkeypatch):
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "c" * 64)
    assert config.testing_sign_in_secret_hash() == "c" * 64


def test_nothing_set_closes_the_secret_path():
    assert config.testing_sign_in_secret_hash() == ""


def test_whitespace_only_values_are_not_secrets(monkeypatch):
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "   ")
    assert config.testing_sign_in_secret_hash() == ""
