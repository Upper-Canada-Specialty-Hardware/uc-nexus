"""Relay credential seeding for non-production environments (issue #414).

A Railway PR environment gets a fresh Postgres with an empty relay_installs, so the relay's handshake
is refused and every GP-dependent page is dead there. Seeding the hash production already stores lets
the one workstation relay authenticate against a PR backend with the secret it already holds.

The tests that matter most are the refusals: this writes a working credential into a database, and the
only things keeping that acceptable are the production kill-switch and the sandbox company pin.
"""

import logging
import uuid
from datetime import datetime

import pytest

from app.crypto import hash_secret
from app.models.relay_install import RelayInstall
from app.repositories import relay_repository
from app.services import relay_seed

SECRET = "a-relay-generated-token-urlsafe-32-value"
HASH = hash_secret(SECRET)


def test_production_is_refused_outright(db_session):
    # Railway clones a PR environment from production, so the variable is SET in production by design
    # (#431) and will always be visible here. The guard is the reason that is survivable - it must not
    # depend on the variable being absent.
    assert relay_seed.seed_from_env(db_session, environment_name="production", secret_hash=HASH) is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0


def test_the_production_refusal_reads_as_expected_not_as_a_misconfiguration(db_session, caplog):
    # #431: the original message logged at ERROR and told the operator to remove the variable from
    # production. Following it breaks every PR environment created afterwards, because production is
    # the only place a new one can inherit the variable from.
    with caplog.at_level(logging.INFO, logger=relay_seed.__name__):
        assert relay_seed.seed_from_env(db_session, environment_name="production", secret_hash=HASH) is None
    record = next(r for r in caplog.records if "RELAY_SEED_SECRET_HASH" in r.getMessage())
    assert record.levelno == logging.INFO
    assert "remove" not in record.getMessage().lower()


@pytest.mark.parametrize("name", ["Production", "  PRODUCTION  "])
def test_the_production_check_ignores_case_and_padding(db_session, name):
    assert relay_seed.seed_from_env(db_session, environment_name=name, secret_hash=HASH) is None


def test_a_pr_environment_gets_a_seeded_install(db_session):
    install = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    assert install is not None
    assert install.company == relay_seed.SEED_COMPANY == "TUBC"
    assert install.secret_hash == HASH
    assert install.label == "seed:pr-414"
    # Enrolled on creation: there is no token and none is wanted, and a permanently "pending" row that
    # nonetheless authenticates would be a lie on Admin -> Relay Installs.
    assert install.enrolled_at is not None


def test_seeding_is_idempotent_across_restarts(db_session):
    first = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    second = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    assert second.id == first.id
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 1


@pytest.mark.parametrize(
    "value",
    ["", "   ", "not-a-hash", "abc123", HASH[:-1], HASH + "0", "z" * 64],
)
def test_a_malformed_hash_is_skipped_not_stored(db_session, value):
    assert relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=value) is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0


def test_an_uppercase_hash_is_accepted_and_normalised(db_session):
    # Copy/paste out of a SQL client can arrive uppercase; the stored digest is lowercase hex, so a
    # verbatim insert would silently never match on the handshake.
    install = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH.upper())
    assert install.secret_hash == HASH


def test_the_seeded_row_authenticates_the_real_relay_secret(db_session):
    # The end-to-end point of the whole feature: the workstation relay presents the secret it already
    # holds, and a PR backend accepts it without any enrollment having happened there.
    relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    install = relay_repository.authenticate_secret(db_session, SECRET)
    assert install is not None
    assert install.company == "TUBC"


def test_a_local_environment_with_no_name_still_seeds(db_session):
    # Off Railway RAILWAY_ENVIRONMENT_NAME is empty. That is not production, and a developer running
    # against a local DB is exactly who else benefits from this.
    install = relay_seed.seed_from_env(db_session, environment_name="", secret_hash=HASH)
    assert install is not None
    assert install.label == "seed:local"


def test_seed_on_startup_does_nothing_without_the_variable(monkeypatch):
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", "")
    called = []
    monkeypatch.setattr(relay_seed, "seed_from_env", lambda *a, **k: called.append(a))
    relay_seed.seed_on_startup()
    assert called == []


def test_seed_on_startup_never_raises(monkeypatch):
    # A backend that cannot seed must still boot: the failure mode is "relay pages don't work in this
    # PR environment", which is exactly where things stood before this existed.
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", HASH)

    def boom(*a, **k):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(relay_seed, "seed_from_env", boom)
    relay_seed.seed_on_startup()  # must not raise


def test_a_database_holding_a_real_enrolled_relay_is_never_seeded(db_session):
    # The naming check alone fails OPEN - rename the base environment, restore a prod dump into
    # staging, or point DATABASE_URL somewhere shared, and a credential whose preimage sits in a
    # Railway variable lands next to the real install. `hostname` is written only by enroll_install, so
    # its presence means a real relay paired with this database whatever the environment is called.
    real = RelayInstall(
        id=uuid.uuid4(),
        label="TAGGING3W10",
        companies=["UCSH"],
        hostname="Tagging3W10",
        secret_hash="c" * 64,
        enrolled_at=datetime.utcnow(),
    )
    db_session.add(real)
    db_session.flush()

    assert relay_seed.seed_from_env(db_session, environment_name="staging", secret_hash=HASH) is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0
    assert real.company == "UCSH"  # untouched


def test_an_existing_row_carrying_the_hash_is_left_completely_alone(db_session):
    # An earlier draft "repaired" the company here. On a live install that silently repoints a real
    # credential from UBC/UCSH to TUBC, with the original value surviving only in a log line.
    real = RelayInstall(id=uuid.uuid4(), label="hand-made", companies=["UCSH"], secret_hash=HASH)
    db_session.add(real)
    db_session.flush()

    returned = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    assert returned.id == real.id
    assert returned.company == "UCSH"  # NOT rewritten to TUBC
    assert returned.label == "hand-made"


def test_rotating_the_hash_removes_the_superseded_seed_row(db_session):
    # Otherwise the old secret keeps authenticating in that environment forever, and the grid grows a
    # row per rotation.
    first = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    first_id = first.id
    rotated = "d" * 64
    second = relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=rotated)

    assert second.id != first_id
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0
    assert db_session.query(RelayInstall).filter(RelayInstall.label == "seed:pr-414").count() == 1


def test_rotation_only_removes_this_environments_own_seed_row(db_session):
    other = RelayInstall(id=uuid.uuid4(), label="seed:pr-999", companies=["TUBC"], secret_hash="e" * 64)
    db_session.add(other)
    db_session.flush()

    relay_seed.seed_from_env(db_session, environment_name="pr-414", secret_hash=HASH)
    assert db_session.query(RelayInstall).filter(RelayInstall.label == "seed:pr-999").count() == 1
