"""Adaptive pacing: the live GP server-load reading, and the busy gate that stands background work
down while the server is under pressure.

pyodbc is faked throughout - a canned RING_BUFFER_SCHEDULER_MONITOR record stands in for the ring
buffer, so the parse and the gate are both exercised without a SQL Server. Nothing here reaches GP.
"""

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ucnexus_relay import channel, db, econnect, server_load
from ucnexus_relay.config import DEFAULT_LOAD_CEILING_PCT, MIN_LOAD_CEILING_PCT, get_settings

# A real record, trimmed to the elements the parse reads. ProcessUtilization is SQL Server's own CPU
# share and SystemIdle is idle; everything else on the box is the remainder.
RECORD = """<Record id="1044" type="RING_BUFFER_SCHEDULER_MONITOR" time="8813750">
  <SchedulerMonitorEvent>
    <SystemHealth>
      <ProcessUtilization>84</ProcessUtilization>
      <SystemIdle>9</SystemIdle>
      <UserModeTime>1180312500</UserModeTime>
      <KernelModeTime>106250000</KernelModeTime>
      <PageFaults>2036</PageFaults>
      <WorkingSetDelta>-16384</WorkingSetDelta>
      <MemoryUtilization>100</MemoryUtilization>
    </SystemHealth>
  </SchedulerMonitorEvent>
</Record>"""


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._row = None

    def execute(self, sql, *params):
        self._conn.sql.append(sql)
        if "dm_os_ring_buffers" in sql:
            if self._conn.ring_raises is not None:
                raise self._conn.ring_raises
            self._row = (self._conn.record,) if self._conn.record is not None else None
        elif "dm_os_schedulers" in sql:
            self._row = (self._conn.runnable,)
        elif "SUSER_NAME" in sql:
            self._row = (self._conn.login,)
        else:
            self._row = None
        return self

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, record=RECORD, runnable=3, ring_raises=None, login="UPPERCANADA\\jayp"):
        self.record = record
        self.runnable = runnable
        self.ring_raises = ring_raises
        self.login = login
        self.sql = []

    def cursor(self):
        return _Cursor(self)


def _fake_db(monkeypatch, conn=None, connect_raises=None):
    """Stand in for the db module server_load samples through (the conftest guard already replaced it
    with one that refuses; this hands back a server instead). Records how many connections were
    opened, which is what the cache is there to keep down."""
    opened = []

    class _Db:
        @staticmethod
        @contextmanager
        def get_read_connection(company):
            opened.append(company)
            if connect_raises is not None:
                raise connect_raises
            yield conn if conn is not None else _Conn()

    monkeypatch.setattr(server_load, "db", _Db)
    return opened


class _Denied(Exception):
    """pyodbc puts the SQLSTATE first in args; the reason line is read off that."""


def _permission_error():
    return _Denied(
        "42000",
        "[42000] [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]VIEW SERVER STATE permission "
        "was denied on object 'server' (300)",
    )


# --- the reading ------------------------------------------------------------------------------------


def test_the_ring_buffer_record_parses_into_sql_and_other_cpu():
    assert server_load.parse_scheduler_monitor(RECORD) == (84, 7)  # 100 - 84 process - 9 idle


def test_a_record_whose_counters_overlap_never_reports_negative_other_cpu():
    # The two counters are sampled a moment apart, so they can sum past 100.
    record = RECORD.replace("<SystemIdle>9</SystemIdle>", "<SystemIdle>30</SystemIdle>")
    assert server_load.parse_scheduler_monitor(record) == (84, 0)


def test_a_record_with_no_system_health_parses_to_nulls():
    assert server_load.parse_scheduler_monitor("<Record><SchedulerMonitorEvent /></Record>") == (None, None)


def test_a_sample_carries_both_signals_and_names_its_source(monkeypatch):
    _fake_db(monkeypatch, _Conn(runnable=5))
    sample = server_load.sample()
    assert sample.to_dict() == {
        "sql_cpu_pct": 84,
        "other_cpu_pct": 7,
        "runnable_tasks": 5,
        "sampled_at": sample.sampled_at,
        "source": "ring_buffer",
    }
    assert sample.sampled_at.endswith("+00:00")


