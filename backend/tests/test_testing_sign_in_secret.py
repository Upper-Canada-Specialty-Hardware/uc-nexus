"""Which digest /testing/clerk-sign-in accepts, and why production must resolve to none.

The secret path exists so a FRESH preview environment can mint its first session, where by definition
no admin session exists yet. The direct variable could never serve that: its preimage mints a real
Clerk session for a real staff account (#422/#424), so it must stay unset in production - and Railway
clones a preview from production, so a preview had nothing to inherit and needed the variable set by
hand, once per PR.

`PREVIEW_TESTING_SIGN_IN_SECRET_HASH` closes that gap: it lives on production, inert, and is
inherited. The load-bearing test here is the one asserting it stays inert there - a regression that
let production resolve a usable digest would hand back exactly the impersonation primitive #424
removed.
"""

import pytest

from app import config


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "")
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "")


def _env(monkeypatch, name):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", name)


def test_production_never_resolves_the_inherited_preview_digest(monkeypatch):
    # THE test in this file. The preimage mints a real staff session, so production holding the
    # variable must remain harmless - that is the only reason it is allowed to live there at all.
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "a" * 64)
    _env(monkeypatch, "production")
    assert config.testing_sign_in_secret_hash() == ""


@pytest.mark.parametrize("name", ["Production", "PRODUCTION", "  production  "])
def test_production_is_recognised_however_it_is_cased_or_padded(monkeypatch, name):
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "a" * 64)
    _env(monkeypatch, name)
    assert config.testing_sign_in_secret_hash() == ""


def test_a_preview_environment_inherits_the_digest_with_nothing_set_on_it(monkeypatch):
    # The whole point: a PR environment is testable the moment it exists.
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "b" * 64)
    _env(monkeypatch, "uc-nexus-pr-999")
    assert config.testing_sign_in_secret_hash() == "b" * 64


def test_an_explicit_per_environment_secret_still_wins(monkeypatch):
    # The documented manual override has to keep working, so one environment can carry its own.
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "c" * 64)
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "d" * 64)
    _env(monkeypatch, "uc-nexus-pr-999")
    assert config.testing_sign_in_secret_hash() == "c" * 64


def test_an_explicit_secret_works_in_production_too(monkeypatch):
    # Deliberate: production refusing the INHERITED digest is the safeguard. Somebody who sets the
    # direct variable there has made an explicit choice, and this is not the layer that overrides it.
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "e" * 64)
    _env(monkeypatch, "production")
    assert config.testing_sign_in_secret_hash() == "e" * 64


def test_nothing_set_closes_the_secret_path(monkeypatch):
    _env(monkeypatch, "uc-nexus-pr-999")
    assert config.testing_sign_in_secret_hash() == ""


def test_a_local_checkout_is_not_production(monkeypatch):
    # RAILWAY_ENVIRONMENT_NAME is empty off Railway; that has to read as "not production" or a local
    # run with the seed set would refuse it.
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "f" * 64)
    assert config.testing_sign_in_secret_hash() == "f" * 64
    assert config.is_production_environment() is False


def test_whitespace_only_values_are_not_secrets(monkeypatch):
    monkeypatch.setattr(config, "TESTING_SIGN_IN_SECRET_HASH", "   ")
    monkeypatch.setattr(config, "PREVIEW_TESTING_SIGN_IN_SECRET_HASH", "  ")
    _env(monkeypatch, "uc-nexus-pr-999")
    assert config.testing_sign_in_secret_hash() == ""
