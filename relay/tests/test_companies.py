"""GP company discovery: the relay serves the companies GP itself holds (DYNAMICS..SY01500), minus the
ones it may never touch (config.EXCLUDED_COMPANIES), and nothing else. There is no configured list any
more, so these cover what the discovery reads, what the exclusion drops, and what an empty discovery
does to an op and to the hello frame.

pyodbc is faked throughout; nothing here reaches a real GP.
"""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import auth, channel, companies, db, ops
from ucnexus_relay.config import (
    EXCLUDED_COMPANIES,
    NON_PRIMARY_ALLOWED_COMPANIES,
    PRODUCTION_BACKEND_URL,
    channel_allowed_companies,
    get_settings,
)
from ucnexus_relay.main import create_app

PR_URL = "wss://backend-pr-999.up.railway.app/relay-link"


class _Row:
    def __init__(self, id, name):
        self.id, self.name = id, name


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *a):
        return self

    def fetchall(self):
        return self._rows


class _Conn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _Cursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _pyodbc(monkeypatch, rows=None, raises=None):
    """Stand in for the module-level pyodbc companies.py imports, recording the connection string so
    the system database it dialled can be asserted."""
    seen = {}

    class _Pyodbc:
        Error = RuntimeError

        @staticmethod
        def connect(conn_str, **kw):
            seen["conn_str"] = conn_str
            if raises is not None:
                raise raises
            return _Conn(rows or [])

    monkeypatch.setattr(companies, "pyodbc", _Pyodbc)
    return seen


# --- reading the company master ---------------------------------------------------------------------