def test_a_denied_dmv_is_an_unavailable_sample_with_nulls(monkeypatch):
    # Not zeros: a 0% CPU standing in for "we could not look" would read as an idle server and let
    # every deferred backlog loose at once.
    _fake_db(monkeypatch, _Conn(ring_raises=_permission_error()))
    sample = server_load.sample()
    assert sample.source == "unavailable"
    assert (sample.sql_cpu_pct, sample.other_cpu_pct, sample.runnable_tasks) == (None, None, None)


def test_the_missing_grant_is_named_once_per_process(monkeypatch, caplog):
    _fake_db(monkeypatch, _Conn(ring_raises=_permission_error()))
    with caplog.at_level("WARNING"):
        for _ in range(3):
            server_load.sample()
    lines = [r for r in caplog.records if r.category == "server_load_unavailable"]
    assert len(lines) == 1
    assert lines[0].grant == "GRANT VIEW SERVER STATE TO [UPPERCANADA\\jayp]"  # read off the same session
    assert "VIEW SERVER STATE permission was denied" in lines[0].error


def test_a_server_that_cannot_be_reached_at_all_is_unavailable_not_an_exception(monkeypatch):
    _fake_db(monkeypatch, connect_raises=RuntimeError("08001 could not open a connection"))
    assert server_load.sample().source == "unavailable"


# --- the cache --------------------------------------------------------------------------------------


def test_a_reading_is_reused_inside_the_window(monkeypatch):
    opened = _fake_db(monkeypatch)
    first = server_load.refresh()
    second = server_load.refresh()
    assert second is first
    assert opened == [get_settings().sql.system_db]  # one connection, not two


def test_a_caller_that_insists_gets_a_fresh_reading(monkeypatch):
    opened = _fake_db(monkeypatch)
    server_load.refresh()
    server_load.refresh(max_age=0)
    assert len(opened) == 2


def test_nothing_is_cached_before_the_first_reading():
    assert server_load.current() is None


def test_current_hands_back_the_last_reading_without_touching_gp(monkeypatch):
    _fake_db(monkeypatch)
    taken = server_load.refresh()
    monkeypatch.setattr(server_load, "db", None)  # any read now would explode
    assert server_load.current() is taken


# --- the busy predicate -----------------------------------------------------------------------------


def test_only_a_real_reading_can_defer_work():
    # A missing grant must not strand the mirror: "unavailable" is not evidence of a busy server.
    assert not server_load.Sample(sql_cpu_pct=99, source="unavailable").busy(70)
    assert server_load.Sample(sql_cpu_pct=70, source="ring_buffer").busy(70)
    assert not server_load.Sample(sql_cpu_pct=69, source="ring_buffer").busy(70)


# --- the gate in front of GP ------------------------------------------------------------------------


@pytest.fixture
def _no_real_sql(monkeypatch):
    @contextmanager
    def _conn(company):
        yield object()

    monkeypatch.setattr(db, "get_read_connection", _conn)
    monkeypatch.setattr(db, "get_connection", _conn)


def _ceiling(monkeypatch, pct):
    monkeypatch.setattr(
        channel, "get_settings", lambda *a, **k: SimpleNamespace(gp=SimpleNamespace(load_ceiling_pct=pct))
    )


def _server_at(monkeypatch, pct):
    """Put the GP server at `pct` CPU, and hand back the log of connections the sampler opened."""
    return _fake_db(
        monkeypatch, _Conn(record=RECORD.replace("<ProcessUtilization>84<", f"<ProcessUtilization>{pct}<"))
    )


