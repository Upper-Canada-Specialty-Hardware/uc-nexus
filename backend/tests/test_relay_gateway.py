"""relay_gateway: WebSocket auth, relay_call correlation, timeouts, keepalive liveness.

No DATABASE_URL and no live GP dependency: `_authenticate` (the one DB-backed call) is
monkeypatched out, and the relay itself is a FakeWebSocket - an in-memory queue standing in
for the real socket - so these run as plain unit tests.
"""

import asyncio

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

import main as main_module
from app.services import relay_gateway as relay_gateway_module
from app.services.relay_gateway import (
    RelayCallError,
    RelayGateway,
    RelayNotConnectedError,
    RelayTimeoutError,
)

_DISCONNECT = object()


class FakeWebSocket:
    """Stands in for the real relay socket: an in-memory queue instead of a network stream."""

    def __init__(self, headers=None):
        self.headers = headers or {"authorization": "Bearer whatever"}
        self.sent: list[dict] = []
        self._inbox: asyncio.Queue = asyncio.Queue()
        self.accepted = False
        self.close_code = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, data):
        self.sent.append(data)

    async def receive_json(self):
        item = await self._inbox.get()
        if item is _DISCONNECT:
            raise WebSocketDisconnect()
        return item

    async def close(self, code=1000):
        self.close_code = code
        await self._inbox.put(_DISCONNECT)

    async def push(self, data):
        await self._inbox.put(data)


def _new_gateway(authenticated: bool = True) -> RelayGateway:
    gw = RelayGateway()
    gw._authenticate = lambda secret: authenticated
    return gw


async def _connect(gw: RelayGateway) -> tuple[FakeWebSocket, "asyncio.Task"]:
    ws = FakeWebSocket()
    task = asyncio.create_task(gw.accept(ws))
    await asyncio.sleep(0)  # let accept() run up to the receive loop
    return ws, task


def test_rejects_unauthenticated_socket():
    async def run():
        gw = _new_gateway(authenticated=False)
        ws, task = await _connect(gw)
        await task
        assert not ws.accepted
        assert ws.close_code == 4401
        assert not gw.is_connected()

    asyncio.run(run())


def test_accepts_authenticated_socket():
    async def run():
        gw = _new_gateway(authenticated=True)
        ws, task = await _connect(gw)
        assert ws.accepted
        assert gw.is_connected()
        await ws.close()
        await task

    asyncio.run(run())


def test_relay_call_sends_job_and_resolves_on_matching_reply():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        call = asyncio.create_task(gw.relay_call("TUBC", "list_vendors", {}))
        await asyncio.sleep(0)
        assert len(ws.sent) == 1
        job = ws.sent[0]
        assert job["op"] == "list_vendors"
        assert job["company"] == "TUBC"

        await ws.push({"id": job["id"], "ok": True, "result": {"vendors": []}})
        assert await call == {"vendors": []}

        await ws.close()
        await task

    asyncio.run(run())


def test_relay_call_raises_on_ok_false_reply():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        call = asyncio.create_task(gw.relay_call("TUBC", "create_po", {}))
        await asyncio.sleep(0)
        job = ws.sent[0]
        await ws.push({"id": job["id"], "ok": False, "error": "GP is unhappy"})

        with pytest.raises(RelayCallError, match="GP is unhappy"):
            await call

        await ws.close()
        await task

    asyncio.run(run())


def test_concurrent_calls_do_not_cross_replies():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        call_a = asyncio.create_task(gw.relay_call("TUBC", "list_vendors", {}))
        call_b = asyncio.create_task(gw.relay_call("TUBC", "list_jobs", {}))
        await asyncio.sleep(0)
        assert len(ws.sent) == 2
        job_a = next(j for j in ws.sent if j["op"] == "list_vendors")
        job_b = next(j for j in ws.sent if j["op"] == "list_jobs")
        assert job_a["id"] != job_b["id"]

        # answer out of order, on purpose
        await ws.push({"id": job_b["id"], "ok": True, "result": "jobs-result"})
        await ws.push({"id": job_a["id"], "ok": True, "result": "vendors-result"})

        assert await call_a == "vendors-result"
        assert await call_b == "jobs-result"

        await ws.close()
        await task

    asyncio.run(run())


def test_relay_call_times_out_without_a_reply():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        with pytest.raises(RelayTimeoutError):
            await gw.relay_call("TUBC", "list_vendors", {}, timeout=0.05)

        await ws.close()
        await task

    asyncio.run(run())


def test_relay_call_raises_distinct_error_when_nothing_connected():
    async def run():
        gw = _new_gateway()
        with pytest.raises(RelayNotConnectedError):
            await gw.relay_call("TUBC", "list_vendors", {})

    asyncio.run(run())


def test_ping_keeps_connection_alive_without_being_treated_as_a_reply():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        await ws.push({"type": "ping"})
        await asyncio.sleep(0)
        assert {"type": "pong"} in ws.sent
        assert gw.is_connected()

        await ws.close()
        await task

    asyncio.run(run())


def test_disconnect_flips_state_and_fails_pending_calls():
    async def run():
        gw = _new_gateway()
        ws, task = await _connect(gw)

        call = asyncio.create_task(gw.relay_call("TUBC", "list_vendors", {}))
        await asyncio.sleep(0)

        await ws.close()
        await task

        assert not gw.is_connected()
        with pytest.raises(RelayNotConnectedError):
            await call

    asyncio.run(run())


def test_new_connection_supersedes_and_fails_old_pending_calls():
    async def run():
        gw = _new_gateway()
        ws1, task1 = await _connect(gw)

        call = asyncio.create_task(gw.relay_call("TUBC", "list_vendors", {}))
        await asyncio.sleep(0)

        ws2, task2 = await _connect(gw)  # a second authenticated connect replaces the first

        with pytest.raises(RelayNotConnectedError):
            await call
        assert gw.is_connected()  # the new connection is still tracked as live

        await ws1.close()
        await ws2.close()
        await task1
        await task2

    asyncio.run(run())


def test_missed_keepalive_marks_connection_dead(monkeypatch):
    monkeypatch.setattr(relay_gateway_module, "_WATCHDOG_TICK", 0.01)
    monkeypatch.setattr(relay_gateway_module, "_DEAD_AFTER", 0.03)

    async def run():
        gw = _new_gateway()
        _ws, task = await _connect(gw)

        await asyncio.sleep(0.2)

        await task
        assert not gw.is_connected()

    asyncio.run(run())


def test_relay_link_route_delegates_to_the_gateway(monkeypatch):
    """Exercises the actual /relay-link FastAPI route (main.py), not just the RelayGateway class."""
    fresh = RelayGateway()
    fresh._authenticate = lambda secret: True
    monkeypatch.setattr(main_module, "relay_gateway", fresh)

    client = TestClient(main_module.app)
    with client.websocket_connect("/relay-link", headers={"authorization": "Bearer good-secret"}):
        assert fresh.is_connected()


def test_relay_link_route_rejects_unauthenticated(monkeypatch):
    fresh = RelayGateway()
    fresh._authenticate = lambda secret: False
    monkeypatch.setattr(main_module, "relay_gateway", fresh)

    client = TestClient(main_module.app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/relay-link", headers={"authorization": "Bearer bad"}):
            pass
    assert not fresh.is_connected()
