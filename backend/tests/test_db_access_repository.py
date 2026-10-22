"""The pure guardrail machinery behind the Database Access page (db-admin-postgres-access).

The role DDL itself needs a Postgres cluster and is exercised in the environment, not here. What these
cover is the part that has to be right BEFORE any statement runs: the SCRAM verifier the statement
carries instead of a password, the identifier validation/quoting that makes a role name safe to
interpolate, the deterministic name derivation, the denylist, and the environment gate.
"""

import base64
import hashlib
import hmac

import pytest
from sqlalchemy import text as sa_text

from app import config
from app.errors import AppError, ValidationError
from app.repositories import db_access_repository as repo

# --- SCRAM-SHA-256 verifier ----------------------------------------------------------------------


def test_scram_verifier_has_the_shape_postgres_stores():
    v = repo._scram_sha256_verifier("hunter2")
    assert v.startswith("SCRAM-SHA-256$4096:")
    prefix, rest = v.split("$", 1)
    iters_salt, keys = rest.split("$", 1)
    iterations, b64salt = iters_salt.split(":", 1)
    stored_b64, server_b64 = keys.split(":", 1)
    assert iterations == "4096"
    # 16-byte salt, 32-byte SHA-256 keys, round-tripping cleanly through base64.
    assert len(base64.b64decode(b64salt)) == 16
    assert len(base64.b64decode(stored_b64)) == 32
    assert len(base64.b64decode(server_b64)) == 32


def test_scram_verifier_keys_are_derived_correctly():
    """Reconstruct StoredKey and ServerKey from the password + the verifier's own salt/iterations and
    check they match - proves the PBKDF2 -> HMAC -> SHA chain is the one Postgres will validate against,
    not merely well-formed."""
    password = "correct horse battery staple"
    v = repo._scram_sha256_verifier(password)
    _, rest = v.split("$", 1)
    iters_salt, keys = rest.split("$", 1)
    iterations, b64salt = iters_salt.split(":", 1)
    stored_b64, server_b64 = keys.split(":", 1)

    salt = base64.b64decode(b64salt)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
    expected_stored = hashlib.sha256(hmac.new(salted, b"Client Key", hashlib.sha256).digest()).digest()
    expected_server = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    assert base64.b64decode(stored_b64) == expected_stored
    assert base64.b64decode(server_b64) == expected_server


def test_scram_verifier_is_salted_per_call():
    assert repo._scram_sha256_verifier("same") != repo._scram_sha256_verifier("same")


def test_scram_verifier_storedkey_ends_in_base64_padding():
    """The StoredKey is 32 bytes, so its base64 always ends in "=" padding. That "=" is exactly why the
    ":" before ServerKey is a SQLAlchemy text() bind hazard - the negative lookbehind before a bind
    passes on a non-word char - and why the role DDL interpolates the verifier via exec_driver_sql."""
    for _ in range(20):
        v = repo._scram_sha256_verifier("pw")
        stored_b64 = v.split("$")[2].split(":")[0]
        assert stored_b64.endswith("=")


def test_text_misparses_a_verifier_shaped_password_literal():
    """Regression for the mint/rotate ship-blocker: a PASSWORD statement carrying a SCRAM verifier must
    NOT go through text(), which reads the "=" -terminated StoredKey's trailing ":" as a required bind
    and raises before the statement reaches Postgres. Uses the exact hazardous shape so it is
    deterministic (a real verifier hits it ~97% of the time). If someone reverts to text(), the
    reasoning is here."""
    hazardous = "SCRAM-SHA-256$4096:c2FsdHNhbHRzYWx0c2E=$c3RvcmVka2V5c3RvcmVka2V5c3RvcmVka2V5MDA=:U2VydmVyS2V5"
    parsed = sa_text(f"ALTER ROLE \"user_x\" PASSWORD '{hazardous}'")
    assert parsed._bindparams, "text() should have misparsed the verifier's ':' as a bind param"


def test_generated_password_and_its_verifier_carry_no_quote():
    """The whole injection-safety argument: a quote in the interpolated literal would break out of it.
    token_urlsafe and base64 both stay in an alphabet that has none."""
    for _ in range(50):
        pw = repo._generate_password()
        assert "'" not in pw and '"' not in pw
        assert "'" not in repo._scram_sha256_verifier(pw)


# --- role names ----------------------------------------------------------------------------------


def test_derive_role_name_lowercases_a_mixed_case_clerk_id():
    assert repo._derive_role_name("user_2AbcDEF123ghi") == "user_2abcdef123ghi"


def test_derive_role_name_is_deterministic():
    cid = "user_2xYz9"
    assert repo._derive_role_name(cid) == repo._derive_role_name(cid)


def test_derived_role_name_always_passes_validation():
    role = repo._derive_role_name("user_2abcDEFghijkLMNop")
    repo._validate_role_name(role)  # must not raise


@pytest.mark.parametrize("bad", ["", "  ", "1leading_digit", "a", "ab", "has space", 'has"quote', "x" * 64])
def test_validate_role_name_rejects_anything_not_a_safe_identifier(bad):
    with pytest.raises(ValidationError):
        repo._validate_role_name(bad)


