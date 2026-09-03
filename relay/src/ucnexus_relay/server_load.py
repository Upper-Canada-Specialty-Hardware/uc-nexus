"""How busy the GP SQL server is, read from the server itself.

Neither Nexus nor this relay may ever contribute to an overload of that server, and the relay is the
last gate in front of it: background work is refused while the server is busy, whatever backend asked.
That decision has to come from the server's LIVE state rather than from a fixed wait, and this is
where the reading comes from.

Two signals, both server-wide:

  sql_cpu_pct / other_cpu_pct - the latest SystemHealth record in the RING_BUFFER_SCHEDULER_MONITOR
  ring buffer. ProcessUtilization is SQL Server's own share of the CPU and SystemIdle is idle, so
  everything else running on the box is the remainder: other = 100 - process - idle. SQL Server
  writes one of these a minute, so the number is up to a minute old BY CONSTRUCTION - it is a trend,
  not an instant.

  runnable_tasks - SUM(runnable_tasks_count) over the online schedulers: tasks that hold a worker and
  are queued for CPU. Instantaneous, and the signal that says the server is out of CPU right now
  rather than a minute ago.

Both DMVs need VIEW SERVER STATE (unlike the per-session cost reading in db.py, which a session may
take on its own row). Without that grant - or on any other failure - the sample comes back with
source "unavailable" and nulls, a WARNING names the grant once per process, and nothing raises. A
relay that cannot see the server's load still does its work; it just cannot pace on it.
"""

import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import db
from .config import get_settings
from .logging_setup import get_logger

logger = get_logger()

RING_BUFFER = "ring_buffer"
UNAVAILABLE = "unavailable"

# How long a reading may be handed back instead of re-read. The ring buffer itself only refreshes once
# a minute, so a shorter window would cost connections for a number that has not moved; a longer one
# would let the busy gate act on a reading from another era.
FRESH_SECONDS = 15.0

# The latest SystemHealth record, shredded in Python rather than with SQL's XML methods: the parse is
# then a pure function this suite can put a canned record through, and the server does no XML work.
_RING_BUFFER_SQL = (
    "SELECT TOP 1 record FROM sys.dm_os_ring_buffers "
    "WHERE ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR' AND record LIKE N'%<SystemHealth>%' "
    "ORDER BY timestamp DESC"
)

# VISIBLE ONLINE only: the hidden schedulers serve internal tasks (DAC, resource monitor) and their
# queues say nothing about the pressure user work is under.
_RUNNABLE_SQL = (
    "SELECT SUM(runnable_tasks_count) FROM sys.dm_os_schedulers WHERE status = 'VISIBLE ONLINE'"
)

_LOCK = threading.Lock()
_CURRENT: "Sample | None" = None
_WARNED = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Sample:
    """One reading. `source` says whether the numbers mean anything: "unavailable" is a reading that
    could not be taken, and then every value is None - there is no partial answer, and in particular
    no zero standing in for one (a 0% CPU that is really "we could not look" would read as an idle
    server and let every deferred backlog loose at once)."""

    sql_cpu_pct: int | None = None
    other_cpu_pct: int | None = None
    runnable_tasks: int | None = None
    sampled_at: str = field(default_factory=_now_iso)
    source: str = UNAVAILABLE
    # Cache age only - monotonic, and deliberately not part of the wire shape below.
    at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> dict:
        """The `server` block on a job reply. `sampled_at` rides along so the backend can see how old
        a reading is: a user-facing op attaches the last sample rather than taking a fresh one."""
        return {
            "sql_cpu_pct": self.sql_cpu_pct,
            "other_cpu_pct": self.other_cpu_pct,
            "runnable_tasks": self.runnable_tasks,
            "sampled_at": self.sampled_at,
            "source": self.source,
        }

    def busy(self, ceiling_pct: int) -> bool:
        """Whether background work must stand down. Only a REAL reading can refuse anything: a sample
        the server would not give is not evidence of a busy server, and refusing on it would strand
        the mirror for as long as the grant is missing."""
        return self.source == RING_BUFFER and self.sql_cpu_pct is not None and self.sql_cpu_pct >= ceiling_pct