def test_sql_discovery_reads_the_company_master(monkeypatch):
    seen = _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada"), _Row("UBC", "Upper Canada")])
    found = companies.discover()
    assert found.companies == ["TUBC", "UBC"]
    assert found.names == {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"}
    assert found.error is None
    assert "DATABASE=DYNAMICS" in seen["conn_str"]  # the system database, not a company one


def test_sql_discovery_trims_and_upcases_codes_and_skips_blanks(monkeypatch):
    # INTERID / CMPNYNAM are char columns, so a driver that does not trim hands back padded values.
    _pyodbc(monkeypatch, [_Row("  ubc ", "  Upper Canada  "), _Row("   ", "no code at all"), _Row("TUBC", "")])
    found = companies.discover()
    assert found.companies == ["TUBC", "UBC"]
    assert found.names == {"UBC": "Upper Canada", "TUBC": "TUBC"}  # a blank name falls back to the code


def test_the_companies_are_sorted(monkeypatch):
    _pyodbc(monkeypatch, [_Row("UCSH", "a"), _Row("TUBC", "b"), _Row("UBC", "c")])
    assert companies.discover().companies == ["TUBC", "UBC", "UCSH"]


def test_a_failed_read_is_an_empty_set_carrying_the_reason(monkeypatch, caplog):
    _pyodbc(monkeypatch, raises=RuntimeError("SQL server is unreachable"))
    with caplog.at_level("WARNING"):
        found = companies.discover()
    assert found.companies == []
    assert found.names == {}
    assert "unreachable" in found.error
    assert any(r.category == "companies_undiscovered" for r in caplog.records)


def test_discovery_never_raises(monkeypatch):
    # Its callers are a hello frame and an op refusal; neither has anywhere to put an exception.
    monkeypatch.setattr(companies, "pyodbc", None)
    assert companies.discover().error


# --- the company nobody may touch ---------------------------------------------------------------------


def _excluded_records(caplog):
    return [r for r in caplog.records if getattr(r, "category", None) == "companies_excluded"]


def test_an_excluded_company_never_leaves_the_discovery(monkeypatch, caplog):
    _pyodbc(monkeypatch, [_Row(c, f"{c} name") for c in ("TUBC", "TUCSH", "UBC", "UCSH")])
    with caplog.at_level("INFO"):
        found = companies.discover()
    assert found.companies == ["TUBC", "UBC", "UCSH"]
    assert "TUCSH" not in found.names
    assert found.error is None
    # Logged once per discovery, naming what was dropped: an operator who cannot find TUCSH in the
    # picker has to be able to see WHY in relay.log rather than reading it as a broken discovery.
    assert [r.companies for r in _excluded_records(caplog)] == [["TUCSH"]]


def test_a_master_holding_nothing_but_excluded_companies_is_an_empty_discovery_that_says_why(monkeypatch):
    # Empty, but NOT the could-not-read wording: GP answered fine here, and an operator looking at
    # "this relay is serving no GP company" has to be able to tell those two apart.
    _pyodbc(monkeypatch, [_Row("TUCSH", "Test UCSH")])
    found = companies.discover()
    assert found.companies == []
    assert found.names == {}
    assert found.error == "every GP company discovered is excluded from this relay: TUCSH"


def test_serves_says_no_to_an_excluded_company_gp_holds(monkeypatch):
    _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada"), _Row("TUCSH", "Test UCSH")])
    companies.refresh()
    assert companies.serves("TUBC")
    assert not companies.serves("TUCSH")


def test_the_http_surface_never_lists_an_excluded_company(monkeypatch):
    _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada"), _Row("TUCSH", "Test UCSH")])
    companies.refresh()
    app = create_app()
    app.dependency_overrides[auth.verify_token] = lambda: None
    # /info probes the SQL login for the desktop status panel; stubbed so the assertion below cannot
    # be paid for with a real connection to GP out of a test run.
    monkeypatch.setattr(db, "connection_info", lambda system_db: {})
    client = TestClient(app)
    assert [c["id"] for c in client.get("/health").json()["companies"]] == ["TUBC"]
    info = client.get("/info").json()
    assert info["companies"] == ["TUBC"]
    assert "TUCSH" not in info["company_names"]


def test_a_job_for_an_excluded_company_is_refused_before_it_reaches_gp(monkeypatch):
    # The production channel is unrestricted (#414), so the ONLY thing standing between a backend that
    # asks for TUCSH and GP is the discovery it was dropped from.
    _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada"), _Row("TUCSH", "Test UCSH")])
    companies.refresh()
    ran = []

    def _spy(company, payload):
        ops.check_company_served(company)  # every real handler's first line, before it opens anything
        ran.append(company)
        return {"ok": 1}

    monkeypatch.setitem(channel._OPS, "spy_op", _spy)
    reply = channel._dispatch("spy_op", "TUCSH", {}, channel_allowed_companies(PRODUCTION_BACKEND_URL))
    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed"
    assert ran == []  # refused at the gate; nothing past it ran


def test_the_exclusion_is_pinned_to_the_one_sandbox():
    # TUCSH is an old testing sandbox whose data predates the current development policies, and it is
    # excluded by executive decision (2026-09-03) rather than by preference - so it is pinned here, not
    # left to whatever someone edits the constant to. A live company appearing in this list would take
    # the relay out of real work silently.
    assert EXCLUDED_COMPANIES == ["TUCSH"]
    assert not {"UBC", "UCSH", "TUBC"} & set(EXCLUDED_COMPANIES)


# --- the module cache -------------------------------------------------------------------------------


def test_nothing_is_served_before_the_first_refresh():
    assert companies.current().companies == []
    assert companies.current().error  # and it says why, rather than looking like an empty GP


def test_refresh_publishes_what_it_found(monkeypatch):
    _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada")])
    assert companies.refresh().companies == ["TUBC"]
    assert companies.current().companies == ["TUBC"]


def test_refresh_reuses_a_reading_a_few_seconds_old(monkeypatch):
    # Every channel refreshes before its hello, and they all connect at once on startup.
    reads = []

    def _fake():
        reads.append(1)
        return companies.Discovery(["TUBC"], {"TUBC": "Test Upper Canada"})

    monkeypatch.setattr(companies, "discover", _fake)
    companies.refresh()
    companies.refresh()
    assert reads == [1]
    companies.refresh(max_age=0)  # and a caller that insists gets a fresh read
    assert reads == [1, 1]


def test_serves_answers_from_the_discovered_set(monkeypatch):
    _pyodbc(monkeypatch, [_Row("TUBC", "Test Upper Canada")])
    companies.refresh()
    assert companies.serves("TUBC")
    assert not companies.serves("UBC")


# --- what an undiscovered company does to an op -----------------------------------------------------


def test_an_op_is_refused_for_a_company_gp_does_not_hold(serving):
    serving(["TUBC"])
    with pytest.raises(ops.RelayOpError) as e:
        ops.check_company_served("UBC")
    assert e.value.code == "company_not_allowed"
    assert "TUBC" in e.value.message


def test_an_empty_set_refuses_every_op_and_quotes_the_discovery_error(serving):
    # The operator-facing half of "discovery failed": the refusal has to say WHY nothing is served,
    # or a relay that cannot reach GP looks identical to one told to serve nothing.
    serving([], error="SQL server is unreachable")
    with pytest.raises(ops.RelayOpError) as e:
        ops.check_company_served("TUBC")
    assert e.value.code == "company_not_allowed"
    assert "SQL server is unreachable" in e.value.message


def test_a_served_company_passes(serving):
    serving(["TUBC", "UBC"])
    ops.check_company_served("UBC")  # no raise


# --- the hello frame --------------------------------------------------------------------------------


def test_the_hello_frame_carries_the_discovered_companies_and_names(serving):
    serving(["TUBC", "UBC"], {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"})
    frame = channel._hello_frame(channel_allowed_companies(PRODUCTION_BACKEND_URL))
    assert frame["companies"] == ["TUBC", "UBC"]
    assert frame["company_names"] == {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"}
    assert frame["companies_error"] is None


def test_a_non_primary_channel_is_only_told_about_the_sandbox(serving):
    # A test backend never sees a company its own channel would refuse anyway (#414), so it cannot
    # offer the operator a company that is guaranteed to come back company_not_allowed_on_channel.
    serving(["TUBC", "UBC", "UCSH"], {c: f"{c} name" for c in ("TUBC", "UBC", "UCSH")})
    frame = channel._hello_frame(channel_allowed_companies(PR_URL))
    assert frame["companies"] == NON_PRIMARY_ALLOWED_COMPANIES
    assert set(frame["company_names"]) == set(NON_PRIMARY_ALLOWED_COMPANIES)
    assert frame["companies_error"] is None  # discovery worked; this channel is simply pinned


def test_the_hello_frame_never_names_an_excluded_company(monkeypatch):
    # The frame is what every backend routes and builds its company picker from, so a company dropped
    # from the discovery is a company no backend can sync, offer or ask for - on the production channel
    # too, which is the unrestricted one.
    _pyodbc(monkeypatch, [_Row(c, f"{c} name") for c in ("TUBC", "TUCSH", "UBC", "UCSH")])
    companies.refresh()
    frame = channel._hello_frame(channel_allowed_companies(PRODUCTION_BACKEND_URL))
    assert frame["companies"] == ["TUBC", "UBC", "UCSH"]
    assert "TUCSH" not in frame["company_names"]
    assert frame["companies_error"] is None


def test_a_failed_discovery_reaches_the_backend_on_the_hello(serving):
    serving([], error="SQL server is unreachable")
    frame = channel._hello_frame(None)
    assert frame["companies"] == []
    assert frame["company_names"] == {}
    assert frame["companies_error"] == "SQL server is unreachable"


# --- re-announcing on a live channel ----------------------------------------------------------------


class _FakeWs:
    """Just enough of a websockets client for _run_once: an async iterator of raw frames, plus send."""

    def __init__(self, done):
        self._done, self.sent = done, []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        async def gen():
            await self._done.wait()
            return
            yield  # pragma: no cover - never reached; makes this a generator

        return gen()


def test_the_refresh_loop_resends_the_hello_only_when_something_changed(monkeypatch, clean_channel_states):
    """A company added in GP has to reach the backend without dropping the socket - but a re-send on
    every tick would have the backend rewriting its relay row every 15 minutes for no reason."""
    one = companies.Discovery(["TUBC"], {"TUBC": "Test Upper Canada"})
    two = companies.Discovery(["TUBC", "UBC"], {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"})
    seq = [one, one, two]

    monkeypatch.setattr(companies, "current", lambda: seq[0])
    monkeypatch.setattr(companies, "refresh", lambda *a, **k: seq.pop(0) if len(seq) > 1 else seq[0])
    monkeypatch.setattr(channel, "COMPANY_REFRESH_SECONDS", 0)

    async def run():
        done = asyncio.Event()
        ws = _FakeWs(done)

        class _Cm:
            async def __aenter__(self):
                return ws

            async def __aexit__(self, *exc):
                return False

        monkeypatch.setattr(channel.websockets, "connect", lambda url, **kw: _Cm())
        task = asyncio.create_task(channel._run_once(PRODUCTION_BACKEND_URL, "secret", get_settings().channel))
        # Real sleeps, not sleep(0) spins: each refresh hops through asyncio.to_thread (pyodbc blocks),
        # and a thread hand-off takes wall time no number of immediate yields will pass.
        deadline = time.monotonic() + 5
        while len(ws.sent) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.005)
        for _ in range(20):  # keep ticking: an unchanged set must not produce a third frame
            await asyncio.sleep(0.005)
        done.set()
        await task
        return ws.sent

    sent = asyncio.run(run())
    assert [f["type"] for f in sent] == ["hello", "hello"]
    assert sent[0]["companies"] == ["TUBC"]
    assert sent[1]["companies"] == ["TUBC", "UBC"]
    assert sent[1]["company_names"]["UBC"] == "Upper Canada"
