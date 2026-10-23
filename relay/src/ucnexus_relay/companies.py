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

The one thing the master does not get to decide is config.EXCLUDED_COMPANIES: those are dropped here,
before anything else sees the reading, so a company nobody may touch is invisible to every consumer at
once rather than needing a refusal in each of them.

Nor does the master decide what this WORKSTATION can actually read. SY01500 lists every company the GP
install has; the relay's own login opens a fraction of them. Production reported 11 companies while its
trusted connection could open three - so every backend loop failed a pass per unreachable company on
every tick, forever, and the log filled with failures that no amount of retrying could fix. So each
company is probed once per discovery and the ones this login cannot read are dropped, with the reason
kept (`inaccessible`) rather than thrown away: a company missing because of a permission is an
operator's problem to fix, and it must not look like a company that does not exist.

What one bad reading does not get to decide is the served set (#1863). A master read that fails (GP's
SQL server restarting, a network blip) used to empty the set until the next tick, fifteen minutes
later, and a probe that merely timed out dropped its company for as long - every op for it refused as
not served while nothing about the company had changed. So refresh() holds the last good set over a
failed read, and holds a company whose probe failed for any reason but a refusal, for at most
HOLD_SECONDS since a reading last confirmed it, and says so (`held`). A company GP no longer lists, or
one the login is refused, is dropped at once as before: those readings worked, and they are the news.
A reading that held anything, or failed outright, asks the channel to read again in RETRY_SECONDS.
"""

import time
from dataclasses import dataclass, field

import pyodbc

from . import db
from .config import EXCLUDED_COMPANIES, get_settings
from .logging_setup import get_logger

logger = get_logger()

# SY01500 is GP's company master: one row per company, INTERID the code (and the company database
# name), CMPNYNAM the display name. Both are char columns, hence the RTRIM.
COMPANY_QUERY = "SELECT RTRIM(INTERID) AS id, RTRIM(CMPNYNAM) AS name FROM dbo.SY01500 ORDER BY INTERID"

_NOT_DISCOVERED_YET = "GP companies not discovered yet"

# The access probe. JC00102 is the job master, which is where every backend loop starts - so a company
# that answers this is a company the loops can actually work, and one that does not is a company they
# would fail on every tick. TOP 1 with no predicate reads a single page; the point is the permission,
# not the row.
ACCESS_PROBE_QUERY = "SELECT TOP 1 1 FROM dbo.JC00102"

# The two refusals production actually gets, named. Anything else (a timeout, a missing database, a
# driver error) is left as "unreadable": the company is unusable either way, and guessing at a
# category we have not seen would be worse than saying so plainly.
_SQLSTATE_REASONS = {
    "28000": "login denied",  # Login failed for user (18456) - the login has no access to that database
    "42000": "permission denied",  # SELECT permission was denied on JC00102 (229)
}

# The longest a company is held served on the strength of an earlier reading, when the readings since
# could not confirm it (#1863): a failed master read, or a probe that failed without being refused. An
# hour is four regular refreshes - long enough to ride out a GP restart, short enough that a company
# genuinely gone does not linger. And how soon a reading like that is tried again.
HOLD_SECONDS = 3600.0
RETRY_SECONDS = 60.0

# How long a discovery may be handed back instead of re-read. Every channel connects at roughly the
# same moment on startup, and each one refreshes before its hello - without this they would each open
# their own connection to GP for the same answer.
REUSE_SECONDS = 5.0


@dataclass(frozen=True)
class Discovery:
    """One reading of the company master. `error` is set only when the read failed, and then
    `companies` and `names` are empty - there is no partial answer. refresh() may instead publish a
    failed read as the last good set, held (see below), and then `error` is None.

    `inaccessible` is code -> why, for the companies GP holds that this relay's login could not read.
    They are NOT in `companies` (nothing may be routed to them), and they are not an error either -
    the reading worked; it is the login that is short. Kept so /health and /info can say why a company
    an operator expects to see is missing."""

    companies: list[str]
    names: dict[str, str]
    error: str | None = None
    inaccessible: dict[str, str] = field(default_factory=dict)
    at: float = field(default_factory=time.monotonic)
    # code -> why, for the companies served from an earlier reading because this one could not confirm
    # them (#1863). They ARE in `companies`. Set only by refresh(), never by discover().
    held: dict[str, str] = field(default_factory=dict)
    # The companies whose probe failed without a refusal (a timeout, a driver fault): what refresh() may
    # hold over. And whether the master read itself failed. Both are discover()'s report to refresh().
    unconfirmed: frozenset[str] = frozenset()
    read_failed: bool = False

    @property
    def retry_soon(self) -> bool:
        """True when this reading is worth repeating before the regular refresh: it failed, or it is
        serving a company only an earlier reading confirmed. A company that has never answered a probe
        waits for the regular refresh, so one that always times out is not dialled every minute."""
        return self.read_failed or bool(self.held)


def _from_sql() -> list[tuple[str, str]]:
    # Not dead: the test suite takes pyodbc away module-wide (conftest), so a discovery nothing asked
    # for fails loudly here instead of dialling the real GP server out of a test run.
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed, so the GP company master cannot be read")
    system_db = get_settings().sql.system_db
    with pyodbc.connect(db.build_conn_string(system_db), autocommit=True) as conn:
        return [(row.id, row.name) for row in conn.cursor().execute(COMPANY_QUERY).fetchall()]


def _reason(error: Exception) -> str:
    """The short why, for the operator. pyodbc puts the SQLSTATE first in args, so the class of
    refusal survives even though the driver's message is a paragraph of vendor prose."""
    args = getattr(error, "args", None) or ()
    state = args[0] if args and isinstance(args[0], str) else ""
    named = _SQLSTATE_REASONS.get(state)
    if named:
        return f"{named} ({state})"
    return f"unreadable ({state})" if state else "unreadable"