def parse_scheduler_monitor(record: str) -> tuple[int | None, int | None]:
    """(sql_cpu_pct, other_cpu_pct) from one RING_BUFFER_SCHEDULER_MONITOR record.

    other = 100 - ProcessUtilization - SystemIdle, clamped: the two values come from separate counters
    sampled a moment apart, so they can sum past 100 and produce a negative remainder that is really a
    rounding artefact."""
    health = ET.fromstring(record).find(".//SystemHealth")
    if health is None:
        return None, None
    process = _int_or_none(health.findtext("ProcessUtilization"))
    idle = _int_or_none(health.findtext("SystemIdle"))
    if process is None:
        return None, None
    process = max(0, min(100, process))
    if idle is None:
        return process, None
    return process, max(0, min(100, 100 - process - idle))


def _int_or_none(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except (TypeError, ValueError):
        return None


def _read(conn) -> tuple[int | None, int | None, int | None]:
    row = conn.cursor().execute(_RING_BUFFER_SQL).fetchone()
    sql_cpu, other_cpu = parse_scheduler_monitor(row[0]) if row and row[0] else (None, None)
    row = conn.cursor().execute(_RUNNABLE_SQL).fetchone()
    runnable = int(row[0]) if row and row[0] is not None else None
    return sql_cpu, other_cpu, runnable


def _warn_unavailable(error: Exception, conn) -> None:
    """Once per process, at WARNING, with the grant a DBA has to run. The login is read back off the
    same connection where there is one, so the line is a statement to paste rather than a shape to
    fill in."""
    global _WARNED
    with _LOCK:
        first = not _WARNED
        _WARNED = True
    if not first:
        return
    login = "<the relay's login>"
    if conn is not None:
        try:
            login = f"[{conn.cursor().execute('SELECT SUSER_NAME()').fetchone()[0]}]"
        except Exception:  # noqa: BLE001 - a best-effort nicety on an already-failing path
            pass
    logger.warning(
        "cannot read the GP server's load; background work will not be paced on it",
        extra={
            "category": "server_load_unavailable",
            "error": str(error),
            "grant": f"GRANT VIEW SERVER STATE TO {login}",
        },
    )


def sample(conn=None) -> Sample:
    """Take a reading now. Never raises - a failure is a Sample whose source is "unavailable".

    Runs on `conn` when the caller has one open. With none it opens its own read connection to the
    system database: the DMVs are server-scoped, so which database it lands in does not matter, and
    the system database is the one every relay can reach."""
    if conn is not None:
        return _sample_on(conn)
    try:
        with db.get_read_connection(get_settings().sql.system_db) as own:
            return _sample_on(own)
    except Exception as e:  # noqa: BLE001 - could not even connect; still not this op's problem
        _warn_unavailable(e, None)
        return Sample()


def _sample_on(conn) -> Sample:
    try:
        sql_cpu, other_cpu, runnable = _read(conn)
    except Exception as e:  # noqa: BLE001 - most likely the missing VIEW SERVER STATE grant
        _warn_unavailable(e, conn)
        return Sample()
    return Sample(sql_cpu_pct=sql_cpu, other_cpu_pct=other_cpu, runnable_tasks=runnable, source=RING_BUFFER)


def current() -> Sample | None:
    """The last reading, without touching GP. None until something has taken one - which is what a
    user-facing op's reply carries, since those never sample on their own account."""
    with _LOCK:
        return _CURRENT


def refresh(max_age: float = FRESH_SECONDS) -> Sample:
    """The current reading, re-read if the cached one is older than `max_age`. Blocking (pyodbc), so
    it is called from the worker thread an op already runs on.

    The read happens OUTSIDE the lock: holding it across a SQL round trip would park every other
    worker thread behind a server that is by definition already struggling. Two threads arriving
    together on a stale cache can therefore both read - two DMV reads instead of one, which is the
    cheap side of that trade."""
    global _CURRENT
    with _LOCK:
        cached = _CURRENT
    if cached is not None and time.monotonic() - cached.at < max_age:
        return cached
    fresh = sample()
    with _LOCK:
        _CURRENT = fresh
    return fresh


def reset() -> None:
    """Forget the cached reading (and the once-per-process warning). For tests."""
    global _CURRENT, _WARNED
    with _LOCK:
        _CURRENT = None
        _WARNED = False
