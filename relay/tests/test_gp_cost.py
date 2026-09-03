"""What an op costs the GP server: APP=UCNexusRelay on every connection, and the per-session
sys.dm_exec_sessions delta booked against (company, op).

pyodbc is faked - the fake cursor answers the DMV SELECT from a scripted list of readings, so a test
decides exactly what the "server" reports on open and on close. Nothing here reaches GP.
"""

import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import auth, channel, db, econnect
from ucnexus_relay.main import create_app


def _body(reply: dict) -> dict:
    """A dispatch reply without the two pacing fields every reply now carries (`cost`, `server`), so a
    test can go on asserting the exact {ok, result|error} it is actually about."""
    return {key: value for key, value in reply.items() if key not in ("cost", "server")}


@pytest.fixture(autouse=True)
def _empty_totals():
    """The accumulator is module-level and runs from process start, so it has to be emptied around
    every test or one test's ops end up in the next one's snapshot."""
    db.reset_cost()
    yield
    db.reset_cost()


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._row = None

    def execute(self, sql, *params):
        self._conn.sql.append(sql)
        if "dm_exec_sessions" in sql:
            if self._conn.dmv_raises is not None:
                raise self._conn.dmv_raises
            self._row = self._conn.samples.pop(0) if self._conn.samples else None
        else:
            self._row = None
        return self

    def fetchone(self):
        return self._row


class _Conn:
    """A pyodbc connection that answers the DMV read with the next scripted (cpu, reads, elapsed)."""

    def __init__(self, samples=(), dmv_raises=None, autocommit=True):
        self.samples = list(samples)
        self.dmv_raises = dmv_raises
        self.autocommit = autocommit
        self.timeout = None
        self.sql = []
        self.rollbacks = 0
        self.commits = 0
        self.closed = False

    def cursor(self):
        return _Cursor(self)

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _fake_pyodbc(monkeypatch, *conns):
    """Hand db.py a pyodbc whose connect() returns the given connections in order."""
    queue = list(conns)
    seen = {"conn_strings": []}

    class _Pyodbc:
        Error = RuntimeError

        @staticmethod
        def connect(conn_str, **kw):
            seen["conn_strings"].append(conn_str)
            return queue.pop(0) if len(queue) > 1 else queue[0]

        @staticmethod
        def drivers():
            return []

    monkeypatch.setattr(db, "pyodbc", _Pyodbc)
    return seen


# --- attributability --------------------------------------------------------------------------------


def test_the_connection_string_names_the_application():
    # The server-side half of this: a DBA filtering sys.dm_exec_sessions or Activity Monitor on
    # program_name has to be able to see the relay's sessions as the relay's.
    assert "APP=UCNexusRelay" in db.build_conn_string("TUBC")


def test_the_connection_string_still_names_the_company_database():
    assert "DATABASE=TUCSH" in db.build_conn_string("TUCSH")


# --- the delta --------------------------------------------------------------------------------------


def test_a_reading_on_open_and_on_close_is_booked_as_the_difference(monkeypatch):
    # cpu_time / logical_reads / total_elapsed_time are cumulative for the session's life and pyodbc
    # pools, so the close value alone would charge this op for every op that ran on the session before
    # it.
    conn = _Conn(samples=[(1000, 40000, 1200), (1812, 85210, 2540)])
    _fake_pyodbc(monkeypatch, conn)

    with db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
        pass

    totals = db.cost_snapshot()["companies"]["TUCSH"]
    assert totals == {
        "ops": 1,
        "cpu_ms": 812,
        "logical_reads": 45210,
        "elapsed_ms": 1340,
        "by_op": {"sync_pos": {"ops": 1, "cpu_ms": 812, "logical_reads": 45210, "elapsed_ms": 1340}},
    }


def test_the_op_is_measured_even_when_it_fails(monkeypatch):
    # A failed op burned the CPU it burned; not counting it is how a runaway hides.
    conn = _Conn(samples=[(100, 10, 100), (400, 60, 900)])
    _fake_pyodbc(monkeypatch, conn)

    with pytest.raises(RuntimeError), db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
        raise RuntimeError("boom")

    assert db.cost_snapshot()["companies"]["TUCSH"]["cpu_ms"] == 300


def test_the_measurement_leaves_no_transaction_on_a_manual_commit_connection(monkeypatch):
    # The SELECT opens an implicit transaction on an autocommit=False connection, and the eConnect
    # orchestration's own BEGIN..COMMIT scope must be exactly what it was before this existed.
    conn = _Conn(samples=[(1, 1, 1), (2, 2, 2)], autocommit=False)
    _fake_pyodbc(monkeypatch, conn)

    with db.measuring("create_po", "TUBC"), db.get_connection("TUBC"):
        pass

    assert conn.rollbacks == 2  # one per reading, and nothing else was rolled back
    assert conn.closed


def test_a_reading_the_server_will_not_give_records_nothing(monkeypatch):
    conn = _Conn(dmv_raises=RuntimeError("VIEW SERVER STATE denied"))
    _fake_pyodbc(monkeypatch, conn)

    with db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
        pass

    assert db.cost_snapshot()["companies"] == {}


def test_the_unavailable_reason_is_logged_once_per_process(monkeypatch, caplog):
    conn = _Conn(dmv_raises=RuntimeError("VIEW SERVER STATE denied"))
    _fake_pyodbc(monkeypatch, conn)

    with caplog.at_level("DEBUG"):
        for _ in range(3):
            with db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
                pass

    lines = [r for r in caplog.records if r.message == "gp cost measurement unavailable"]
    assert len(lines) == 1
    assert "VIEW SERVER STATE denied" in lines[0].error


