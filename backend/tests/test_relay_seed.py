"""Relay credential seeding for non-production environments (#414, #654).

A Railway PR environment gets a fresh Postgres with an empty relay_installs, so a relay's handshake is
refused and every GP-dependent page is dead there. Seeding a hash lets the relay that holds its
preimage authenticate with the secret it already has.

WHICH hash is seeded is #654's change: the default is a stub relay running inside the preview, and
PREVIEW_REAL_RELAY opts back into the workstation relay. Exactly one is ever seeded, and the tests
that matter most are still the refusals - this writes a working credential into a database, and the
production kill-switch is what keeps that acceptable.
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
STUB_HASH = hash_secret("the-stub-relays-own-secret")


def _seed(session, *, environment_name="pr-414", secret_hash=HASH, label_prefix=None):
    return relay_seed.seed_from_env(
        session,
        environment_name=environment_name,
        secret_hash=secret_hash,
        label_prefix=label_prefix or relay_seed.SEED_LABEL_PREFIX,
    )


def _owned_rows(session) -> list[str]:
    """The labels of the rows seeding owns for pr-414 - both kinds. Scoped to those two rather than
    counting the whole table: other suites commit relay installs of their own."""
    return sorted(
        label
        for (label,) in session.query(RelayInstall.label)
        .filter(RelayInstall.label.in_(["seed:pr-414", "stub:pr-414"]))
        .all()
    )


def test_production_is_refused_outright(db_session):
    # Railway clones a PR environment from production, so the variables are SET in production by design
    # (#431) and will always be visible here. The guard is the reason that is survivable - it must not
    # depend on them being absent.
    assert _seed(db_session, environment_name="production") is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0


def test_production_refuses_the_stub_hash_too(db_session):
    assert (
        _seed(
            db_session,
            environment_name="production",
            secret_hash=STUB_HASH,
            label_prefix=relay_seed.STUB_LABEL_PREFIX,
        )
        is None
    )
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == STUB_HASH).count() == 0


def test_the_production_refusal_reads_as_expected_not_as_a_misconfiguration(db_session, caplog):
    # #431: the original message logged at ERROR and told the operator to remove the variable from
    # production. Following it breaks every PR environment created afterwards, because production is
    # the only place a new one can inherit the variable from.
    with caplog.at_level(logging.INFO, logger=relay_seed.__name__):
        assert _seed(db_session, environment_name="production") is None
    record = next(r for r in caplog.records if "seeding never" in r.getMessage())
    assert record.levelno == logging.INFO
    assert "remove" not in record.getMessage().lower()


@pytest.mark.parametrize("name", ["Production", "  PRODUCTION  "])
def test_the_production_check_ignores_case_and_padding(db_session, name):
    assert _seed(db_session, environment_name=name) is None


def test_a_pr_environment_gets_a_seeded_install(db_session):
    install = _seed(db_session)
    assert install is not None
    assert install.secret_hash == HASH
    assert install.label == "seed:pr-414"
    # Enrolled on creation: there is no token and none is wanted, and a permanently "pending" row that
    # nonetheless authenticates would be a lie on Admin -> Relay Installs.
    assert install.enrolled_at is not None


def test_the_stub_install_is_labelled_as_one(db_session):
    # The label prefix is what lets a later pass recognise the row of the other kind and remove it.
    install = _seed(db_session, secret_hash=STUB_HASH, label_prefix=relay_seed.STUB_LABEL_PREFIX)
    assert install.label == "stub:pr-414"


def test_seeding_is_idempotent_across_restarts(db_session):
    first = _seed(db_session)
    second = _seed(db_session)
    assert second.id == first.id
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 1


@pytest.mark.parametrize(
    "value",
    ["", "   ", "not-a-hash", "abc123", HASH[:-1], HASH + "0", "z" * 64],
)
def test_a_malformed_hash_is_skipped_not_stored(db_session, value):
    assert _seed(db_session, secret_hash=value) is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0


def test_an_uppercase_hash_is_accepted_and_normalised(db_session):
    # Copy/paste out of a SQL client can arrive uppercase; the stored digest is lowercase hex, so a
    # verbatim insert would silently never match on the handshake.
    install = _seed(db_session, secret_hash=HASH.upper())
    assert install.secret_hash == HASH


def test_the_seeded_row_authenticates_the_real_relay_secret(db_session):
    # The end-to-end point of the whole feature: the relay presents the secret it already holds, and a
    # PR backend accepts it without any enrollment having happened there.
    _seed(db_session)
    install = relay_repository.authenticate_secret(db_session, SECRET)
    assert install is not None
    assert install.label == "seed:pr-414"


def test_a_local_environment_with_no_name_still_seeds(db_session):
    # Off Railway RAILWAY_ENVIRONMENT_NAME is empty. That is not production, and a developer running
    # against a local DB is exactly who else benefits from this.
    install = _seed(db_session, environment_name="")
    assert install is not None
    assert install.label == "seed:local"


def test_a_database_holding_a_real_enrolled_relay_is_never_seeded(db_session):
    # The naming check alone fails OPEN - rename the base environment, restore a prod dump into
    # staging, or point DATABASE_URL somewhere shared, and a credential whose preimage sits in a
    # Railway variable lands next to the real install. `hostname` is written only by enroll_install, so
    # its presence means a real relay paired with this database whatever the environment is called.
    real = RelayInstall(
        id=uuid.uuid4(),
        label="TAGGING3W10",
        hostname="Tagging3W10",
        secret_hash="c" * 64,
        enrolled_at=datetime.utcnow(),
    )
    db_session.add(real)
    db_session.flush()

    assert _seed(db_session, environment_name="staging") is None
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0
    assert real.secret_hash == "c" * 64  # untouched


def test_an_existing_row_carrying_the_hash_is_left_completely_alone(db_session):
    # A row that already carries the hash is somebody else's - a real install, or one made by hand -
    # and seeding neither relabels nor otherwise repairs it.
    real = RelayInstall(id=uuid.uuid4(), label="hand-made", secret_hash=HASH)
    db_session.add(real)
    db_session.flush()

    returned = _seed(db_session)
    assert returned.id == real.id
    assert returned.label == "hand-made"


def test_rotating_the_hash_removes_the_superseded_seed_row(db_session):
    # Otherwise the old secret keeps authenticating in that environment forever, and the grid grows a
    # row per rotation.
    first = _seed(db_session)
    first_id = first.id
    rotated = "d" * 64
    second = _seed(db_session, secret_hash=rotated)

    assert second.id != first_id
    assert db_session.query(RelayInstall).filter(RelayInstall.secret_hash == HASH).count() == 0
    assert db_session.query(RelayInstall).filter(RelayInstall.label == "seed:pr-414").count() == 1


def test_rotation_only_removes_this_environments_own_seed_row(db_session):
    other = RelayInstall(id=uuid.uuid4(), label="seed:pr-999", secret_hash="e" * 64)
    db_session.add(other)
    db_session.flush()

    _seed(db_session)
    assert db_session.query(RelayInstall).filter(RelayInstall.label == "seed:pr-999").count() == 1


# --- one kind at a time: flipping PREVIEW_REAL_RELAY (#654) ----------------------------------------


def test_flipping_to_the_real_relay_removes_the_stub_row(db_session):
    """Two live credentials on one environment means the connection slot goes to whichever relay dials
    first, which is not a decision anybody made."""
    _seed(db_session, secret_hash=STUB_HASH, label_prefix=relay_seed.STUB_LABEL_PREFIX)
    real = _seed(db_session)

    assert real.label == "seed:pr-414"
    assert _owned_rows(db_session) == ["seed:pr-414"]


def test_flipping_back_to_the_stub_removes_the_real_row(db_session):
    _seed(db_session)
    stub = _seed(db_session, secret_hash=STUB_HASH, label_prefix=relay_seed.STUB_LABEL_PREFIX)

    assert stub.label == "stub:pr-414"
    assert _owned_rows(db_session) == ["stub:pr-414"]


def test_the_flip_only_touches_this_environments_rows(db_session):
    other = RelayInstall(id=uuid.uuid4(), label="stub:pr-999", secret_hash="f" * 64)
    db_session.add(other)
    db_session.flush()

    _seed(db_session)
    assert db_session.query(RelayInstall).filter(RelayInstall.label == "stub:pr-999").count() == 1


# --- which credential seed_on_startup chooses ------------------------------------------------------


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        return None


@pytest.fixture
def startup_call(monkeypatch):
    """Run seed_on_startup against no database and report the arguments it chose."""
    captured: list[dict] = []
    monkeypatch.setattr(relay_seed, "SessionLocal", _FakeSession)
    monkeypatch.setattr(relay_seed, "seed_from_env", lambda session, **kwargs: captured.append(kwargs))
    return captured


def test_the_stub_is_what_a_preview_seeds_by_default(monkeypatch, startup_call):
    # The default preview is self-contained: nothing depends on an office workstation being switched on
    # for a PR to be testable.
    monkeypatch.setattr(relay_seed, "PREVIEW_REAL_RELAY", False)
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", HASH)
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", STUB_HASH)

    relay_seed.seed_on_startup()

    assert startup_call == [
        {
            "environment_name": relay_seed.RAILWAY_ENVIRONMENT_NAME,
            "secret_hash": STUB_HASH,
            "label_prefix": relay_seed.STUB_LABEL_PREFIX,
        }
    ]


def test_the_real_relay_hash_is_seeded_when_the_flag_is_on(monkeypatch, startup_call):
    monkeypatch.setattr(relay_seed, "PREVIEW_REAL_RELAY", True)
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", HASH)
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", STUB_HASH)

    relay_seed.seed_on_startup()

    assert startup_call[0]["secret_hash"] == HASH
    assert startup_call[0]["label_prefix"] == relay_seed.SEED_LABEL_PREFIX


def test_seed_on_startup_does_nothing_without_either_variable(monkeypatch, startup_call):
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", "")
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", "")
    relay_seed.seed_on_startup()
    assert startup_call == []


def test_production_skips_quietly_before_choosing_a_kind(monkeypatch, startup_call, caplog):
    # Production holds the real relay's hash for previews to inherit and never the stub hash, so the
    # kind-selection below would otherwise warn that relay pages will not work on the one environment
    # where they do. Seen on the first deploy of the stub-default seeding.
    monkeypatch.setattr(relay_seed, "RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setattr(relay_seed, "PREVIEW_REAL_RELAY", False)
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", HASH)
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", "")

    with caplog.at_level(logging.INFO, logger=relay_seed.__name__):
        relay_seed.seed_on_startup()

    assert startup_call == []
    assert all(r.levelno < logging.WARNING for r in caplog.records)
    assert "seeding never runs in production" in caplog.records[-1].getMessage()


def test_a_missing_hash_for_the_chosen_kind_says_so(monkeypatch, startup_call, caplog):
    # The flag is on but the hash it selects is unset - the environment gets no credential, and the
    # reason has to be readable in the deploy log rather than looking like a silent no-op.
    monkeypatch.setattr(relay_seed, "PREVIEW_REAL_RELAY", True)
    monkeypatch.setattr(relay_seed, "RELAY_SEED_SECRET_HASH", "")
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", STUB_HASH)

    with caplog.at_level(logging.WARNING, logger=relay_seed.__name__):
        relay_seed.seed_on_startup()

    assert startup_call == []
    assert "RELAY_SEED_SECRET_HASH" in caplog.records[-1].getMessage()


def test_seed_on_startup_never_raises(monkeypatch):
    # A backend that cannot seed must still boot: the failure mode is "relay pages don't work in this
    # PR environment", which is exactly where things stood before this existed.
    monkeypatch.setattr(relay_seed, "PREVIEW_REAL_RELAY", False)
    monkeypatch.setattr(relay_seed, "RELAY_STUB_SECRET_HASH", STUB_HASH)

    def boom(*a, **k):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr(relay_seed, "SessionLocal", boom)
    relay_seed.seed_on_startup()  # must not raise
