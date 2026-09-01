"""Relay install provisioning + enrollment + authentication round-trip."""

import os

import pytest
from cryptography.fernet import Fernet

# Provide an encryption key before any crypto call (the app reads RELAY_SECRET_ENC_KEY at call time).
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from app.errors import ConflictError, ValidationError  # noqa: E402
from app.repositories import relay_repository  # noqa: E402


def test_provision_returns_token_and_stores_hash_only(db_session):
    install, token = relay_repository.provision_install(db_session, label="Tagging3W10", companies=["TUBC"])
    assert token
    assert install.secret_hash is None  # no relay credential exists until the relay enrolls
    assert install.secret_encrypted is None
    assert install.enrollment_token_hash and install.enrollment_token_hash != token  # hashed, not raw


def test_enroll_stores_secret_and_authenticates(db_session):
    install, token = relay_repository.provision_install(db_session, label="WS1", companies=["TUBC"])
    enrolled = relay_repository.enroll_install(db_session, token, hostname="WS1", secret="s3cr3t-value")
    assert enrolled.id == install.id
    assert enrolled.enrolled_at is not None  # single use is enforced via enrolled_at, not by clearing the hash
    # the encrypted secret round-trips: the relay's own WS connect handshake authenticates with it
    found = relay_repository.authenticate_secret(db_session, "s3cr3t-value")
    assert found is not None
    assert found.id == install.id


def test_enroll_rejects_reused_token(db_session):
    _, token = relay_repository.provision_install(db_session, label="WS2", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="WS2", secret="abc")
    with pytest.raises(ConflictError):
        relay_repository.enroll_install(db_session, token, hostname="WS2", secret="def")


def test_enroll_rejects_invalid_token(db_session):
    with pytest.raises(ValidationError):
        relay_repository.enroll_install(db_session, "not-a-real-token", hostname="WS3", secret="abc")


def test_authenticate_secret_finds_the_enrolled_install(db_session):
    install, token = relay_repository.provision_install(db_session, label="WS4", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="WS4", secret="channel-secret")

    found = relay_repository.authenticate_secret(db_session, "channel-secret")
    assert found is not None
    assert found.id == install.id
    assert found.last_seen_at is not None


def test_authenticate_secret_rejects_an_unknown_secret(db_session):
    _, token = relay_repository.provision_install(db_session, label="WS5", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="WS5", secret="the-real-secret")

    assert relay_repository.authenticate_secret(db_session, "not-the-secret") is None


def test_authenticate_secret_rejects_blank():
    assert relay_repository.authenticate_secret(None, "") is None


def test_a_rotated_encryption_key_no_longer_orphans_an_install(db_session, monkeypatch):
    """#353 PR C inverts what #352 could only mitigate.

    This test previously asserted that rotating RELAY_SECRET_ENC_KEY made a *correct* secret fail -
    true when the secret was stored reversibly, and the reason that one key was a single point of
    permanent failure. Since migration 067 the secret is a hash, so the key is not read on this path
    at all and rotation is a non-event. Losing the key can no longer take GP down.

    The clean-rejection property #352 added still matters for pre-067 rows; that case is covered in
    test_relay_secret_hash.py (a legacy row with the key gone returns None without raising, and logs
    the real cause)."""
    _, token = relay_repository.provision_install(db_session, label="WS6", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="WS6", secret="valid-secret")

    monkeypatch.setenv("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

    found = relay_repository.authenticate_secret(db_session, "valid-secret")
    assert found is not None
    assert found.label == "WS6"


# --- deletion (#366) ----------------------------------------------------------------------------------
# Rows accumulate from every abandoned provisioning attempt, and until this existed the only way to
# remove one was hand-written SQL. Two properties matter: the credential is genuinely revoked (not just
# hidden from the grid), and removing one install does not disturb the others.


def test_delete_install_revokes_the_credential(db_session):
    install, token = relay_repository.provision_install(db_session, label="Retired", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="RETIRED", secret="retired-secret")
    assert relay_repository.authenticate_secret(db_session, "retired-secret") is not None

    snapshot = relay_repository.delete_install(db_session, install.id)

    assert snapshot["label"] == "Retired"
    assert snapshot["hostname"] == "RETIRED"
    # The point of a hard delete: the secret stops authenticating, rather than the row merely hiding.
    assert relay_repository.authenticate_secret(db_session, "retired-secret") is None


def test_delete_install_returns_none_for_a_row_that_is_already_gone(db_session):
    import uuid as _uuid

    assert relay_repository.delete_install(db_session, _uuid.uuid4()) is None


def test_delete_install_leaves_the_other_installs_authenticating(db_session):
    doomed, doomed_token = relay_repository.provision_install(db_session, label="Doomed", companies=["TUBC"])
    relay_repository.enroll_install(db_session, doomed_token, hostname="D", secret="doomed-secret")
    _, keeper_token = relay_repository.provision_install(db_session, label="Keeper", companies=["TUBC"])
    keeper = relay_repository.enroll_install(db_session, keeper_token, hostname="K", secret="keeper-secret")

    relay_repository.delete_install(db_session, doomed.id)

    assert relay_repository.authenticate_secret(db_session, "doomed-secret") is None
    still_there = relay_repository.authenticate_secret(db_session, "keeper-secret")
    assert still_there is not None and still_there.id == keeper.id