def test_quote_ident_wraps_a_validated_name():
    assert repo._q("nexus_rw") == '"nexus_rw"'


def test_quote_ident_refuses_an_invalid_name():
    with pytest.raises(ValidationError):
        repo._q("no; drop table")


# --- denylist ------------------------------------------------------------------------------------


@pytest.mark.parametrize("protected", ["postgres", "nexus_rw", repo._APP_ROLE])
def test_denylist_protects_the_untouchable_roles(protected):
    with pytest.raises(ValidationError):
        repo._assert_manageable(protected)


def test_a_minted_role_name_is_manageable():
    repo._assert_manageable("user_2abc")  # must not raise


# --- connection strings --------------------------------------------------------------------------


def test_connection_strings_embed_the_proxy_coordinates(monkeypatch):
    monkeypatch.setattr(config, "PG_DIRECT_HOST", "switchback.proxy.rlwy.net")
    monkeypatch.setattr(config, "PG_DIRECT_PORT", "28233")
    monkeypatch.setattr(config, "PG_DIRECT_DBNAME", "railway")
    monkeypatch.setattr(config, "PG_DIRECT_SSLMODE", "require")

    strings = repo._connection_strings("user_2abc", "s3cret")

    for s in strings.values():
        assert "Server=switchback.proxy.rlwy.net" in s
        assert "Port=28233" in s
        assert "Database=railway" in s
        assert "Uid=user_2abc" in s
        assert "Pwd=s3cret" in s
        assert "SSLmode=require" in s
    assert strings["adodb_connection_string"].startswith("Provider=MSDASQL;")
    assert strings["access_connection_string"].startswith("ODBC;")


# --- environment gate ----------------------------------------------------------------------------


def test_require_enabled_refuses_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(config, "db_direct_access_enabled", lambda: False)
    with pytest.raises(AppError) as excinfo:
        repo._require_enabled()
    assert excinfo.value.code == "FEATURE_DISABLED"


def test_require_enabled_passes_when_the_feature_is_on(monkeypatch):
    monkeypatch.setattr(config, "db_direct_access_enabled", lambda: True)
    repo._require_enabled()  # must not raise


# --- the pre-mint sweep of unlisted group members (#1865) ----------------------------------------


class _FakeScalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _FakeSession:
    """Just enough of a Session for the sweep: the live registry roles, and what it adds and commits."""

    def __init__(self, listed):
        self.listed = listed
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def connection(self):
        return "conn"

    def scalars(self, _stmt):
        return _FakeScalars(self.listed)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


def test_a_mint_sweeps_every_group_member_the_registry_does_not_list(monkeypatch):
    """A data reset dropped the registry while the roles, cluster-level, lived on in nexus_rw - and the
    next mint re-granted the group DML on every rebuilt table. The sweep drops each one the registry
    does not list, audits it, and leaves the protected roles, a superuser and a hand-made name alone."""
    session = _FakeSession(listed=["user_live"])
    monkeypatch.setattr(repo, "SessionLocal", lambda: session)
    monkeypatch.setattr(
        repo,
        "_group_member_roles",
        lambda conn: [
            ("user_live", False),
            ("user_orphan", False),
            (repo._APP_ROLE, False),
            ("nexus_rw", False),
            ("user_super", True),
            ("HandMade", False),
        ],
    )
    monkeypatch.setattr(repo, "_app_database_count", lambda conn: 1)
    swept = []
    monkeypatch.setattr(repo, "_sweep_role", lambda conn, role: swept.append(role))

    assert repo._sweep_unlisted_members(actor_clerk_id="user_actor") == ["user_orphan"]

    assert swept == ["user_orphan"]
    assert session.committed
    [audit] = session.added
    assert (audit.action, audit.db_role, audit.target_clerk_id, audit.actor_clerk_id) == (
        "REVOKE",
        "user_orphan",
        None,
        "user_actor",
    )


def test_nothing_is_swept_on_a_cluster_another_database_shares(monkeypatch):
    """The registry is this database's and the roles the cluster's: an unlisted login may be another
    database's, live."""
    session = _FakeSession(listed=[])
    monkeypatch.setattr(repo, "SessionLocal", lambda: session)
    monkeypatch.setattr(repo, "_app_database_count", lambda conn: 2)
    monkeypatch.setattr(repo, "_group_member_roles", lambda conn: [("user_orphan", False)])
    swept = []
    monkeypatch.setattr(repo, "_sweep_role", lambda conn, role: swept.append(role))

    assert repo._sweep_unlisted_members(actor_clerk_id="user_actor") == []
    assert swept == []


