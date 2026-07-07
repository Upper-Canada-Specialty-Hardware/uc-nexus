"""The outbound channel's job dispatch: {id, op, company, payload} -> {id, ok, result|error}.
Everything here is mocked at the db/econnect boundary — no real SQL, never touches GP. Covers:
op routing + reply correlation, the company/payload validation gates, and the WS connect call
(URL + Bearer auth header + keepalive interval) that dials the backend."""

import asyncio
import json
from contextlib import contextmanager

from ucnexus_relay import channel
from ucnexus_relay.config import get_settings

ALLOWED_COMPANY = get_settings().gp.allowed_companies[0]


def _run(coro):
    return asyncio.run(coro)


async def _drain(ws) -> None:
    """Await _serve(ws), then let any fire-and-forget job-handling tasks it scheduled via
    asyncio.ensure_future finish before the event loop closes (production doesn't need this —
    the loop stays alive via the concurrent uvicorn server; a standalone test does)."""
    await channel._serve(ws)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


class _FakeWS:
    def __init__(self, raws):
        self._raws = list(raws)
        self.sent: list[str] = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._raws:
            raise StopAsyncIteration
        return self._raws.pop(0)

    async def send(self, data):
        self.sent.append(data)


def _fake_read_connection(marker=None):
    """Returns a drop-in replacement for db.get_read_connection: a context manager yielding a
    sentinel "connection" (never real SQL), optionally recording the company it was called with."""

    @contextmanager
    def _fake(company):
        if marker is not None:
            marker.append(company)
        yield "FAKE_CONN"

    return _fake


# --- dispatch_job: routing + validation gates ---------------------------------------------------


def test_unknown_op_returns_clean_error():
    reply = _run(channel.dispatch_job({"id": "1", "op": "nonsense", "company": ALLOWED_COMPANY, "payload": {}}))
    assert reply == {
        "id": "1",
        "ok": False,
        "error": {"error": "unknown_op", "message": "unknown op 'nonsense'", "context": {}},
    }


def test_missing_op_key_reports_unknown_op():
    reply = _run(channel.dispatch_job({"id": "1b", "company": ALLOWED_COMPANY, "payload": {}}))
    assert reply["ok"] is False
    assert reply["error"]["error"] == "unknown_op"


def test_missing_company_returns_clean_error():
    reply = _run(channel.dispatch_job({"id": "2", "op": "list_jobs", "payload": {}}))
    assert reply["id"] == "2"
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_company"


def test_company_not_allowed_returns_clean_error():
    reply = _run(channel.dispatch_job({"id": "3", "op": "list_jobs", "company": "NOTREAL", "payload": {}}))
    assert reply == {
        "id": "3",
        "ok": False,
        "error": {
            "error": "company_not_allowed",
            "message": f"NOTREAL not in allowed_companies {get_settings().gp.allowed_companies}",
            "context": {},
        },
    }


def test_create_po_missing_required_fields_returns_invalid_payload():
    reply = _run(channel.dispatch_job({"id": "7", "op": "create_po", "company": ALLOWED_COMPANY, "payload": {}}))
    assert reply["id"] == "7"
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


def test_list_cost_codes_requires_job():
    reply = _run(
        channel.dispatch_job({"id": "6", "op": "list_cost_codes", "company": ALLOWED_COMPANY, "payload": {}})
    )
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_job"


# --- dispatch_job: successful op routing (db/econnect mocked) -----------------------------------


def test_list_jobs_dispatches_through_read_connection_and_correlates_reply(monkeypatch):
    calls = []
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection(calls))
    monkeypatch.setattr(
        channel.econnect, "list_jobs", lambda conn: [{"job_number": "80003", "job_name": "Tower", "status": "active"}]
    )

    reply = _run(channel.dispatch_job({"id": "job-42", "op": "list_jobs", "company": ALLOWED_COMPANY, "payload": {}}))

    assert calls == [ALLOWED_COMPANY]
    assert reply == {
        "id": "job-42",
        "ok": True,
        "result": {
            "company": ALLOWED_COMPANY,
            "jobs": [{"job_number": "80003", "job_name": "Tower", "status": "active"}],
        },
    }


def test_list_vendors_dispatches_through_read_connection(monkeypatch):
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    monkeypatch.setattr(
        channel.econnect,
        "list_vendors",
        lambda conn, active_only=True: [
            {"vendor_id": "V1", "vendor_name": "Acme", "vendor_class": None, "status": 1}
        ],
    )

    reply = _run(channel.dispatch_job({"id": "5", "op": "list_vendors", "company": ALLOWED_COMPANY, "payload": {}}))

    assert reply["ok"] is True
    assert reply["result"]["vendors"] == [{"vendor_id": "V1", "vendor_name": "Acme", "vendor_class": None, "status": 1}]


