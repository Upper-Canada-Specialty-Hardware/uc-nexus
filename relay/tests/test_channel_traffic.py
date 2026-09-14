"""RELAY TRAFFIC: the relay's own in-memory record of the jobs it is running now and the jobs it has
finished since it started.

This is the relay half of NEXUS GP TRAFFIC. The window's tab and the /health block are both fed from
`channel.traffic_snapshot`, so what matters here is the bookkeeping underneath it:

- a job is in `running` while it runs and in `recent` the moment it stops, whatever stopped it
- a refused background op is a finished job with an error, not a missing one
- the per-company totals go on counting after `recent` has rolled over
- a summary line is a nicety, so an odd payload or result costs the line and never the row

Nothing here reaches GP: the jobs are dispatched with `_handle_job` stubbed, except the one test that
proves a real refusal lands as `server_busy`, which uses the faked SQL server the pacing tests use.
"""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from ucnexus_relay import channel, db, server_load
from ucnexus_relay.config import PRODUCTION_BACKEND_URL, get_settings

PR_URL = "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"

# Read once, at import: a test that replaces channel.get_settings to set the busy ceiling still has to
# hand _run_once a real channel config.
CHANNEL_CFG = get_settings().channel

# A ring-buffer record saying the GP server is pinned, so the busy gate has something to refuse on.
BUSY_RECORD = """<Record id="1044" type="RING_BUFFER_SCHEDULER_MONITOR" time="8813750">
  <SchedulerMonitorEvent><SystemHealth>
    <ProcessUtilization>95</ProcessUtilization><SystemIdle>1</SystemIdle>
  </SystemHealth></SchedulerMonitorEvent>
</Record>"""


@pytest.fixture(autouse=True)
def _empty_traffic():
    """The record is module-level and runs from process start, so one test's jobs would otherwise land
    in the next one's snapshot."""
    channel.reset_traffic()
    yield
    channel.reset_traffic()


class _FakeWs:
    """Just enough of a websockets client for _run_once: an async iterator of raw frames, plus send."""

    def __init__(self, frames, done):
        self._frames, self._done, self.sent = list(frames), done, []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        async def gen():
            for frame in self._frames:
                yield json.dumps(frame)
            await self._done.wait()

        return gen()


def _fake_connect(monkeypatch, ws):
    class _Cm:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(channel.websockets, "connect", lambda url, **kw: _Cm())


async def _settle(times: int = 12) -> None:
    """Let the channel's own tasks run. The hello refreshes the company master on a real thread, so
    this yields with a small delay rather than only to the event loop."""
    for _ in range(times):
        await asyncio.sleep(0.005)


@contextmanager
def _measuring():
    """db.measuring without a GP server: the busy gate names its own sample, and that naming must not
    try to open a connection in a test run."""
    yield SimpleNamespace(cost=None)


def _finish(job, url=PRODUCTION_BACKEND_URL, reply=None, payload=None):
    """One job's whole life, start to finish, without a socket: the seam _dispatch_job uses."""
    row = channel._traffic_start(job, url)
    channel._traffic_finish(row, payload if payload is not None else (job.get("payload") or {}), reply or {})
    return row


# --- the bookkeeping through the channel's own dispatch ----------------------------------------------


