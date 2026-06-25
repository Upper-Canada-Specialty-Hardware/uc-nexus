"""pyodbc connection factory. Windows SSPI auth (Trusted_Connection) — no password stored.

autocommit=False on the orchestration connection is critical: we want one explicit
BEGIN..COMMIT/ROLLBACK scope across the multi-proc PO create.
"""

from contextlib import contextmanager

import pyodbc

from .config import get_settings


def build_conn_string(company: str) -> str:
    s = get_settings().sql
    parts = [
        f"DRIVER={{{s.driver}}}",
        f"SERVER={s.server}",
        f"DATABASE={company}",
    ]
    if s.trusted_connection:
        parts.append("Trusted_Connection=yes")
    parts.append(f"Encrypt={s.encrypt}")
    if s.trust_server_certificate:
        parts.append("TrustServerCertificate=yes")
    parts.append(f"Connection Timeout={s.connection_timeout}")
    return ";".join(parts) + ";"


def driver_available() -> bool:
    target = get_settings().sql.driver
    return any(target in d for d in pyodbc.drivers())


@contextmanager
def get_connection(company: str):
    """Transactional connection for eConnect orchestration (autocommit off)."""
    conn = pyodbc.connect(build_conn_string(company), autocommit=False)
    conn.timeout = get_settings().sql.command_timeout
    # SET NOCOUNT ON for the whole session: eConnect procs do heavy internal DML, and the
    # "(N rows affected)" count messages otherwise push our trailing `SELECT @err` off pyodbc's
    # first result set -> "No results. Previous SQL was not a query." NOCOUNT suppresses the
    # count tokens only; real SELECT result sets (our error read + read-backs) are unaffected.
    conn.cursor().execute("SET NOCOUNT ON")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_read_connection(company: str):
    """Read-only connection (autocommit) for plain SELECTs — no eConnect, no writes, no held
    transaction. Used by /vendors and any other pure read."""
    conn = pyodbc.connect(build_conn_string(company), autocommit=True)
    conn.timeout = get_settings().sql.command_timeout
    try:
        yield conn
    finally:
        conn.close()


def connection_info(company: str) -> dict:
    """Read-only identity probe for /info. Opens an autocommit connection, runs a
    metadata SELECT, returns who we are. No eConnect calls, no writes."""
    with pyodbc.connect(build_conn_string(company), autocommit=True) as conn:
        row = conn.cursor().execute(
            "SELECT SUSER_NAME() AS login, DB_NAME() AS db, @@VERSION AS ver, IS_MEMBER('DYNGRP') AS dyngrp"
        ).fetchone()
        return {
            "connected_as": row.login,
            "database": row.db,
            "sql_version": row.ver.splitlines()[0].strip(),
            "is_member_dyngrp": bool(row.dyngrp),
        }