def test_list_buyers_dispatches_through_read_connection(monkeypatch):
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    monkeypatch.setattr(channel.econnect, "list_buyers", lambda conn: ["mira", "donr"])

    reply = _run(channel.dispatch_job({"id": "9", "op": "list_buyers", "company": ALLOWED_COMPANY, "payload": {}}))

    assert reply == {"id": "9", "ok": True, "result": {"company": ALLOWED_COMPANY, "buyers": ["mira", "donr"]}}


def test_list_cost_codes_dispatches_with_job_from_payload(monkeypatch):
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    seen_job = []

    def fake_list_cost_codes(conn, job):
        seen_job.append(job)
        return [{"cost_code": "210-200", "description": None, "cost_element": 2}]

    monkeypatch.setattr(channel.econnect, "list_cost_codes", fake_list_cost_codes)

    reply = _run(
        channel.dispatch_job(
            {"id": "10", "op": "list_cost_codes", "company": ALLOWED_COMPANY, "payload": {"job": "80003"}}
        )
    )

    assert seen_job == ["80003"]
    assert reply["ok"] is True
    assert reply["result"]["job"] == "80003"
    assert reply["result"]["cost_codes"][0]["cost_code"] == "210-200"


# --- dispatch_job: unexpected op failure never kills the channel --------------------------------


def test_op_raising_unexpected_exception_returns_internal_error(monkeypatch):
    def boom(conn):
        raise RuntimeError("boom")

    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    monkeypatch.setattr(channel.econnect, "list_jobs", boom)

    reply = _run(channel.dispatch_job({"id": "11", "op": "list_jobs", "company": ALLOWED_COMPANY, "payload": {}}))

    assert reply["id"] == "11"
    assert reply["ok"] is False
    assert reply["error"]["error"] == "internal_error"


# --- _serve: reply correlation over a fake socket, malformed frames don't crash it ---------------


def test_serve_dispatches_frame_and_sends_correlated_reply(monkeypatch):
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    monkeypatch.setattr(channel.econnect, "list_jobs", lambda conn: [])

    frame = json.dumps({"id": "z1", "op": "list_jobs", "company": ALLOWED_COMPANY, "payload": {}})
    ws = _FakeWS([frame])

    _run(_drain(ws))

    assert len(ws.sent) == 1
    reply = json.loads(ws.sent[0])
    assert reply == {"id": "z1", "ok": True, "result": {"company": ALLOWED_COMPANY, "jobs": []}}


def test_serve_ignores_malformed_json_frame():
    ws = _FakeWS(["not valid json{{{"])
    _run(_drain(ws))
    assert ws.sent == []


def test_serve_handles_concurrent_frames_independently(monkeypatch):
    monkeypatch.setattr(channel.db, "get_read_connection", _fake_read_connection())
    monkeypatch.setattr(channel.econnect, "list_jobs", lambda conn: [])
    monkeypatch.setattr(channel.econnect, "list_buyers", lambda conn: ["mira"])

    frames = [
        json.dumps({"id": "a", "op": "list_jobs", "company": ALLOWED_COMPANY, "payload": {}}),
        json.dumps({"id": "b", "op": "list_buyers", "company": ALLOWED_COMPANY, "payload": {}}),
    ]
    ws = _FakeWS(frames)

    _run(_drain(ws))

    ids = {json.loads(m)["id"] for m in ws.sent}
    assert ids == {"a", "b"}


# --- run_channel: dials the configured URL with Bearer auth + the 20s keepalive -----------------


class _FakeConnectCM:
    """Stands in for websockets.connect(...): records the call, then behaves as an immediately-
    empty async iterator so run_channel's `async for ws in ...` returns after one pass instead of
    looping forever."""

    calls: list[tuple[str, dict]] = []

    def __init__(self, uri, **kwargs):
        _FakeConnectCM.calls.append((uri, kwargs))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_run_channel_dials_configured_url_with_bearer_auth_and_keepalive(monkeypatch):
    _FakeConnectCM.calls = []
    monkeypatch.setattr(channel.websockets, "connect", _FakeConnectCM)

    _run(channel.run_channel())

    assert len(_FakeConnectCM.calls) == 1
    uri, kwargs = _FakeConnectCM.calls[0]
    settings = get_settings()
    assert uri == settings.backend.url
    assert kwargs["additional_headers"] == {"Authorization": f"Bearer {settings.auth.shared_secret}"}
    assert kwargs["ping_interval"] == channel._KEEPALIVE_SECONDS