def test_a_job_is_running_while_it_runs_and_recent_once_it_has_finished(monkeypatch, clean_channel_states):
    """The two halves of the tab: what is in flight now, and what has already crossed. Driven through
    _run_once so the wiring in _dispatch_job is what is under test, not a helper called by hand."""
    release = asyncio.Event()

    async def fake_handle_job(job, allowed_companies=None):
        await release.wait()
        return {
            "id": job["id"],
            "ok": True,
            "result": {"pos": [{"po": "PO012346"}, {"po": "PO012347"}]},
            "cost": {"cpu_ms": 31, "logical_reads": 900, "elapsed_ms": 120},
        }

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)

    async def run():
        done = asyncio.Event()
        ws = _FakeWs(
            [
                {
                    "id": "j1",
                    "op": "sync_pos",
                    "company": "UBC",
                    "background": True,
                    "payload": {"cursor": "PO012345", "open_only": True},
                }
            ],
            done,
        )
        _fake_connect(monkeypatch, ws)
        task = asyncio.create_task(channel._run_once(PRODUCTION_BACKEND_URL, "secret", get_settings().channel))
        await _settle()
        in_flight = channel.traffic_snapshot()
        release.set()
        await _settle()
        finished = channel.traffic_snapshot()
        done.set()
        await task
        return in_flight, finished

    in_flight, finished = asyncio.run(run())

    running = in_flight["running"]
    assert [(r["id"], r["op"], r["company"], r["background"]) for r in running] == [("j1", "sync_pos", "UBC", True)]
    assert running[0]["url"] == PRODUCTION_BACKEND_URL  # whose work it was
    assert running[0]["elapsed_ms"] >= 0
    assert running[0]["started_at"].endswith("Z")
    assert in_flight["recent"] == []

    assert finished["running"] == []
    row = finished["recent"][-1]
    assert (row["id"], row["ok"], row["error_code"]) == ("j1", True, None)
    assert row["cost"] == {"cpu_ms": 31, "logical_reads": 900, "elapsed_ms": 120}
    assert row["summary"] == "2 POs from PO012345 (open only)"
    assert finished["totals"]["UBC"]["sync_pos"]["count"] == 1
    assert finished["totals"]["UBC"]["sync_pos"]["ok"] == 1


def test_a_job_that_never_answered_still_leaves_the_running_list(monkeypatch, clean_channel_states):
    """A crashing job must not read on the tab as GP work stuck in flight forever - the same reason
    _INFLIGHT is decremented in a finally."""

    async def fake_handle_job(job, allowed_companies=None):
        raise RuntimeError("the job frame was not a job")

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)

    async def run():
        done = asyncio.Event()
        ws = _FakeWs([{"id": "j1", "op": "list_jobs", "company": "UBC"}], done)
        _fake_connect(monkeypatch, ws)
        task = asyncio.create_task(channel._run_once(PRODUCTION_BACKEND_URL, "secret", get_settings().channel))
        await _settle()
        done.set()
        await task
        return channel.traffic_snapshot()

    snapshot = asyncio.run(run())

    assert snapshot["running"] == []
    assert snapshot["recent"][-1]["ok"] is False
    assert channel._INFLIGHT == 0


def test_a_job_carries_the_channel_it_arrived_on(monkeypatch, clean_channel_states):
    """A preview backend's job is real GP work, and the tab has to be able to say whose it was."""
    release = asyncio.Event()

    async def fake_handle_job(job, allowed_companies=None):
        await release.wait()
        return {"id": job["id"], "ok": True, "result": {}}

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)

    async def run():
        done = asyncio.Event()
        ws = _FakeWs([{"id": "j1", "op": "list_jobs", "company": "TUBC"}], done)
        _fake_connect(monkeypatch, ws)
        task = asyncio.create_task(channel._run_once(PR_URL, "secret", CHANNEL_CFG))
        await _settle()
        in_flight = channel.traffic_snapshot()
        release.set()
        await _settle()
        done.set()
        await task
        return in_flight

    in_flight = asyncio.run(run())

    assert [r["url"] for r in in_flight["running"]] == [PR_URL]
    assert channel.traffic_snapshot()["recent"][-1]["company"] == "TUBC"


