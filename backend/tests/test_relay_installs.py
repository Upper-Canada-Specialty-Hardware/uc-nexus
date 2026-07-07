"""Relay install provisioning + enrollment + credential round-trip."""

import os

import pytest
from cryptography.fernet import Fernet

# Provide an encryption key before any crypto call (the app reads RELAY_SECRET_ENC_KEY at call time).
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from app.errors import ConflictError, ValidationError  # noqa: E402
from app.repositories import relay_repository  # noqa: E402


def test_provision_returns_token_and_stores_hash_only(db_session):
    install, token = relay_repository.provision_install(db_session, label="Tagging3W10", company="TUBC")
    assert token
    assert install.secret_encrypted is None
    assert install.enrollment_token_hash and install.enrollment_token_hash != token  # hashed, not raw


def test_enroll_stores_secret_and_returns_credential(db_session):
    install, token = relay_repository.provision_install(db_session, label="WS1", company="TUBC")
    enrolled = relay_repository.enroll_install(db_session, token, hostname="WS1", secret="s3cr3t-value")
    assert enrolled.id == install.id
    assert enrolled.enrolled_at is not None  # single use is enforced via enrolled_at, not by clearing the hash
    # credential round-trips back to the raw secret the frontend needs for the Bearer header
    assert relay_repository.get_credential(db_session) == "s3cr3t-value"


def test_enroll_rejects_reused_token(db_session):
    _, token = relay_repository.provision_install(db_session, label="WS2", company="TUBC")
    relay_repository.enroll_install(db_session, token, hostname="WS2", secret="abc")
    with pytest.raises(ConflictError):
        relay_repository.enroll_install(db_session, token, hostname="WS2", secret="def")


def test_enroll_rejects_invalid_token(db_session):
    with pytest.raises(ValidationError):
        relay_repository.enroll_install(db_session, "not-a-real-token", hostname="WS3", secret="abc")


def test_authenticate_secret_finds_the_enrolled_install(db_session):
    install, token = relay_repository.provision_install(db_session, label="WS4", company="TUBC")
    relay_repository.enroll_install(db_session, token, hostname="WS4", secret="channel-secret")

    found = relay_repository.authenticate_secret(db_session, "channel-secret")
    assert found is not None
    assert found.id == install.id
    assert found.last_seen_at is not None


def test_authenticate_secret_rejects_an_unknown_secret(db_session):
    _, token = relay_repository.provision_install(db_session, label="WS5", company="TUBC")
    relay_repository.enroll_install(db_session, token, hostname="WS5", secret="the-real-secret")

    assert relay_repository.authenticate_secret(db_session, "not-the-secret") is None


def test_authenticate_secret_rejects_blank():
    assert relay_repository.authenticate_secret(None, "") is None