def test_a_mint_sweeps_before_the_group_is_granted(monkeypatch):
    """The order is the fix: a sweep after `_ensure_group` would leave the orphans holding the grants for
    as long as the mint took, and for good if the mint then failed."""
    monkeypatch.setattr(config, "db_direct_access_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(repo, "_sweep_unlisted_members", lambda *, actor_clerk_id: calls.append("sweep"))

    def _ensure_group():
        calls.append("grant")
        raise RuntimeError("stop here")

    monkeypatch.setattr(repo, "_ensure_group", _ensure_group)

    with pytest.raises(RuntimeError):
        repo.mint("user_2abc", actor_clerk_id="user_actor")

    assert calls == ["sweep", "grant"]


# --- the tables the group can't touch (#1867) -----------------------------------------------------


class _RecordingConn:
    def __init__(self):
        self.statements = []

    def exec_driver_sql(self, sql):
        self.statements.append(" ".join(sql.split()))


def test_the_group_grant_is_taken_back_off_the_registry_the_audit_and_alembic_version(monkeypatch):
    """The blanket DML grant reached the registry (a login could list itself), the audit (or erase who
    handed it out) and alembic_version. The REVOKE comes after the grant, so every re-run takes it back."""
    conn = _RecordingConn()
    session = _FakeSession(listed=[])
    session.connection = lambda: conn
    monkeypatch.setattr(repo, "SessionLocal", lambda: session)

    repo._ensure_group()

    grant = next(
        i for i, s in enumerate(conn.statements) if s.startswith("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL")
    )
    [revoke] = [i for i, s in enumerate(conn.statements) if s.startswith("REVOKE")]
    assert revoke > grant
    assert conn.statements[revoke] == (
        'REVOKE ALL ON TABLE public."pg_direct_access", public."pg_direct_access_audit", '
        'public."alembic_version" FROM "nexus_rw"'
    )
    assert session.committed


# --- a holder who lost UC Nexus Admin (#1866) ----------------------------------------------------


def test_the_grid_flags_a_login_whose_holder_lost_the_admin_role(monkeypatch):
    """Mint grants only to a UC Nexus Admin (#729), but nothing followed the holder losing the role: the
    login lived on unmarked. Flagged, not revoked - that awaits a ruling."""
    from datetime import datetime as _dt

    from app.auth import NEXUS_ADMIN_ROLE
    from app.models.pg_direct_access import PgDirectAccess

    rows = [
        PgDirectAccess(db_role=r, clerk_user_id=r, created_by="a", created_at=_dt(2026, 1, 1))
        for r in ("user_still", "user_lost", "user_gone")
    ]
    monkeypatch.setattr(config, "db_direct_access_enabled", lambda: True)
    monkeypatch.setattr(repo, "SessionLocal", lambda: _FakeSession(listed=rows))
    monkeypatch.setattr(repo, "_live_member_roles", lambda conn: {"user_still", "user_lost", "user_gone"})
    roster = [
        {"id": "user_still", "roles": [NEXUS_ADMIN_ROLE]},
        {"id": "user_lost", "roles": ["Purchasing"]},
    ]

    by_role = {d["db_role"]: d for d in repo.list_admins(roster)}

    assert by_role["user_still"]["lost_admin_role"] is False
    assert by_role["user_lost"]["lost_admin_role"] is True
    # Gone from Clerk is its own flag, not this one.
    assert by_role["user_gone"]["lost_admin_role"] is False
    assert by_role["user_gone"]["clerk_missing"] is True


def _rotate(monkeypatch, roster):
    from app.auth import NEXUS_ADMIN_ROLE
    from app.schemas.db_access import DbAccessMutations

    monkeypatch.setattr(config, "db_direct_access_enabled", lambda: True)
    monkeypatch.setattr(repo, "live_holder", lambda db_role: "user_holder")
    rotated = []

    def fake_rotate(db_role, *, actor_clerk_id):
        rotated.append(db_role)
        return {
            "db_role": db_role,
            "clerk_user_id": "user_holder",
            "adodb_connection_string": "a",
            "access_connection_string": "b",
        }

    monkeypatch.setattr(repo, "rotate", fake_rotate)
    monkeypatch.setattr("app.schemas.db_access.current_user", lambda info: {"user_id": "user_actor"})

    class Info:
        context = {"request": None, "_auth_roles": ["DB Admin", NEXUS_ADMIN_ROLE], "_auth_user_roster": roster}

    return rotated, lambda: DbAccessMutations().rotate_postgres_admin(Info(), db_role="user_holder")


@pytest.mark.parametrize("roster", [[{"id": "user_holder", "roles": ["Purchasing"]}], []], ids=["demoted", "gone"])
def test_rotate_refuses_a_login_whose_holder_no_longer_holds_the_admin_role(monkeypatch, roster):
    """A fresh password would hand the access back to someone no longer trusted with it (#1866)."""
    rotated, call = _rotate(monkeypatch, roster)

    with pytest.raises(ValidationError, match="no longer holds"):
        call()
    assert rotated == []


def test_rotate_still_rotates_an_admins_login(monkeypatch):
    from app.auth import NEXUS_ADMIN_ROLE

    rotated, call = _rotate(monkeypatch, [{"id": "user_holder", "roles": [NEXUS_ADMIN_ROLE]}])

    assert call().db_role == "user_holder"
    assert rotated == ["user_holder"]
