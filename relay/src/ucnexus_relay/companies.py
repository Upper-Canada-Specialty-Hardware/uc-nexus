"""Which GP companies this relay serves, discovered from GP itself.

The list used to be hand-maintained in two places - a key in every workstation's config.toml and a
constant in config.py - so a company that exists in GP was invisible to Nexus until somebody edited
both. It now comes from the company master, DYNAMICS..SY01500, which is the same list GP's own login
screen offers. Nothing about it is configurable.

An empty set is not a fallback to anything: a relay that cannot read the master serves NO company and
says why (the hello frame carries `companies_error`, and an op refusal quotes it). Silently serving a
guessed list would be the one failure mode worth avoiding here - a job would reach a company nobody
meant this workstation to touch.

Refreshed on every channel connect and on a timer while a channel is up (channel.py), so a company
added in GP reaches the backend without a restart.
"""

import time
from dataclasses import dataclass, field

try:
    import pyodbc
except ImportError:  # fixture mode (a Linux container, no ODBC stack) - see fixture_ops.py
    pyodbc = None

from . import db
from .config import get_settings
from .logging_setup import get_logger

logger = get_logger()

# SY01500 is GP's company master: one row per company, INTERID the code (and the company database
# name), CMPNYNAM the display name. Both are char columns, hence the RTRIM.
COMPANY_QUERY = "SELECT RTRIM(INTERID) AS id, RTRIM(CMPNYNAM) AS name FROM dbo.SY01500 ORDER BY INTERID"

# One company's display name, for `ucnexus-relay capture` - a snapshot records the name GP gives so a
# fixture relay reports what a workstation would. Same table, same trim; parameterised on the code.
COMPANY_NAME_QUERY = "SELECT RTRIM(CMPNYNAM) FROM dbo.SY01500 WHERE RTRIM(INTERID) = ?"

_NOT_DISCOVERED_YET = "GP companies not discovered yet"

# How long a discovery may be handed back instead of re-read. Every channel connects at roughly the
# same moment on startup, and each one refreshes before its hello - without this they would each open
# their own connection to GP for the same answer.
REUSE_SECONDS = 5.0


@dataclass(frozen=True)
class Discovery:
    """One reading of the company master. `error` is set only when the read failed, and then
    `companies` and `names` are empty - there is no partial answer."""

    companies: list[str]
    names: dict[str, str]
    error: str | None = None
    at: float = field(default_factory=time.monotonic)


def _from_sql() -> list[tuple[str, str]]:
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed, so the GP company master cannot be read")
    system_db = get_settings().sql.system_db
    with pyodbc.connect(db.build_conn_string(system_db), autocommit=True) as conn:
        return [(row.id, row.name) for row in conn.cursor().execute(COMPANY_QUERY).fetchall()]


def _from_fixture() -> list[tuple[str, str]]:
    """The snapshot's own companies. `name` is optional there, so a snapshot written before this
    existed (and one written by `ucnexus-relay capture`, which has no read op for it) still loads."""
    from . import fixture_ops  # lazy: the workstation relay never loads this module

    companies = fixture_ops.load_state().get("companies") or {}
    return [(code, (data or {}).get("name") or code) for code, data in companies.items()]


def discover() -> Discovery:
    """Read the company master. Never raises: a failure comes back as an empty Discovery carrying the
    reason, because the callers are a channel hello frame and an op refusal, and neither has anywhere
    to put an exception."""
    try:
        rows = _from_fixture() if get_settings().gp.mode == "fixture" else _from_sql()
    except Exception as e:  # noqa: BLE001 - any failure to read GP is "this relay serves nothing"
        logger.warning(
            "could not read the GP company master; this relay serves no company until it can",
            extra={"category": "companies_undiscovered", "error": str(e)},
        )
        return Discovery([], {}, str(e))
    names: dict[str, str] = {}
    for code, name in rows:
        code = (code or "").strip().upper()
        if not code:
            continue
        names[code] = (name or "").strip() or code
    return Discovery(sorted(names), names)


_current = Discovery([], {}, _NOT_DISCOVERED_YET, at=0.0)


def current() -> Discovery:
    """The last discovery, without touching GP. Empty with an error until the first refresh."""
    return _current


def refresh(max_age: float = REUSE_SECONDS) -> Discovery:
    """Re-read the company master, or hand back the last reading if it is younger than `max_age`.
    Blocking (pyodbc), so the channel calls it on a worker thread."""
    global _current
    if time.monotonic() - _current.at < max_age:
        return _current
    _current = discover()
    return _current


def serves(company: str) -> bool:
    return company in current().companies


def reset() -> None:
    """Forget the last discovery, so the next refresh reads GP again."""
    global _current
    _current = Discovery([], {}, _NOT_DISCOVERED_YET, at=0.0)
