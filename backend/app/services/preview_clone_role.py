"""Production's half of the preview clone: the read-only login previews dump through.

A preview environment clones production's database (app/preview_clone.py) over the public Postgres
proxy, which means it needs a login on production's cluster. That login is created HERE, by
production itself at startup, from `PREVIEW_CLONE_PASSWORD` - the same variable a Railway fork
inherits. One variable therefore both mints the credential and hands it to every environment that
needs it, and rotating it is a variable edit plus a production restart rather than a manual
psql session nobody can run from this machine anyway.

The role gets `pg_read_all_data` and nothing else. It can SELECT, and that is the whole of what
pg_dump needs; it cannot write, cannot DDL, and is not a superuser.

Role DDL cannot take bind parameters (CREATE ROLE / ALTER ROLE are utility statements), so this
follows the pattern app/repositories/db_access_repository.py already established for exactly that
problem: the identifier is regex-validated and identifier-quoted through `_q`, and the password never
appears in a statement at all - what is interpolated is the SCRAM-SHA-256 verifier computed here from
it. A verifier in a log line authenticates nobody.

Never blocks startup. A cluster that refuses the DDL (an unexpected permission setup, a Postgres
version without pg_read_all_data) means previews cannot clone, which is a degraded preview, not a
degraded production.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app import config
from app.repositories.db_access_repository import _q, _scram_sha256_verifier

logger = logging.getLogger(__name__)

# Predefined since Postgres 14; production runs 17. Carries SELECT on every table in every database
# object the role can reach, which is what pg_dump needs and the smallest grant that covers it.
_READ_ALL_ROLE = "pg_read_all_data"


def enabled() -> bool:
    """Only production, and only when a password has been set. Everywhere else this is a no-op with
    no log line - a preview, CI and a local checkout have nothing to mint and nothing to warn about."""
    return config.is_production_environment() and bool(config.PREVIEW_CLONE_PASSWORD.strip())


def _statements(role: str, verifier: str, *, exists: bool) -> list[str]:
    """The DDL, in order. Split out from the execution so a test can assert the text without a
    cluster: this is a place where getting the quoting wrong is the whole risk."""
    quoted = _q(role)
    if exists:
        # ALTER rather than CREATE so a rotated password lands on the role already holding grants,
        # and so a restart is idempotent rather than a duplicate-role error.
        first = f"ALTER ROLE {quoted} WITH LOGIN PASSWORD '{verifier}'"
    else:
        first = f"CREATE ROLE {quoted} LOGIN PASSWORD '{verifier}'"
    # Re-granted every time. GRANT of a role already held is a no-op, and it repairs a role somebody
    # revoked by hand.
    return [first, f"GRANT {_READ_ALL_ROLE} TO {quoted}"]


def ensure_role() -> None:
    """Create or update the preview_clone login. Raises on failure; `ensure_role_on_startup` swallows."""
    from app.database import SessionLocal

    role = config.PREVIEW_CLONE_ROLE
    _q(role)  # validates the name before anything is interpolated anywhere below
    verifier = _scram_sha256_verifier(config.PREVIEW_CLONE_PASSWORD.strip())
    with SessionLocal() as session:
        conn = session.connection()
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first() is not None
        for statement in _statements(role, verifier, exists=exists):
            # exec_driver_sql, not text(): the verifier's base64 StoredKey ends in "=" and its ":"
            # separators would be read by text() as bind parameters. Same reason db_access_repository
            # uses it for every PASSWORD statement.
            conn.exec_driver_sql(statement)
        session.commit()
    logger.info("preview clone role %s is %s with %s", role, "updated" if exists else "created", _READ_ALL_ROLE)


def ensure_role_on_startup() -> None:
    """Lifespan hook. Silent everywhere but production, and never fatal."""
    if not enabled():
        return
    try:
        ensure_role()
    except Exception as e:
        logger.warning(
            "could not ensure the %s login, so preview environments cannot clone this database: %s",
            config.PREVIEW_CLONE_ROLE,
            e,
        )
