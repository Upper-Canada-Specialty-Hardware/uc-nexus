"""pyodbc connection factory. Windows SSPI auth (Trusted_Connection) - no password stored.

autocommit=False on the orchestration connection is critical: we want one explicit
BEGIN..COMMIT/ROLLBACK scope across the multi-proc PO create.

Every connection also carries APP=UCNexusRelay and is measured against the GP server's OWN accounting
of the session it opened - see the cost section below.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

import pyodbc

from .config import get_settings
from .logging_setup import get_logger

logger = get_logger()

# ODBC "Application Name" (the APP keyword). It lands in sys.dm_exec_sessions.program_name and in
# Activity Monitor, so everything this relay costs the GP server is attributable to Nexus rather than
# showing up as one more anonymous "Microsoft SQL Server" session. A 15-hour CPU pin nobody could
# attribute from either side is why this is here.
APP_NAME = "UCNexusRelay"


def build_conn_string(company: str) -> str:
    s = get_settings().sql
    parts = [
        f"DRIVER={{{s.driver}}}",
        f"SERVER={s.server}",
        f"DATABASE={company}",
        f"APP={APP_NAME}",
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


# --- what an op costs the GP server -------------------------------------------------------------
#
# sys.dm_exec_sessions carries cpu_time (ms), logical_reads and total_elapsed_time (ms) per session,
# and a session may read its OWN row (session_id = @@SPID) without VIEW SERVER STATE - so this needs
# no extra grant on the GP login.
#
# Those three are CUMULATIVE for the life of the SESSION, not per statement, and pyodbc pools
# connections by default: the "connection" an op opens may be a session an earlier op already ran on.
# So only the DELTA between the open reading and the close reading belongs to the op.
#
# None of it may fail an op. Both reads are wrapped; a server that will not answer means this op is
# simply not counted, and the reason is logged once per process at DEBUG.

_SESSION_COST_SQL = (
    "SELECT cpu_time, logical_reads, total_elapsed_time FROM sys.dm_exec_sessions WHERE session_id = @@SPID"
)

class Measured:
    """What one op is being measured as, and what it turned out to cost.

    `cost` sums EVERY connection opened inside the block, because an op that opens two (create_po and
    then the eConnect description lookup on the way out) cost the server both. It stays None until a
    delta actually landed - a reply says "not measured" with null rather than with a zero, which would
    read as a free op."""

    __slots__ = ("op", "company", "cpu_ms", "logical_reads", "elapsed_ms", "connections")

    def __init__(self, op: str, company: str):
        self.op = op
        self.company = company
        self.cpu_ms = 0
        self.logical_reads = 0
        self.elapsed_ms = 0
        self.connections = 0

    def add(self, cpu_ms: int, logical_reads: int, elapsed_ms: int) -> None:
        # No lock: a handler is synchronous and every connection it opens is opened on its own thread,
        # so this object is only ever touched by the one thread its context belongs to.
        self.cpu_ms += cpu_ms
        self.logical_reads += logical_reads
        self.elapsed_ms += elapsed_ms
        self.connections += 1

    @property
    def cost(self) -> dict | None:
        """The `cost` block on a job reply, or None if no measurement happened."""
        if not self.connections:
            return None
        return {"cpu_ms": self.cpu_ms, "logical_reads": self.logical_reads, "elapsed_ms": self.elapsed_ms}


# Which op the connections opened on this thread belong to. channel._dispatch sets it around the
# handler call and main.py's middleware sets it around an HTTP request, so db.py can name a cost
# without every call site threading an op name through. asyncio.to_thread and Starlette's threadpool
# both copy the caller's context into the worker thread, so a value set either side reaches here.
_CURRENT_OP: ContextVar[Measured | None] = ContextVar("gp_current_op", default=None)

_UNKNOWN_OP = "unknown"

# Ops run on worker threads, so the totals need a lock. `_COST_SINCE` is process start (import time).
_COST_LOCK = threading.Lock()
_COST_SINCE = datetime.now(timezone.utc)
_COST: dict[str, dict] = {}
_COST_UNAVAILABLE_LOGGED = False


@contextmanager
def measuring(op: str, company: str):
    """Name the op that every connection opened inside this block is measured against, and yield the
    Measured that collects what it cost - channel._dispatch reads `.cost` off it for the reply."""
    measured = Measured(op, company)
    token = _CURRENT_OP.set(measured)
    try:
        yield measured
    finally:
        _CURRENT_OP.reset(token)


def _sample(conn) -> tuple[int, int, int] | None:
    """(cpu_ms, logical_reads, elapsed_ms) for this connection's own session, or None if the reading
    could not be taken.

    Runs on the connection being measured - never a second one. On a manual-commit connection the
    SELECT opens an implicit transaction, so it is rolled back straight away: the op's transaction
    scope has to be exactly what it was before the measurement existed, and at both call sites the
    op's own work is already committed or rolled back (or has not started yet)."""
    global _COST_UNAVAILABLE_LOGGED
    try:
        row = conn.cursor().execute(_SESSION_COST_SQL).fetchone()
        if not getattr(conn, "autocommit", True):
            conn.rollback()
        if row is None:
            return None
        return int(row[0]), int(row[1]), int(row[2])
    except Exception as e:
        with _COST_LOCK:
            first = not _COST_UNAVAILABLE_LOGGED
            _COST_UNAVAILABLE_LOGGED = True
        if first:
            logger.debug(
                "gp cost measurement unavailable",
                extra={"category": "gp_cost_unavailable", "error": str(e)},
            )
        return None