def test_a_background_flagged_job_is_refused_above_the_ceiling(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 84)
    ran = []
    monkeypatch.setattr(econnect, "sync_pos", lambda *a, **k: ran.append(1) or {"pos": []})

    reply = channel._dispatch("sync_pos", "UBC", {}, None, True)

    assert ran == []  # and nothing ran
    assert reply["ok"] is False
    assert reply["error"]["error"] == "server_busy"
    assert reply["error"]["message"] == (
        "GP SQL server is at 84% CPU, above this relay's ceiling of 70%; background work deferred"
    )
    assert reply["error"]["context"] == {"sql_cpu_pct": 84, "ceiling_pct": 70, "retry_after_seconds": 60}
    assert reply["server"]["sql_cpu_pct"] == 84
    assert reply["server"]["source"] == "ring_buffer"


def test_a_background_flagged_job_runs_below_the_ceiling(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 40)
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [{"job_number": "80003"}])

    reply = channel._dispatch("list_jobs", "UBC", {}, None, True)

    assert reply["ok"] is True
    assert reply["result"]["jobs"] == [{"job_number": "80003"}]
    assert reply["server"]["sql_cpu_pct"] == 40


def test_every_op_a_loop_calls_can_be_deferred(monkeypatch, serving, _no_real_sql):
    # The set is the audit of the backend's timer-driven callers and the outer bound on what a
    # `background` flag may ever defer; a new one added to _OPS without being classified is the
    # failure this guards.
    assert channel.BACKGROUND_OPS == {"sync_pos", "read_pos_by_number", "list_jobs", "job_setup_health"}
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 95)
    for op in sorted(channel.BACKGROUND_OPS):
        assert channel._dispatch(op, "UBC", {}, None, True)["error"]["error"] == "server_busy"


def test_an_unflagged_job_is_served_above_the_ceiling_and_pays_for_no_sample(monkeypatch, serving, _no_real_sql):
    """The same op the adoption pass calls, asked for by a person: the GP job picker and the admin
    Sync from GP button both reach list_jobs, and neither may be deferred because a loop shares the
    op name. No flag, no refusal - and no reading taken on its account either."""
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    opened = _server_at(monkeypatch, 99)
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [{"job_number": "80003"}])

    reply = channel._dispatch("list_jobs", "UBC", {})

    assert reply["ok"] is True
    assert reply["result"]["jobs"] == [{"job_number": "80003"}]
    assert opened == []  # nothing was sampled for it
    assert reply["server"] is None  # so there is no reading to report


def test_a_flagged_op_outside_the_audited_set_is_never_refused(monkeypatch, serving, _no_real_sql):
    # A backend that flagged a user's PO write as background would otherwise have this relay defer a
    # GP write already accepted and owed to somebody. BACKGROUND_OPS makes that unexpressible.
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 99)
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [])
    assert channel._dispatch("list_vendors", "UBC", {}, None, True)["ok"] is True


def test_a_user_facing_op_is_never_refused(monkeypatch, serving, _no_real_sql):
    # Somebody is waiting on this one. A person is worth more than a percentage point of CPU.
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 99)
    server_load.refresh()  # the reading exists and says the server is pinned
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [{"vendor_id": "V1"}])

    reply = channel._dispatch("list_vendors", "UBC", {})

    assert reply["ok"] is True
    assert reply["result"]["vendors"] == [{"vendor_id": "V1"}]
    assert reply["server"]["sql_cpu_pct"] == 99  # reported, not acted on


def test_an_unavailable_reading_never_defers_a_flagged_job(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _fake_db(monkeypatch, _Conn(ring_raises=_permission_error()))
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [])

    reply = channel._dispatch("list_jobs", "UBC", {}, None, True)

    assert reply["ok"] is True
    assert reply["server"]["source"] == "unavailable"
    assert reply["server"]["sql_cpu_pct"] is None


def test_the_flag_travels_from_the_job_frame_to_the_gate(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 84)
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [])

    frame = {"id": "j1", "op": "list_jobs", "company": "UBC", "background": True}
    flagged = asyncio.run(channel._handle_job(frame))
    plain = asyncio.run(channel._handle_job({"id": "j2", "op": "list_jobs", "company": "UBC"}))

    assert flagged["id"] == "j1" and flagged["error"]["error"] == "server_busy"
    assert plain["id"] == "j2" and plain["ok"] is True  # the same op, unflagged, on the same server


