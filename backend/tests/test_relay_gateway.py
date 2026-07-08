"""RelayGateway: live-connection tracking + relay_call() correlation/timeout/error behavior.

Plain `def test_...(): asyncio.run(...)` throughout (no pytest-asyncio dependency) - the codebase has
no async test infra yet, and this keeps that decision out of scope for this slice."""

import asyncio

import pytest

from app.errors import RelayCallError, RelayTimeoutError, RelayUnavailableError
from app.services.relay_gateway import RelayGateway


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


def test_relay_call_without_a_connection_raises_unavailable():
    async def run():
        gateway = RelayGateway()
        with pytest.raises(RelayUnavailableError):
            await gateway.relay_call("TUBC", "list_vendors")

    asyncio.run(run())


def test_relay_call_for_a_different_company_raises_unavailable():
    async def run():
        gateway = RelayGateway()
        gateway.try_register("TUBC", FakeWebSocket())
        with pytest.raises(RelayUnavailableError):
            await gateway.relay_call("TUCSH", "list_vendors")

    asyncio.run(run())


def test_try_register_exposes_connected_and_company():
    gateway = RelayGateway()
    assert gateway.connected is False
    assert gateway.company is None
    assert gateway.try_register("TUBC", FakeWebSocket()) is True
    assert gateway.connected is True
    assert gateway.company == "TUBC"


def test_relay_call_resolves_with_the_matching_reply():
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": {"vendors": []}})

        responder_task = asyncio.create_task(responder())
        result = await gateway.relay_call("TUBC", "list_vendors", timeout=1)
        await responder_task
        assert result == {"vendors": []}
        assert ws.sent[0]["op"] == "list_vendors"
        assert ws.sent[0]["company"] == "TUBC"

    asyncio.run(run())


def test_relay_call_times_out_when_no_reply_arrives():
    async def run():
        gateway = RelayGateway()
        gateway.try_register("TUBC", FakeWebSocket())
        with pytest.raises(RelayTimeoutError):
            await gateway.relay_call("TUBC", "list_vendors", timeout=0.05)

    asyncio.run(run())


def test_relay_call_raises_relay_call_error_on_ok_false():
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve(
                {"id": ws.sent[0]["id"], "ok": False, "error": {"error": "po_not_found", "message": "nope"}}
            )

        responder_task = asyncio.create_task(responder())
        with pytest.raises(RelayCallError) as exc_info:
            await gateway.relay_call("TUBC", "create_receipt", timeout=1)
        await responder_task
        assert exc_info.value.detail["error"] == "po_not_found"

    asyncio.run(run())


def test_a_second_connection_is_rejected_and_the_incumbent_is_undisturbed():
    # issue #202 #6: while a relay is connected, a second connecting relay is rejected (try_register ->
    # False, the route closes it 4409) rather than superseding the incumbent. The old supersede behaviour
    # could drop the in-flight reply for a GP write that had committed; here the incumbent's call still
    # resolves normally.
    async def run():
        gateway = RelayGateway()
        first_ws = FakeWebSocket()
        assert gateway.try_register("TUBC", first_ws) is True

        call_task = asyncio.create_task(gateway.relay_call("TUBC", "list_vendors", timeout=1))
        while not first_ws.sent:
            await asyncio.sleep(0)

        second_ws = FakeWebSocket()
        assert gateway.try_register("TUBC", second_ws) is False
        assert gateway.connected is True

        gateway.resolve({"id": first_ws.sent[0]["id"], "ok": True, "result": {"vendors": []}})
        assert await call_task == {"vendors": []}

    asyncio.run(run())


def test_unregister_fails_any_pending_calls():
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)

        call_task = asyncio.create_task(gateway.relay_call("TUBC", "list_vendors", timeout=1))
        while not ws.sent:
            await asyncio.sleep(0)

        gateway.unregister(ws)

        with pytest.raises(RelayUnavailableError):
            await call_task

    asyncio.run(run())