def _record(company: str, op: str, cpu_ms: int, logical_reads: int, elapsed_ms: int) -> None:
    with _COST_LOCK:
        totals = _COST.setdefault(
            company, {"ops": 0, "cpu_ms": 0, "logical_reads": 0, "elapsed_ms": 0, "by_op": {}}
        )
        per_op = totals["by_op"].setdefault(op, {"ops": 0, "cpu_ms": 0, "logical_reads": 0, "elapsed_ms": 0})
        for bucket in (totals, per_op):
            bucket["ops"] += 1
            bucket["cpu_ms"] += cpu_ms
            bucket["logical_reads"] += logical_reads
            bucket["elapsed_ms"] += elapsed_ms
    logger.info(
        "gp cost",
        extra={
            "category": "gp_cost",
            "company": company,
            "op": op,
            "cpu_ms": cpu_ms,
            "logical_reads": logical_reads,
            "elapsed_ms": elapsed_ms,
        },
    )


def _record_delta(conn, company: str, opened: tuple[int, int, int] | None) -> None:
    """Close-side half of the measurement: read the session again and book the difference. Nothing is
    recorded unless BOTH readings came back - half a delta is worse than no number at all."""
    if opened is None:
        return
    closed = _sample(conn)
    if closed is None:
        return
    measured = _CURRENT_OP.get()
    # Clamped: a pooled session that was reset between the two readings would otherwise book a
    # negative and quietly eat somebody else's total.
    cpu_ms, logical_reads, elapsed_ms = (max(0, c - o) for c, o in zip(closed, opened))
    if measured is not None:
        measured.add(cpu_ms, logical_reads, elapsed_ms)
    op = measured.op if measured is not None else _UNKNOWN_OP
    _record((measured.company if measured is not None else "") or company, op, cpu_ms, logical_reads, elapsed_ms)


def cost_snapshot() -> dict:
    """The gp_cost block /health publishes: per company and per (company, op) totals since process
    start. Copied out under the lock rather than handed over live - /health is a sync def served on a
    threadpool worker while GP ops keep running on their own threads, and serialising a dict another
    thread is mutating is the same bug channel.channel_state_snapshot guards against."""
    with _COST_LOCK:
        return {
            "since": _COST_SINCE.isoformat(timespec="seconds"),
            "companies": {
                company: {
                    "ops": totals["ops"],
                    "cpu_ms": totals["cpu_ms"],
                    "logical_reads": totals["logical_reads"],
                    "elapsed_ms": totals["elapsed_ms"],
                    "by_op": {op: dict(per_op) for op, per_op in totals["by_op"].items()},
                }
                for company, totals in _COST.items()
            },
        }


def reset_cost() -> None:
    """Empty the totals. For tests - the accumulator is module-level and would otherwise carry one
    test's ops into the next one's assertions."""
    global _COST_SINCE, _COST_UNAVAILABLE_LOGGED
    with _COST_LOCK:
        _COST.clear()
        _COST_SINCE = datetime.now(timezone.utc)
        _COST_UNAVAILABLE_LOGGED = False


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
    opened = _sample(conn)
    try:
        yield conn
    finally:
        _record_delta(conn, company, opened)
        conn.close()


@contextmanager
def get_read_connection(company: str):
    """Read-only connection (autocommit) for plain SELECTs - no eConnect, no writes, no held
    transaction. Used by /vendors and any other pure read."""
    conn = pyodbc.connect(build_conn_string(company), autocommit=True)
    conn.timeout = get_settings().sql.command_timeout
    opened = _sample(conn)
    try:
        yield conn
    finally:
        _record_delta(conn, company, opened)
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
