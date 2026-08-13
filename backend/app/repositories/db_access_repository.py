"""Mint, list, rotate and revoke per-user Postgres logins (db-admin-postgres-access).

Every login is a personal role, member of a `nexus_rw` group that carries read-write (DML) on schema
`public` and nothing more - no superuser, no DDL. The role DDL runs on the app's existing superuser
connection (the same `engine` the rest of the backend uses), guard-railed here rather than in the UI:

- role names are identifiers and CANNOT be bound parameters, so each is validated against a strict
  regex and identifier-quoted before it reaches a statement;
- passwords cannot be bound either (CREATE ROLE / ALTER ROLE are utility statements, and Postgres
  rejects bind parameters in them), and a plaintext literal would also be disclosed by
  `log_min_error_statement` if the statement failed - so the statement never carries the password.
  The backend generates it, computes the SCRAM-SHA-256 verifier itself (RFC 5802/7677, stdlib only),
  and interpolates THAT as the quoted literal. A logged verifier authenticates nobody;
- every rotate/revoke target must be present in the registry; a hard denylist keeps `postgres`, the
  app's own role and the shared group untouchable, and a superuser role is refused outright.

The password is returned once, in the mint/rotate response, and exists nowhere else we control - only
as a SCRAM hash in Postgres, never in a stored column and never in a SQL statement.
"""

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from app import config
from app.database import SessionLocal
from app.errors import AppError, ConflictError, NotFoundError, ValidationError
from app.models.pg_direct_access import PgDirectAccess, PgDirectAccessAudit

# The group every minted login joins. NOLOGIN itself; it only carries the DML grants.
_GROUP_ROLE = "nexus_rw"

# Postgres identifier shape we allow to reach a statement. Lowercase-only (Clerk ids are mixed-case,
# so a derived name is lowercased first), 3-63 chars, leading letter/underscore. The regex is the
# whole reason a role name is safe to interpolate: nothing matching it can contain a quote.
_ROLE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{2,62}$")

# Blast-radius caps on a minted login. The connection limit is server-enforced; the two timeouts are
# session-default GUCs a login could SET away, which is the right shape against the accidents they
# target (a stuck Access client, a runaway ad-hoc query, an ODBC client idling in an open transaction)
# rather than an adversary - a minted login is a trusted admin.
_CONNECTION_LIMIT = 5
_STATEMENT_TIMEOUT = "60s"
_IDLE_TX_TIMEOUT = "60s"

# RFC 5802 default; also Postgres' own default for a SCRAM verifier.
_SCRAM_ITERATIONS = 4096

# The role that runs migrations (and therefore owns future tables), for ALTER DEFAULT PRIVILEGES. On
# Railway this is `postgres`; parsed from DATABASE_URL so it follows a differently-named cluster.
_APP_ROLE = (make_url(config.DATABASE_URL).username or "postgres").lower()

# Never manageable from this page, whatever the registry says: the superuser, the app's own account,
# and the shared group. The page can never be aimed at the account the backend itself runs as.
_DENYLIST = {"postgres", _GROUP_ROLE} | {_APP_ROLE}


# --- identifiers, passwords, connection strings --------------------------------------------------


def _validate_role_name(role: str) -> None:
    if not _ROLE_NAME_RE.fullmatch(role):
        raise ValidationError(f"{role!r} is not a valid managed role name.")


def _q(identifier: str) -> str:
    """Identifier-quote a role name. Only ever called on a name already through `_validate_role_name`,
    so the doubled-quote is belt-and-braces - nothing matching the regex contains one."""
    _validate_role_name(identifier)
    return '"' + identifier.replace('"', '""') + '"'


def _derive_role_name(clerk_user_id: str) -> str:
    """A deterministic role name for a Clerk user. Lowercased (the regex is), non-conforming chars
    mapped to `_` (Clerk ids are alphanumeric after `user_`, so this is defensive). Deterministic so a
    re-mint after a revoke lands on exactly the same name - the live-grant refusal and the pre-sweep
    together make that safe."""
    role = re.sub(r"[^a-z0-9_]", "_", (clerk_user_id or "").lower())
    if not _ROLE_NAME_RE.fullmatch(role):
        raise ValidationError(f"Cannot derive a valid Postgres role name from {clerk_user_id!r}.")
    return role


def _generate_password() -> str:
    """A URL-safe token: base64url alphabet, so no quote can appear and the SCRAM verifier built from
    it stays a safe SQL literal for the same reason."""
    return secrets.token_urlsafe(24)


