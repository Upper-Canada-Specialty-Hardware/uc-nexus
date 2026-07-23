"""RelayGateway: live-connection tracking + relay_call() correlation/timeout/error behavior.

Plain `def test_...(): asyncio.run(...)` throughout (no pytest-asyncio dependency) - the codebase has
no async test infra yet, and this keeps that decision out of scope for this slice."""

import asyncio

import pytest

from app.errors import RelayCallError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
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


def test_register_ping_miss_does_not_reap_before_the_first_pong():
    # issue #277: a relay build that doesn't answer the data heartbeat yet must never be reaped on a
    # false positive - missed pings only count once the relay has proven it speaks the protocol.
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    assert gateway.register_ping_miss() is False
    assert gateway.register_ping_miss() is False
    assert gateway.register_ping_miss() is False


def test_register_ping_miss_reaps_after_two_misses_once_armed():
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    gateway.note_pong()  # the first pong arms the reaper
    assert gateway.register_ping_miss() is False  # 1 unanswered ping
    assert gateway.register_ping_miss() is True  # 2 unanswered pings -> reap


def test_note_pong_resets_the_miss_counter():
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    gateway.note_pong()
    assert gateway.register_ping_miss() is False
    gateway.note_pong()  # a responsive relay keeps the counter from ever reaching the reap threshold
    assert gateway.register_ping_miss() is False


def test_try_register_resets_heartbeat_state_for_the_new_connection():
    # A fresh connection must not inherit the previous socket's armed flag or miss count.
    gateway = RelayGateway()
    first_ws = FakeWebSocket()
    gateway.try_register("TUBC", first_ws)
    gateway.note_pong()
    gateway.register_ping_miss()
    gateway.unregister(first_ws)

    gateway.try_register("TUBC", FakeWebSocket())
    assert gateway.register_ping_miss() is False  # not armed yet on the new connection
    assert gateway.register_ping_miss() is False


# --- issue #315: op-parity guard (hello frame -> build/op-set, proactive + reactive) ---


def test_note_hello_records_build_and_op_set():
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    assert gateway.build is None  # nothing advertised yet
    gateway.note_hello("relay-v0.1.0-build.30", ["list_vendors", "list_tax_details", "create_po"])
    assert gateway.build == "relay-v0.1.0-build.30"


def test_try_register_and_unregister_clear_the_advertised_build():
    gateway = RelayGateway()
    ws = FakeWebSocket()
    gateway.try_register("TUBC", ws)
    gateway.note_hello("relay-v0.1.0-build.30", ["list_vendors"])
    gateway.unregister(ws)
    assert gateway.build is None
    # A new connection starts blank - it must not inherit the old relay's build/op-set.
    gateway.try_register("TUBC", FakeWebSocket())
    assert gateway.build is None


def test_relay_call_rejects_an_op_outside_the_advertised_set_without_sending():
    # Proactive parity: once the relay advertised its op-set, a call for an op it lacks fails fast with
    # RELAY_OP_UNSUPPORTED and never hits the wire (no 30s round-trip).
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        gateway.note_hello("relay-v0.1.0-build.28", ["list_vendors", "create_po"])  # no list_tax_details
        with pytest.raises(RelayOpUnsupportedError) as exc_info:
            await gateway.relay_call("TUBC", "list_tax_details", timeout=1)
        assert exc_info.value.op == "list_tax_details"
        assert exc_info.value.code == "RELAY_OP_UNSUPPORTED"
        assert ws.sent == []  # never sent

    asyncio.run(run())


def test_relay_call_allows_an_advertised_op():
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        gateway.note_hello("relay-v0.1.0-build.30", ["list_vendors", "list_tax_details"])

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": {"tax_details": []}})

        responder_task = asyncio.create_task(responder())
        result = await gateway.relay_call("TUBC", "list_tax_details", timeout=1)
        await responder_task
        assert result == {"tax_details": []}

    asyncio.run(run())


def test_relay_call_maps_an_unknown_op_reply_to_op_unsupported():
    # Reactive parity: an older relay that sends no hello (op-set unknown) skips the proactive check, so a
    # call for a missing op reaches it and comes back `unknown_op` - which must still surface as the clean
    # RELAY_OP_UNSUPPORTED, not a raw RelayCallError.
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)  # no note_hello -> op-set unknown

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve(
                {
                    "id": ws.sent[0]["id"],
                    "ok": False,
                    "error": {"error": "unknown_op", "message": "unknown op 'list_tax_details'", "context": {}},
                }
            )

        responder_task = asyncio.create_task(responder())
        with pytest.raises(RelayOpUnsupportedError) as exc_info:
            await gateway.relay_call("TUBC", "list_tax_details", timeout=1)
        await responder_task
        assert exc_info.value.op == "list_tax_details"
        assert exc_info.value.detail["error"] == "unknown_op"

    asyncio.run(run())