def _refused(reason: str) -> bool:
    """Whether a probe's reason is one of the named refusals - the login has no access, which is the
    news - rather than a failure that says nothing about the company (#1863)."""
    return any(reason.startswith(named) for named in _SQLSTATE_REASONS.values())


def _probe(code: str) -> str | None:
    """None if this relay's login can read the company, else the reason it cannot.

    Goes through the module-level `pyodbc` that _from_sql uses rather than db.get_read_connection, so
    the suite-wide guard that takes pyodbc away covers the probe too - a discovery in a test must not
    be able to dial the real GP server, and this runs a connect per company. The connection string is
    still db's, so the probe hits exactly what an op would.

    Only execute() is called, deliberately: SQL Server raises the login/permission refusal there, and
    fetching a row we do not read would only be ceremony."""
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed, so GP companies cannot be probed")
    try:
        with pyodbc.connect(db.build_conn_string(code), autocommit=True) as conn:
            conn.cursor().execute(ACCESS_PROBE_QUERY)
    except Exception as e:  # noqa: BLE001 - any failure means the loops cannot work this company
        return _reason(e)
    return None


def discover() -> Discovery:
    """Read the company master. Never raises: a failure comes back as an empty Discovery carrying the
    reason, because the callers are a channel hello frame and an op refusal, and neither has anywhere
    to put an exception."""
    try:
        rows = _from_sql()
    except Exception as e:  # noqa: BLE001 - any failure to read GP is "this relay serves nothing"
        logger.warning(
            "could not read the GP company master; this relay serves no company until it can",
            extra={"category": "companies_undiscovered", "error": str(e)},
        )
        return Discovery([], {}, str(e), read_failed=True)
    names: dict[str, str] = {}
    for code, name in rows:
        code = (code or "").strip().upper()
        if not code:
            continue
        names[code] = (name or "").strip() or code
    excluded = [code for code in sorted(names) if code in EXCLUDED_COMPANIES]
    for code in excluded:
        del names[code]
    if excluded:
        logger.info(
            "GP companies dropped from this discovery; this relay never serves them",
            extra={"category": "companies_excluded", "companies": excluded},
        )
        if not names:
            # Distinct from a failed read, and the message has to say so: an operator who sees "serving
            # no GP company" needs to know GP answered and every company it named is excluded here.
            return Discovery([], {}, f"every GP company discovered is excluded from this relay: {', '.join(excluded)}")

    # One probe per remaining company, at most once every REFRESH interval - a handful of short
    # connects, against a loop that would otherwise fail a pass per unreadable company forever. The
    # excluded ones above are never probed: this relay may not open them at all.
    inaccessible: dict[str, str] = {}
    for code in sorted(names):
        reason = _probe(code)
        if reason:
            inaccessible[code] = reason
            del names[code]
    unconfirmed = frozenset(code for code, why in inaccessible.items() if not _refused(why))
    if inaccessible:
        logger.info(
            "GP companies this relay's login cannot read; they are not served",
            extra={"category": "companies_inaccessible", "companies": inaccessible},
        )
    if not names and inaccessible:
        # Again distinct from a failed read: GP answered, and this login can open none of what it named.
        # Guarded on `inaccessible` so a master that genuinely lists nothing stays "no companies, no
        # error" rather than being blamed on a login that refused nothing.
        listed = ", ".join(f"{code} ({why})" for code, why in inaccessible.items())
        return Discovery(
            [],
            {},
            f"this relay's login cannot read any GP company it discovered: {listed}",
            inaccessible,
            unconfirmed=unconfirmed,
        )
    return Discovery(sorted(names), names, None, inaccessible, unconfirmed=unconfirmed)