def test_a_refused_background_op_is_a_finished_job_with_server_busy(monkeypatch, serving, clean_channel_states):
    """A refusal is not a missing job: the operator's question is "is the mirror being held back", and
    a silent gap in the record cannot answer it."""
    serving(["UBC"])
    monkeypatch.setattr(
        channel, "get_settings", lambda *a, **k: SimpleNamespace(gp=SimpleNamespace(load_ceiling_pct=70))
    )

    class _Cursor:
        def __init__(self, conn):
            self._conn, self._row = conn, None

        def execute(self, sql, *params):
            self._row = (BUSY_RECORD,) if "dm_os_ring_buffers" in sql else (0,)
            return self

        def fetchone(self):
            return self._row

    class _Conn:
        def cursor(self):
            return _Cursor(self)

    class _Db:
        @staticmethod
        @contextmanager
        def get_read_connection(company):
            yield _Conn()

    monkeypatch.setattr(server_load, "db", _Db)
    monkeypatch.setattr(db, "measuring", lambda *a, **k: _measuring())

    async def run():
        done = asyncio.Event()
        ws = _FakeWs([{"id": "j1", "op": "sync_pos", "company": "UBC", "background": True}], done)
        _fake_connect(monkeypatch, ws)
        # cfg is read before get_settings is replaced above, which is why it is passed in rather than
        # looked up inside the channel.
        task = asyncio.create_task(channel._run_once(PRODUCTION_BACKEND_URL, "secret", CHANNEL_CFG))
        await _settle()
        done.set()
        await task
        return channel.traffic_snapshot()

    snapshot = asyncio.run(run())

    row = snapshot["recent"][-1]
    assert (row["ok"], row["error_code"]) == (False, "server_busy")
    assert snapshot["totals"]["UBC"]["sync_pos"] == {
        "count": 1,
        "ok": 0,
        "errors": 1,
        "elapsed_ms": row["elapsed_ms"],
    }


# --- the record itself -------------------------------------------------------------------------------


def test_the_totals_go_on_counting_after_recent_has_rolled_over():
    for i in range(350):
        _finish({"id": f"j{i}", "op": "list_jobs", "company": "UBC"}, reply={"ok": True, "result": {"jobs": []}})

    snapshot = channel.traffic_snapshot()
    assert len(snapshot["recent"]) == channel.TRAFFIC_RECENT_MAX == 300
    assert snapshot["recent"][-1]["id"] == "j349"  # newest last
    assert snapshot["recent"][0]["id"] == "j50"  # and the oldest 50 have fallen off
    assert snapshot["totals"]["UBC"]["list_jobs"]["count"] == 350


def test_an_error_and_a_success_are_counted_apart():
    _finish({"id": "j1", "op": "create_po", "company": "UBC"}, reply={"ok": True, "result": {"po_number": "PO1"}})
    _finish(
        {"id": "j2", "op": "create_po", "company": "UBC"},
        reply={"ok": False, "error": {"error": "econnect_error", "message": "no"}},
    )

    totals = channel.traffic_snapshot()["totals"]["UBC"]["create_po"]
    assert (totals["count"], totals["ok"], totals["errors"]) == (2, 1, 1)


def test_a_companyless_op_is_totalled_under_the_empty_company():
    """server_load asks about the server, not about a company. What it costs and how often it runs is
    exactly what the pacing questions are about, so it is recorded rather than dropped."""
    _finish({"id": "j1", "op": "server_load"}, reply={"ok": True, "result": {"sql_cpu_pct": 12}})

    snapshot = channel.traffic_snapshot()
    assert snapshot["recent"][-1]["company"] == ""
    assert snapshot["totals"][""]["server_load"]["count"] == 1


def test_a_job_frame_with_no_id_still_counts_and_keeps_its_own_row():
    """The backend always sends an id, but an unidentified job is still a GP round-trip. Without a key
    of its own every such job would overwrite the last one in the running list."""
    first = channel._traffic_start({"op": "server_load"}, PRODUCTION_BACKEND_URL)
    second = channel._traffic_start({"op": "server_load"}, PRODUCTION_BACKEND_URL)

    assert first["id"] != second["id"]
    assert len(channel.traffic_snapshot()["running"]) == 2


def test_reset_traffic_empties_everything():
    _finish({"id": "j1", "op": "list_jobs", "company": "UBC"}, reply={"ok": True, "result": {"jobs": []}})
    channel._traffic_start({"id": "j2", "op": "list_jobs", "company": "UBC"}, PRODUCTION_BACKEND_URL)

    channel.reset_traffic()

    assert channel.traffic_snapshot()["running"] == []
    assert channel.traffic_snapshot()["recent"] == []
    assert channel.traffic_snapshot()["totals"] == {}