# --- the accumulator --------------------------------------------------------------------------------


def test_totals_add_up_per_company_and_per_op(monkeypatch):
    conn = _Conn(
        samples=[
            (0, 0, 0), (100, 1000, 200),      # TUCSH / sync_pos
            (100, 1000, 200), (250, 4000, 700),  # TUCSH / sync_pos again
            (250, 4000, 700), (300, 4500, 800),  # TUCSH / list_vendors
            (0, 0, 0), (10, 20, 30),          # TUBC / list_vendors
        ]
    )
    _fake_pyodbc(monkeypatch, conn)

    ran = (("sync_pos", "TUCSH"), ("sync_pos", "TUCSH"), ("list_vendors", "TUCSH"), ("list_vendors", "TUBC"))
    for op, company in ran:
        with db.measuring(op, company), db.get_read_connection(company):
            pass

    companies = db.cost_snapshot()["companies"]
    assert companies["TUCSH"]["ops"] == 3
    assert companies["TUCSH"]["cpu_ms"] == 100 + 150 + 50
    assert companies["TUCSH"]["logical_reads"] == 1000 + 3000 + 500
    assert companies["TUCSH"]["elapsed_ms"] == 200 + 500 + 100
    assert companies["TUCSH"]["by_op"]["sync_pos"] == {
        "ops": 2, "cpu_ms": 250, "logical_reads": 4000, "elapsed_ms": 700
    }
    assert companies["TUCSH"]["by_op"]["list_vendors"]["ops"] == 1
    assert companies["TUBC"] == {
        "ops": 1,
        "cpu_ms": 10,
        "logical_reads": 20,
        "elapsed_ms": 30,
        "by_op": {"list_vendors": {"ops": 1, "cpu_ms": 10, "logical_reads": 20, "elapsed_ms": 30}},
    }


def test_the_snapshot_is_a_copy(monkeypatch):
    conn = _Conn(samples=[(0, 0, 0), (5, 5, 5)])
    _fake_pyodbc(monkeypatch, conn)
    with db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
        pass

    snapshot = db.cost_snapshot()
    snapshot["companies"]["TUCSH"]["cpu_ms"] = 999
    snapshot["companies"]["TUCSH"]["by_op"]["sync_pos"]["cpu_ms"] = 999
    assert db.cost_snapshot()["companies"]["TUCSH"]["cpu_ms"] == 5
    assert db.cost_snapshot()["companies"]["TUCSH"]["by_op"]["sync_pos"]["cpu_ms"] == 5


def test_a_connection_opened_with_no_op_named_is_booked_as_unknown(monkeypatch):
    conn = _Conn(samples=[(0, 0, 0), (7, 8, 9)])
    _fake_pyodbc(monkeypatch, conn)
    with db.get_read_connection("TUBC"):
        pass
    assert db.cost_snapshot()["companies"]["TUBC"]["by_op"]["unknown"]["cpu_ms"] == 7


# --- attribution from the channel ---------------------------------------------------------------------


def test_a_dispatched_op_is_booked_against_its_op_name_and_company(monkeypatch, serving):
    serving(["TUBC"])
    conn = _Conn(samples=[(500, 2000, 600), (700, 9000, 1100)])
    _fake_pyodbc(monkeypatch, conn)
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [{"vendor_id": "V1"}])

    reply = channel._dispatch("list_vendors", "TUBC", {})

    assert reply["ok"] is True
    assert db.cost_snapshot()["companies"]["TUBC"]["by_op"]["list_vendors"] == {
        "ops": 1, "cpu_ms": 200, "logical_reads": 7000, "elapsed_ms": 500
    }


def test_a_dmv_that_refuses_leaves_the_op_result_untouched(monkeypatch, serving):
    serving(["TUBC"])
    _fake_pyodbc(monkeypatch, _Conn(dmv_raises=RuntimeError("no")))
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [{"vendor_id": "V1"}])

    reply = channel._dispatch("list_vendors", "TUBC", {})

    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "vendors": [{"vendor_id": "V1"}]}}
    assert db.cost_snapshot()["companies"] == {}


# --- /health ------------------------------------------------------------------------------------------


def test_health_carries_gp_cost():
    body = TestClient(create_app()).get("/health").json()
    assert body["gp_cost"]["since"]
    assert body["gp_cost"]["companies"] == {}


def test_health_reports_what_the_ops_cost(monkeypatch):
    conn = _Conn(samples=[(0, 0, 0), (812, 45210, 1340)])
    _fake_pyodbc(monkeypatch, conn)
    with db.measuring("sync_pos", "TUCSH"), db.get_read_connection("TUCSH"):
        pass

    body = TestClient(create_app()).get("/health").json()
    assert body["gp_cost"]["companies"]["TUCSH"]["cpu_ms"] == 812
    assert body["gp_cost"]["companies"]["TUCSH"]["by_op"]["sync_pos"]["logical_reads"] == 45210


def test_an_http_route_is_booked_against_its_path(monkeypatch, serving):
    serving(["TUBC"])
    conn = _Conn(samples=[(10, 100, 20), (60, 900, 320)])
    _fake_pyodbc(monkeypatch, conn)
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [])

    app = create_app()
    app.dependency_overrides[auth.verify_token] = lambda: None
    r = TestClient(app).get("/vendors", params={"company": "TUBC"})

    assert r.status_code == 200
    assert db.cost_snapshot()["companies"]["TUBC"]["by_op"]["http:/vendors"] == {
        "ops": 1, "cpu_ms": 50, "logical_reads": 800, "elapsed_ms": 300
    }