def test_only_a_literal_true_is_a_background_claim(monkeypatch, serving, _no_real_sql):
    """Strict on purpose: a backend that put the string "false" - or anything else - in that slot must
    not have its user-facing job deferred by it."""
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 84)
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [])

    for value in (False, "true", "false", 1, None, {}):
        frame = {"id": "j", "op": "list_jobs", "company": "UBC", "background": value}
        assert asyncio.run(channel._handle_job(frame))["ok"] is True


# --- the reply fields -------------------------------------------------------------------------------


class _CostCursor:
    def __init__(self, conn):
        self._conn = conn
        self._row = None

    def execute(self, sql, *params):
        if "dm_exec_sessions" in sql:
            self._row = self._conn.samples.pop(0) if self._conn.samples else None
        else:
            self._row = None
        return self

    def fetchone(self):
        return self._row


class _CostConn:
    """A connection whose own session accounting is scripted, so the reply's `cost` is a known delta."""

    def __init__(self, samples):
        self.samples = list(samples)
        self.autocommit = True
        self.timeout = None

    def cursor(self):
        return _CostCursor(self)

    def close(self):
        pass


def test_a_reply_carries_what_the_op_cost_and_what_the_server_looked_like(monkeypatch, serving):
    serving(["UBC"])
    conn = _CostConn([(1000, 40000, 1200), (1812, 85210, 2540)])

    class _Pyodbc:
        Error = RuntimeError

        @staticmethod
        def connect(conn_str, **kw):
            return conn

    monkeypatch.setattr(db, "pyodbc", _Pyodbc)
    _server_at(monkeypatch, 40)
    server_load.refresh()
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [])

    reply = channel._dispatch("list_vendors", "UBC", {})

    assert reply["cost"] == {"cpu_ms": 812, "logical_reads": 45210, "elapsed_ms": 1340}
    assert reply["server"]["sql_cpu_pct"] == 40


def test_a_reply_says_null_when_nothing_was_measured_or_sampled(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [])
    reply = channel._dispatch("list_vendors", "UBC", {})
    assert reply["cost"] is None  # the faked connection reports no session accounting
    assert reply["server"] is None  # and nothing has sampled on this relay yet


def test_an_error_reply_carries_them_too(monkeypatch, serving, _no_real_sql):
    serving(["UBC"])
    reply = channel._dispatch("not_a_real_op", "UBC", {})
    assert reply["ok"] is False
    assert reply["cost"] is None and reply["server"] is None


# --- the server_load op -----------------------------------------------------------------------------


def test_the_server_load_op_answers_with_the_current_sample(monkeypatch, serving):
    serving(["UBC"])
    _server_at(monkeypatch, 55)
    reply = channel._dispatch("server_load", "UBC", {})
    assert reply["ok"] is True
    assert reply["result"] == {
        "sql_cpu_pct": 55,
        "other_cpu_pct": 36,
        "runnable_tasks": 3,
        "sampled_at": reply["result"]["sampled_at"],
        "source": "ring_buffer",
    }


def test_the_server_load_op_is_never_refused(monkeypatch, serving):
    # It is what the backend probes while it is being held back, so it has to answer while everything
    # background is being refused.
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    _server_at(monkeypatch, 99)
    assert channel._dispatch("server_load", "UBC", {})["ok"] is True


def test_the_server_load_op_needs_no_company(monkeypatch, serving):
    # A paused backend may have none in hand, and the answer is about the server, not a company.
    serving(["UBC"])
    _server_at(monkeypatch, 20)
    assert channel._dispatch("server_load", "", {})["ok"] is True
    assert channel._dispatch("server_load", "", {}, ["TUBC"])["ok"] is True  # nor is it company-pinned


