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
