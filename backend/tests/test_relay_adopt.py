"""The admin-armed adopt window (#353 PR B).

Adoption deliberately accepts a /relay-link connection whose secret matches nothing, so the parts
that bound that exposure - a TTL, single use, one install at a time - are the parts that need pinning.
A regression here would not fail any GP flow; it would silently leave the door open."""

import os
import uuid
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

# The crypto layer reads RELAY_SECRET_ENC_KEY at call time; provide one before enroll/adopt.
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from app.repositories import relay_repository  # noqa: E402
from app.services import relay_adopt  # noqa: E402


def _fresh_window_state():
    relay_adopt.disarm()


def test_arm_then_peek_returns_the_window():
    _fresh_window_state()
    install_id = uuid.uuid4()
    armed = relay_adopt.arm(install_id, "TAGGING3W10", "user_admin")
    seen = relay_adopt.peek()
    assert seen is not None
    assert seen.install_id == install_id
    assert seen.label == "TAGGING3W10"
    assert seen.armed_by == "user_admin"
    assert seen == armed
    relay_adopt.disarm()


def test_peek_clears_an_expired_window():
    # Expiry is only ever observed on a read, so an expired window must not linger as "armed" in the
    # admin UI - and must not be adoptable.
    _fresh_window_state()
    install_id = uuid.uuid4()
    relay_adopt.arm(install_id, "STALE", "user_admin")
    relay_adopt._window = relay_adopt.ArmedWindow(
        install_id=install_id,
        label="STALE",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
        armed_by="user_admin",
    )
    assert relay_adopt.peek() is None
    assert relay_adopt.consume(install_id) is False


def test_consume_is_single_use():
    _fresh_window_state()
    install_id = uuid.uuid4()
    relay_adopt.arm(install_id, "ONE-SHOT", "user_admin")
    assert relay_adopt.consume(install_id) is True
    assert relay_adopt.consume(install_id) is False
    assert relay_adopt.peek() is None


def test_consume_rejects_a_different_install():
    _fresh_window_state()
    armed_id = uuid.uuid4()
    relay_adopt.arm(armed_id, "ARMED", "user_admin")
    assert relay_adopt.consume(uuid.uuid4()) is False
    assert relay_adopt.peek() is not None  # the real window is untouched
    relay_adopt.disarm()


def test_arming_a_second_install_replaces_the_first():
    _fresh_window_state()
    first, second = uuid.uuid4(), uuid.uuid4()
    relay_adopt.arm(first, "FIRST", "user_admin")
    relay_adopt.arm(second, "SECOND", "user_admin")
    seen = relay_adopt.peek()
    assert seen is not None and seen.install_id == second
    assert relay_adopt.consume(first) is False
    relay_adopt.disarm()


def test_disarm_reports_whether_a_window_was_open():
    _fresh_window_state()
    assert relay_adopt.disarm() is False
    relay_adopt.arm(uuid.uuid4(), "X", "user_admin")
    assert relay_adopt.disarm() is True
    assert relay_adopt.peek() is None


def test_adopt_secret_binds_the_presented_secret_and_stamps_the_audit(db_session):
    # The whole point: after adoption, the secret the relay is ALREADY dialling with authenticates.
    install, _token = relay_repository.provision_install(db_session, label="ADOPT-ME", companies=["TUBC"])
    presented = "the-secret-the-relay-still-holds"
    assert relay_repository.authenticate_secret(db_session, presented) is None

    adopted = relay_repository.adopt_secret(db_session, install.id, presented, "user_admin")
    assert adopted is not None and adopted.id == install.id
    assert adopted.adopted_by == "user_admin"
    assert adopted.adopted_at is not None
    assert adopted.enrolled_at is not None  # a never-enrolled row stops reading as "pending"

    found = relay_repository.authenticate_secret(db_session, presented)
    assert found is not None and found.id == install.id


def test_adopt_secret_returns_none_when_the_row_is_gone(db_session):
    assert relay_repository.adopt_secret(db_session, uuid.uuid4(), "whatever", "user_admin") is None


def test_adopt_secret_replaces_an_existing_credential(db_session):
    # The recovery case: the row already holds a secret, but the running relay is presenting an older
    # one. Adoption must rebind to what is being presented, and the superseded secret must stop working.
    install, token = relay_repository.provision_install(db_session, label="DRIFTED", companies=["TUBC"])
    relay_repository.enroll_install(db_session, token, hostname="DRIFTED", secret="new-but-unused")
    relay_repository.adopt_secret(db_session, install.id, "old-in-memory-secret", "user_admin")

    assert relay_repository.authenticate_secret(db_session, "old-in-memory-secret") is not None
    assert relay_repository.authenticate_secret(db_session, "new-but-unused") is None
