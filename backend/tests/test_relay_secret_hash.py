"""The relay secret is stored hashed, and pre-067 rows upgrade themselves (#353 PR C).

The property that matters is not "hashing works" - it is that RELAY_SECRET_ENC_KEY has stopped being
able to orphan a relay. So these pin all three states a live database can be in: hash-only (the new
normal), legacy-only (upgraded in place on the next handshake), and legacy-with-the-key-gone (must
fail softly and say why, never raise)."""

import os

from cryptography.fernet import Fernet

# The crypto layer reads RELAY_SECRET_ENC_KEY at call time; provide one before enroll/authenticate.
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from app.crypto import encrypt_secret, hash_secret  # noqa: E402
from app.models.relay_install import RelayInstall  # noqa: E402
from app.repositories import relay_repository  # noqa: E402


def _legacy_install(session, label: str, secret: str) -> RelayInstall:
    """A pre-067 row: ciphertext only, no hash. Constructed directly because nothing writes this shape
    any more - which is the point of the test."""
    install, _token = relay_repository.provision_install(session, label=label, company="TUBC")
    install.secret_encrypted = encrypt_secret(secret)
    install.secret_hash = None
    session.flush()
    return install


def test_enrolment_stores_a_hash_and_no_ciphertext(db_session):
    _install, token = relay_repository.provision_install(db_session, label="HASH-1", company="TUBC")
    enrolled = relay_repository.enroll_install(db_session, token, hostname="HASH-1", secret="s3cr3t-value")

    assert enrolled.secret_hash == hash_secret("s3cr3t-value")
    assert enrolled.secret_encrypted is None

    found = relay_repository.authenticate_secret(db_session, "s3cr3t-value")
    assert found is not None and found.id == enrolled.id


def test_a_legacy_row_authenticates_and_upgrades_in_place(db_session):
    # The migration path: no data migration ran, so the row migrates itself on the relay's next dial.
    install = _legacy_install(db_session, "LEGACY-1", "legacy-secret")

    found = relay_repository.authenticate_secret(db_session, "legacy-secret")
    assert found is not None and found.id == install.id

    db_session.refresh(install)
    assert install.secret_hash == hash_secret("legacy-secret")
    assert install.secret_encrypted is None

    # And it still authenticates afterwards, now via the hash path.
    again = relay_repository.authenticate_secret(db_session, "legacy-secret")
    assert again is not None and again.id == install.id


def test_a_hash_only_install_authenticates_with_no_encryption_key(db_session, monkeypatch):
    # The whole point of the change: losing or rotating RELAY_SECRET_ENC_KEY can no longer orphan a
    # relay enrolled from 067 on.
    _install, token = relay_repository.provision_install(db_session, label="NOKEY-1", company="TUBC")
    enrolled = relay_repository.enroll_install(db_session, token, hostname="NOKEY-1", secret="keyless-secret")

    monkeypatch.delenv("RELAY_SECRET_ENC_KEY", raising=False)
    found = relay_repository.authenticate_secret(db_session, "keyless-secret")
    assert found is not None and found.id == enrolled.id


def test_a_legacy_only_install_fails_softly_when_the_key_is_gone(db_session, monkeypatch, caplog):
    # A missing key must skip the legacy scan entirely rather than raise CONFIG_ERROR out of the
    # /relay-link route, and the log must name the real cause.
    _legacy_install(db_session, "LEGACY-NOKEY", "legacy-secret")

    monkeypatch.delenv("RELAY_SECRET_ENC_KEY", raising=False)
    with caplog.at_level("WARNING"):
        assert relay_repository.authenticate_secret(db_session, "legacy-secret") is None
    assert any("relay handshake rejected" in r.message for r in caplog.records)


def test_a_wrong_secret_matches_neither_representation(db_session):
    _install, token = relay_repository.provision_install(db_session, label="WRONG-1", company="TUBC")
    relay_repository.enroll_install(db_session, token, hostname="WRONG-1", secret="right-secret")
    _legacy_install(db_session, "WRONG-2", "right-legacy-secret")

    assert relay_repository.authenticate_secret(db_session, "not-the-secret") is None
    assert relay_repository.authenticate_secret(db_session, "") is None


def test_adoption_also_stores_a_hash(db_session):
    # set_install_secret is the single writer, so the adopt path must have moved with it.
    install, _token = relay_repository.provision_install(db_session, label="ADOPT-HASH", company="TUBC")
    relay_repository.adopt_secret(db_session, install.id, "presented-secret", "user_admin")

    assert install.secret_hash == hash_secret("presented-secret")
    assert install.secret_encrypted is None
    assert relay_repository.authenticate_secret(db_session, "presented-secret") is not None