def test_the_op_set_the_relay_advertises_carries_it(serving):
    serving(["UBC"])
    assert "server_load" in channel._hello_frame()["ops"]


# --- the ceiling ------------------------------------------------------------------------------------


def test_the_ceiling_defaults_to_seventy(tmp_path):
    assert get_settings(str(tmp_path / "none.toml")).gp.load_ceiling_pct == DEFAULT_LOAD_CEILING_PCT == 70


def test_config_sets_the_ceiling(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nload_ceiling_pct = 55\n", encoding="utf-8")
    assert get_settings(str(cfg)).gp.load_ceiling_pct == 55


def test_the_env_override_wins(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nload_ceiling_pct = 55\n", encoding="utf-8")
    monkeypatch.setenv("UCNEXUS_RELAY_LOAD_CEILING_PCT", "42")
    assert get_settings(str(cfg)).gp.load_ceiling_pct == 42


def test_the_ceiling_has_a_floor(tmp_path):
    # Below it the gate would refuse everything forever, which looks exactly like a broken relay.
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nload_ceiling_pct = 1\n", encoding="utf-8")
    assert get_settings(str(cfg)).gp.load_ceiling_pct == MIN_LOAD_CEILING_PCT == 10


def test_the_gate_cannot_be_switched_off_from_config(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nload_ceiling_pct = 900\n", encoding="utf-8")
    assert get_settings(str(cfg)).gp.load_ceiling_pct == 100


def test_a_junk_ceiling_falls_back_instead_of_stopping_the_relay(tmp_path):
    # An unreadable config.toml would take production's channel down over a typo in a safety limit.
    cfg = tmp_path / "config.toml"
    cfg.write_text('[gp]\nload_ceiling_pct = "seventy"\n', encoding="utf-8")
    assert get_settings(str(cfg)).gp.load_ceiling_pct == DEFAULT_LOAD_CEILING_PCT


# --- what the gate itself costs -----------------------------------------------------------------------


class _MeteredConn:
    """A connection that answers BOTH the per-session cost reading and the two load DMVs, so the
    sampler's own connection is measured exactly as a real one would be."""

    def __init__(self, cost_samples, pct=84):
        self.cost_samples = list(cost_samples)
        self.record = RECORD.replace("<ProcessUtilization>84<", f"<ProcessUtilization>{pct}<")
        self.autocommit = True
        self.timeout = None
        self.closed = False

    def cursor(self):
        return _MeteredCursor(self)

    def close(self):
        self.closed = True


class _MeteredCursor:
    def __init__(self, conn):
        self._conn = conn
        self._row = None

    def execute(self, sql, *params):
        if "dm_exec_sessions" in sql:
            self._row = self._conn.cost_samples.pop(0) if self._conn.cost_samples else None
        elif "dm_os_ring_buffers" in sql:
            self._row = (self._conn.record,)
        elif "dm_os_schedulers" in sql:
            self._row = (2,)
        else:
            self._row = None
        return self

    def fetchone(self):
        return self._row


def test_the_gate_books_its_own_sampling_as_server_load(monkeypatch, serving):
    """The reading the gate takes opens a connection of its own. That is the relay's overhead for
    deciding whether to run at all, not the deferred op's cost - and above all it must not land in
    gp_cost as an unattributed "unknown", which is the one thing that accounting exists to stop."""
    serving(["UBC"])
    _ceiling(monkeypatch, 70)
    db.reset_cost()
    conn = _MeteredConn([(1000, 40000, 1200), (1040, 40050, 1240)], pct=84)

    class _Pyodbc:
        Error = RuntimeError

        @staticmethod
        def connect(conn_str, **kw):
            return conn

    monkeypatch.setattr(db, "pyodbc", _Pyodbc)
    monkeypatch.setattr(server_load, "db", db)  # the real connection factory, so the sample is measured
    try:
        reply = channel._dispatch("sync_pos", "UBC", {}, None, True)

        assert reply["error"]["error"] == "server_busy"  # it was refused, so only the sample ran
        booked = db.cost_snapshot()["companies"]
        assert all("unknown" not in totals["by_op"] for totals in booked.values())
        assert list(booked) == [get_settings().sql.system_db]  # the system db it sampled through
        assert booked[get_settings().sql.system_db]["by_op"] == {
            "server_load": {"ops": 1, "cpu_ms": 40, "logical_reads": 50, "elapsed_ms": 40}
        }
    finally:
        db.reset_cost()


# --- the command timeout a background read gets --------------------------------------------------------


class _TimedConn:
    """Records the command timeout db set on it. No session accounting, so nothing is booked."""

    def __init__(self):
        self.autocommit = True
        self.timeout = None
        self.closed = False

    def cursor(self):
        return _TimedCursor()

    def close(self):
        self.closed = True


class _TimedCursor:
    def execute(self, sql, *params):
        return self

    def fetchone(self):
        return None


def _timeout_seen(monkeypatch, serving, *, background):
    serving(["UBC"])
    conn = _TimedConn()

    class _Pyodbc:
        Error = RuntimeError

        @staticmethod
        def connect(conn_str, **kw):
            return conn

    monkeypatch.setattr(db, "pyodbc", _Pyodbc)
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [])
    reply = channel._dispatch("list_jobs", "UBC", {}, None, background)
    assert reply["ok"] is True  # the load sample is unavailable in tests, so nothing is deferred
    return conn.timeout


def test_a_background_read_gets_the_short_command_timeout(monkeypatch, serving):
    # Nobody is waiting on it, so an overrunning statement is cancelled ON THE SERVER rather than
    # allowed the user-facing limit - the 30s open-book re-read that never finished is the reason.
    assert _timeout_seen(monkeypatch, serving, background=True) == (
        get_settings().gp.background_command_timeout_seconds
    )


def test_a_user_facing_read_keeps_the_normal_command_timeout(monkeypatch, serving):
    # Cutting somebody's own read short to save the server a few seconds is the wrong trade.
    assert _timeout_seen(monkeypatch, serving, background=False) == get_settings().sql.command_timeout


def test_the_two_timeouts_are_actually_different():
    assert get_settings().gp.background_command_timeout_seconds < get_settings().sql.command_timeout


def test_a_statement_the_server_cancelled_is_a_normal_sql_error(monkeypatch, serving, _no_real_sql):
    # pyodbc raises on the timeout; it must come back as the same sql_error any other SQL failure does,
    # so the backend retries the page rather than treating it as a protocol fault.
    serving(["UBC"])

    def _timed_out(conn):
        raise channel.pyodbc.Error("HYT00", "[HYT00] [Microsoft][ODBC Driver 17] Query timeout expired")

    monkeypatch.setattr(econnect, "list_jobs", _timed_out)
    reply = channel._dispatch("list_jobs", "UBC", {}, None, True)
    assert reply["ok"] is False
    assert reply["error"]["error"] == "sql_error"
    assert "timeout expired" in reply["error"]["message"].lower()


def test_the_background_timeout_defaults_to_twenty_seconds(tmp_path):
    assert get_settings(str(tmp_path / "none.toml")).gp.background_command_timeout_seconds == 20


def test_config_and_env_set_the_background_timeout(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nbackground_command_timeout_seconds = 8\n", encoding="utf-8")
    assert get_settings(str(cfg)).gp.background_command_timeout_seconds == 8
    monkeypatch.setenv("UCNEXUS_RELAY_BACKGROUND_TIMEOUT_SECONDS", "12")
    assert get_settings(str(tmp_path / "env.toml")).gp.background_command_timeout_seconds == 12


def test_the_background_timeout_is_never_zero(tmp_path):
    # 0 means "wait forever" to pyodbc, which is the exact failure this setting exists to prevent.
    cfg = tmp_path / "config.toml"
    cfg.write_text("[gp]\nbackground_command_timeout_seconds = 0\n", encoding="utf-8")
    assert get_settings(str(cfg)).gp.background_command_timeout_seconds == 1