_current = Discovery([], {}, _NOT_DISCOVERED_YET, at=0.0)

# code -> (name, when a reading last confirmed it), for every company the last readings served. What a
# reading that cannot confirm a company is measured against (#1863).
_confirmed: dict[str, tuple[str, float]] = {}


def _hold_over(found: Discovery) -> Discovery:
    """`found`, with the companies it could not confirm but a reading within HOLD_SECONDS did held in
    it (#1863). A company it confirmed is recorded as confirmed now; one it dropped for any other
    reason - GP no longer lists it, the login is refused, it is excluded - is forgotten at once."""
    now = found.at
    if found.read_failed:
        candidates = {code: found.error or "the GP company master could not be read" for code in _confirmed}
    else:
        for code in found.companies:
            _confirmed[code] = (found.names[code], now)
        candidates = {code: found.inaccessible[code] for code in found.unconfirmed if code in _confirmed}
        for code in [code for code in _confirmed if code not in found.companies and code not in candidates]:
            del _confirmed[code]
    held: dict[str, str] = {}
    for code, why in sorted(candidates.items()):
        if now - _confirmed[code][1] <= HOLD_SECONDS:
            held[code] = why
        else:
            del _confirmed[code]
    if not held:
        return found
    logger.warning(
        "GP companies this reading could not confirm are still served from an earlier one",
        extra={"category": "companies_held", "companies": held},
    )
    names = {**found.names, **{code: _confirmed[code][0] for code in held}}
    return Discovery(
        sorted(names),
        names,
        None,
        {code: why for code, why in found.inaccessible.items() if code not in held},
        at=now,
        held=held,
        unconfirmed=found.unconfirmed,
        read_failed=found.read_failed,
    )


def current() -> Discovery:
    """The last discovery, without touching GP. Empty with an error until the first refresh."""
    return _current


def refresh(max_age: float = REUSE_SECONDS) -> Discovery:
    """Re-read the company master, or hand back the last reading if it is younger than `max_age`.
    Blocking (pyodbc), so the channel calls it on a worker thread."""
    global _current
    if time.monotonic() - _current.at < max_age:
        return _current
    _current = _hold_over(discover())
    return _current


def serves(company: str) -> bool:
    return company in current().companies


def reset() -> None:
    """Forget the last discovery, so the next refresh reads GP again."""
    global _current
    _current = Discovery([], {}, _NOT_DISCOVERED_YET, at=0.0)
    _confirmed.clear()