def _scram_sha256_verifier(password: str, *, iterations: int = _SCRAM_ITERATIONS) -> str:
    """The SCRAM-SHA-256 verifier Postgres stores for a password (RFC 5802/7677), computed with the
    stdlib. Postgres stores a presented verifier verbatim when the literal is in this format, so we
    never send it the plaintext.

    Format: ``SCRAM-SHA-256$<iterations>:<b64 salt>$<b64 StoredKey>:<b64 ServerKey>``."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()

    def _b64(raw: bytes) -> str:
        return base64.b64encode(raw).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{_b64(salt)}${_b64(stored_key)}:{_b64(server_key)}"


def _connection_strings(role: str, password: str) -> dict:
    """The ADODB and ODBC (MS Access linked-table) connection strings for a minted login, built from
    the public-proxy coordinates. The password is present here and nowhere else we keep."""
    common = (
        f"Driver={{PostgreSQL Unicode}};Server={config.PG_DIRECT_HOST};Port={config.PG_DIRECT_PORT};"
        f"Database={config.PG_DIRECT_DBNAME};Uid={role};Pwd={password};SSLmode={config.PG_DIRECT_SSLMODE};"
    )
    return {
        "adodb_connection_string": f"Provider=MSDASQL;{common}",
        "access_connection_string": f"ODBC;{common}",
    }


# --- cluster inspection --------------------------------------------------------------------------


def _role_exists(conn, role: str) -> bool:
    return conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first() is not None


def _assert_not_superuser(conn, role: str) -> None:
    row = conn.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
    if row is not None and row[0]:
        raise ValidationError(f"{role!r} is a superuser role and cannot be managed here.")


def _is_group_member(conn, role: str) -> bool:
    """Whether `role` exists and is a member of nexus_rw. A join on pg_auth_members rather than
    pg_has_role, which errors on a role that does not exist - this must answer False, not raise."""
    return (
        conn.execute(
            text(
                """
                SELECT 1
                  FROM pg_roles r
                  JOIN pg_auth_members m ON m.member = r.oid
                  JOIN pg_roles g ON g.oid = m.roleid
                 WHERE r.rolname = :r AND g.rolname = :grp
                """
            ),
            {"r": role, "grp": _GROUP_ROLE},
        ).first()
        is not None
    )


def _live_member_roles(conn) -> set[str]:
    """Every role that can log in AND is a member of nexus_rw - the set that reads as 'active' in the
    grid, so a registry row whose role was dropped out from under it shows as missing instead."""
    rows = conn.execute(
        text(
            """
            SELECT r.rolname
              FROM pg_roles r
              JOIN pg_auth_members m ON m.member = r.oid
              JOIN pg_roles g ON g.oid = m.roleid
             WHERE g.rolname = :grp AND r.rolcanlogin
            """
        ),
        {"grp": _GROUP_ROLE},
    ).all()
    return {row[0] for row in rows}


def _sweep_role(conn, role: str) -> None:
    """Terminate the role's live sessions, then drop everything it owns and the role itself - the
    tolerant cleanup both revoke and the pre-mint sweep run.

    Guarded by an existence check because DROP OWNED BY has no IF EXISTS form and would error on a
    role that is not there (a first-ever mint, or a revoke closing out a role already gone). The same
    guard is what makes both callers safe on a half-gone role."""
    if not _role_exists(conn, role):
        return
    conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = :r"), {"r": role})
    # exec_driver_sql, not text(): these are interpolated DDL with no bind params, and text() would try
    # to parse any ":" in them as a bind. Same reason the PASSWORD statements below use it.
    conn.exec_driver_sql(f"DROP OWNED BY {_q(role)}")
    conn.exec_driver_sql(f"DROP ROLE IF EXISTS {_q(role)}")


# --- group setup ---------------------------------------------------------------------------------


def _ensure_group() -> None:
    """Idempotently create nexus_rw and (re)apply its grants: USAGE on public, DML on all tables,
    USAGE/SELECT on all sequences, plus ALTER DEFAULT PRIVILEGES for tables AND sequences so objects
    future migrations create stay reachable. The sequence grants are not optional - without them every
    insert into an identity-pk table fails.

    Kept out of Alembic on purpose: roles are cluster-level and would collide across the PR-env clones
    and CI runs that share a cluster."""
    app_role = _q(_APP_ROLE)
    grp = _q(_GROUP_ROLE)
    with SessionLocal() as session:
        # exec_driver_sql throughout: interpolated DDL with no bind params, so text()'s ":" bind parsing
        # must not run over it. The CREATE is wrapped in an EXCEPTION handler rather than a bare
        # IF NOT EXISTS - the check-then-create is not atomic, so two first-ever mints racing could both
        # see the role absent and both CREATE; catching duplicate_object makes the loser a no-op.
        conn = session.connection()
        conn.exec_driver_sql(
            f"""
            DO $$
            BEGIN
                CREATE ROLE {_GROUP_ROLE} NOLOGIN;
            EXCEPTION WHEN duplicate_object THEN
                NULL;
            END
            $$
            """
        )
        conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {grp}")
        conn.exec_driver_sql(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {grp}")
        conn.exec_driver_sql(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {grp}")
        conn.exec_driver_sql(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {app_role} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {grp}"
        )
        conn.exec_driver_sql(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {app_role} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {grp}"
        )
        session.commit()


# --- guards --------------------------------------------------------------------------------------


def _require_enabled() -> None:
    if not config.db_direct_access_enabled():
        raise AppError("Direct database access is not enabled in this environment.", "FEATURE_DISABLED")


def _assert_manageable(role: str) -> None:
    """The static half of the denylist: `postgres`, the app's own role, the shared group. The dynamic
    half (a superuser) is checked against the cluster once a connection is open."""
    _validate_role_name(role)
    if role in _DENYLIST:
        raise ValidationError(f"{role!r} is a protected role and cannot be managed here.")


def _display_name(user: dict | None) -> str | None:
    if not user:
        return None
    full = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
    return full or user.get("email") or user.get("id")


# --- the five operations -------------------------------------------------------------------------


def mint(clerk_user_id: str, *, actor_clerk_id: str) -> dict:
    """Mint a login for a Clerk user and return its connection strings once.

    Ensures the group, refuses if the user already has a live grant, sweeps any orphan the deterministic
    name would collide with, then creates + configures the role and writes the registry row and a MINT
    audit event - the role DDL and the registry insert in ONE transaction, so a lost race rolls the
    role back with the row and leaves no orphan."""
    _require_enabled()
    role = _derive_role_name(clerk_user_id)
    _assert_manageable(role)
    _ensure_group()

    password = _generate_password()
    verifier = _scram_sha256_verifier(password)

    with SessionLocal() as session:
        # Live-grant refusal FIRST, so the sweep below only ever hits a role the registry says should
        # not exist.
        existing = session.scalar(
            select(PgDirectAccess).where(
                PgDirectAccess.clerk_user_id == clerk_user_id,
                PgDirectAccess.revoked_at.is_(None),
            )
        )
        if existing:
            raise ConflictError("This user already has a live database login. Rotate it instead.")

        # Two distinct Clerk ids can only derive the same role name if they differ solely in letter
        # case (unreachable with today's alphanumeric ids), but refuse cleanly if it ever happens
        # rather than letting the sweep below drop the other user's live role and then roll back on the
        # db_role partial-unique with an opaque IntegrityError.
        role_taken = session.scalar(
            select(PgDirectAccess).where(
                PgDirectAccess.db_role == role,
                PgDirectAccess.clerk_user_id != clerk_user_id,
                PgDirectAccess.revoked_at.is_(None),
            )
        )
        if role_taken:
            raise ConflictError("That database role name is already in use by another user.")

        conn = session.connection()
        _assert_not_superuser(conn, role)
        # The deterministic name may land on an orphan a prior imperfect revoke left behind (its DROP
        # failed after the registry row closed); without this, CREATE ROLE would be a duplicate-role
        # error no UI action can clear.
        _sweep_role(conn, role)

        # exec_driver_sql, not text(): the SCRAM verifier's StoredKey base64 ends in "=", so the ":"
        # before its ServerKey would be read by text() as a phantom required bind and raise before the
        # statement reached Postgres. exec_driver_sql skips bind parsing, and the verifier carries no "%".
        conn.exec_driver_sql(f"CREATE ROLE {_q(role)} LOGIN CONNECTION LIMIT {_CONNECTION_LIMIT} PASSWORD '{verifier}'")
        conn.exec_driver_sql(f"ALTER ROLE {_q(role)} SET statement_timeout = '{_STATEMENT_TIMEOUT}'")
        conn.exec_driver_sql(f"ALTER ROLE {_q(role)} SET idle_in_transaction_session_timeout = '{_IDLE_TX_TIMEOUT}'")
        conn.exec_driver_sql(f"GRANT {_q(_GROUP_ROLE)} TO {_q(role)}")

        session.add(PgDirectAccess(db_role=role, clerk_user_id=clerk_user_id, created_by=actor_clerk_id))
        session.add(
            PgDirectAccessAudit(
                actor_clerk_id=actor_clerk_id, action="MINT", db_role=role, target_clerk_id=clerk_user_id
            )
        )
        session.commit()

    return {"db_role": role, "clerk_user_id": clerk_user_id, **_connection_strings(role, password)}


def list_admins(roster: list[dict]) -> list[dict]:
    """The live registry joined to the Clerk roster for names and emails, with a cluster cross-check
    for status. A row whose user has left Clerk stays in the list flagged, never dropped - it is the
    login most in need of a revoke."""
    _require_enabled()
    roster_by_id = {u["id"]: u for u in roster}
    with SessionLocal() as session:
        rows = session.scalars(
            select(PgDirectAccess).where(PgDirectAccess.revoked_at.is_(None)).order_by(PgDirectAccess.created_at.desc())
        ).all()
        live_roles = _live_member_roles(session.connection())
        result = []
        for r in rows:
            u = roster_by_id.get(r.clerk_user_id)
            result.append(
                {
                    "db_role": r.db_role,
                    "clerk_user_id": r.clerk_user_id,
                    "display_name": _display_name(u),
                    "email": u.get("email") if u else None,
                    "clerk_missing": u is None,
                    "active": r.db_role in live_roles,
                    "created_at": r.created_at,
                    "last_rotated_at": r.last_rotated_at,
                }
            )
        return result


def rotate(db_role: str, *, actor_clerk_id: str) -> dict:
    """A fresh password for an existing login, returned once. Requires the role to be present in the
    registry AND a live nexus_rw member - if it is not, revoke and re-mint instead. Sessions open on
    the old password persist until they reconnect; same person, so that is fine."""
    _require_enabled()
    _assert_manageable(db_role)
    with SessionLocal() as session:
        row = session.scalar(
            select(PgDirectAccess).where(
                PgDirectAccess.db_role == db_role,
                PgDirectAccess.revoked_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("No live database login for that role.")

        conn = session.connection()
        _assert_not_superuser(conn, db_role)
        if not _is_group_member(conn, db_role):
            raise ConflictError("That role is not a live nexus_rw member. Revoke it and re-mint instead.")

        password = _generate_password()
        verifier = _scram_sha256_verifier(password)
        # exec_driver_sql, not text(): the verifier's ":" separators would be misread as binds. See mint.
        conn.exec_driver_sql(f"ALTER ROLE {_q(db_role)} PASSWORD '{verifier}'")

        row.last_rotated_at = datetime.utcnow()
        session.add(
            PgDirectAccessAudit(
                actor_clerk_id=actor_clerk_id, action="ROTATE", db_role=db_role, target_clerk_id=row.clerk_user_id
            )
        )
        session.commit()
        clerk_user_id = row.clerk_user_id

    return {"db_role": db_role, "clerk_user_id": clerk_user_id, **_connection_strings(db_role, password)}


def revoke(db_role: str, *, actor_clerk_id: str) -> dict:
    """End a login now: terminate its live sessions, drop what it owns, drop the role, and close its
    registry row. Deliberately tolerant - a role already half-gone still gets `revoked_at` set, because
    a strict existence check would brick cleanup of exactly the rows most needing it. The registry
    presence check still comes first, so this only ever acts on a row the registry says is live."""
    _require_enabled()
    _assert_manageable(db_role)
    with SessionLocal() as session:
        row = session.scalar(
            select(PgDirectAccess).where(
                PgDirectAccess.db_role == db_role,
                PgDirectAccess.revoked_at.is_(None),
            )
        )
        if row is None:
            raise NotFoundError("No live database login for that role.")

        conn = session.connection()
        _assert_not_superuser(conn, db_role)
        _sweep_role(conn, db_role)

        row.revoked_at = datetime.utcnow()
        session.add(
            PgDirectAccessAudit(
                actor_clerk_id=actor_clerk_id, action="REVOKE", db_role=db_role, target_clerk_id=row.clerk_user_id
            )
        )
        session.commit()
        clerk_user_id = row.clerk_user_id

    return {"db_role": db_role, "clerk_user_id": clerk_user_id}


def list_audit(roster: list[dict], *, limit: int = 200) -> list[dict]:
    """The audit table newest-first, actor and target resolved against the roster for display names."""
    _require_enabled()
    roster_by_id = {u["id"]: u for u in roster}
    with SessionLocal() as session:
        rows = session.scalars(
            select(PgDirectAccessAudit).order_by(PgDirectAccessAudit.created_at.desc()).limit(limit)
        ).all()
        return [
            {
                "id": r.id,
                "action": r.action,
                "db_role": r.db_role,
                "actor_clerk_id": r.actor_clerk_id,
                "actor_name": _display_name(roster_by_id.get(r.actor_clerk_id)),
                "target_clerk_id": r.target_clerk_id,
                "target_name": _display_name(roster_by_id.get(r.target_clerk_id)) if r.target_clerk_id else None,
                "created_at": r.created_at,
            }
            for r in rows
        ]