def test_the_snapshot_is_a_copy_rather_than_the_live_record():
    """/health serialises this on a threadpool worker while jobs keep finishing on their own threads;
    handing out the live structures is the bug db.cost_snapshot guards against."""
    _finish({"id": "j1", "op": "list_jobs", "company": "UBC"}, reply={"ok": True, "result": {"jobs": []}})

    snapshot = channel.traffic_snapshot()
    snapshot["recent"].clear()
    snapshot["totals"].clear()

    assert len(channel.traffic_snapshot()["recent"]) == 1
    assert channel.traffic_snapshot()["totals"]["UBC"]["list_jobs"]["count"] == 1


# --- the summary line --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("op", "payload", "result", "expected"),
    [
        ("sync_pos", {"cursor": "PO012345", "open_only": True}, {"pos": [{}] * 25}, "25 POs from PO012345 (open only)"),
        ("sync_pos", {}, {"pos": [{}] * 12}, "12 POs from start"),
        ("read_pos_by_number", {"po_numbers": ["A", "B", "C"]}, {"pos": [{}] * 3}, "3 POs by number"),
        ("list_jobs", {}, {"jobs": [{}] * 84}, "84 jobs"),
        ("job_setup_health", {"jobs": ["1"]}, {"jobs": [{}] * 6}, "6 jobs checked"),
        ("create_po", {}, {"po_number": "PO012350"}, "PO PO012350"),
        ("create_receipt", {}, {"receipt_number": "RCT0042"}, "receipt RCT0042"),
        ("server_load", {}, {"sql_cpu_pct": 12}, "CPU 12%"),
        ("list_vendors", {}, {"vendors": [{}]}, None),
    ],
)
def test_the_summary_says_what_each_op_actually_did(op, payload, result, expected):
    assert channel._summarise(op, payload, {"ok": True, "result": result}) == expected


@pytest.mark.parametrize(
    ("op", "payload", "reply"),
    [
        # A failed job read nothing, so "0 POs from start" - a successful empty page - would be a lie.
        ("sync_pos", {}, {"ok": False, "error": {"error": "sql_error"}}),
        ("list_jobs", {}, {"ok": True, "result": None}),
        ("job_setup_health", {}, "not a reply"),
        ("create_po", {}, {"ok": True, "result": {}}),  # answered, but with no PO number in it
        ("server_load", {}, {"ok": True, "result": {"sql_cpu_pct": None}}),  # no reading to report
        ("list_vendors", {}, {"ok": True, "result": {"vendors": [{}]}}),  # an op with nothing to say
    ],
)
def test_there_is_no_summary_when_there_is_nothing_to_say(op, payload, reply):
    assert channel._summarise(op, payload, reply) is None


@pytest.mark.parametrize("payload", ["not a dict", {"cursor": 17}, None, {"open_only": object()}])
def test_an_odd_payload_never_takes_the_row_down_with_it(payload):
    # The summary reads a payload some backend sent, so a surprise in it must cost the line at most.
    assert channel._summarise("sync_pos", payload, {"ok": True, "result": {"pos": []}}).startswith("0 POs")


def test_a_payload_that_raises_on_being_read_costs_only_the_summary():
    class _Hostile(dict):
        def get(self, *args, **kwargs):
            raise RuntimeError("this payload does not answer questions")

    assert channel._summarise("sync_pos", _Hostile(), {"ok": True, "result": {"pos": []}}) is None


def test_a_failed_job_records_its_error_code_and_no_summary():
    _finish(
        {"id": "j1", "op": "sync_pos", "company": "UBC", "background": True},
        reply={"ok": False, "error": {"error": "sql_error", "message": "timeout"}},
    )

    row = channel.traffic_snapshot()["recent"][-1]
    assert (row["ok"], row["error_code"], row["summary"]) == (False, "sql_error", None)
