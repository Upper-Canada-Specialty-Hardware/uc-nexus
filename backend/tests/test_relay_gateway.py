"""RelayGateway: live-connection tracking + relay_call() correlation/timeout/error behavior.

Plain `def test_...(): asyncio.run(...)` throughout (no pytest-asyncio dependency) - the codebase has
no async test infra yet, and this keeps that decision out of scope for this slice."""

import asyncio
import logging
import uuid

import pytest

from app.errors import RelayCallError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
from app.services.relay_gateway import (
    DISCONNECT_REASON_PEER,
    DISCONNECT_REASON_SHUTDOWN,
    HEARTBEAT_MAX_MISSED,
    RelayGateway,
)


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


def test_register_ping_miss_gives_an_unarmed_connection_longer_before_reaping():
    # #353 PR F. issue #277 originally refused to reap an unarmed connection at all, to protect relay
    # builds predating the data heartbeat. That left a real gap: a relay that connects, takes the
    # single slot and never pongs held the slot until the platform reaped the dead TCP socket ~an
    # hour later, blocking every other relay and failing every GP write. The unarmed limit is longer
    # than the armed one, not absent.
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    assert gateway.register_ping_miss() is False  # 1
    assert gateway.register_ping_miss() is False  # 2 - would already reap an ARMED connection
    assert gateway.register_ping_miss() is False  # 3
    assert gateway.register_ping_miss() is True  # 4 (~80s) -> reap, freeing the slot


def test_register_ping_miss_reaps_after_two_misses_once_armed():
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    gateway.note_pong()  # the first pong arms the reaper
    assert gateway.register_ping_miss() is False  # 1 unanswered ping
    assert gateway.register_ping_miss() is True  # 2 unanswered pings -> reap


def test_a_pong_tightens_the_limit_from_unarmed_to_armed():
    # Answering once proves the relay speaks the heartbeat, so from then on silence is reaped at the
    # tighter armed limit rather than the unarmed one.
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket())
    gateway.register_ping_miss()
    gateway.note_pong()  # arms and resets
    assert gateway.register_ping_miss() is False
    assert gateway.register_ping_miss() is True  # two misses is enough once armed


def test_close_for_shutdown_says_going_away_and_closes_1012():
    # #353 PR F: a deploy must tell the relay it is a restart, so the relay reconnects at once instead
    # of growing its backoff and sitting out the start of the new deployment.
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        await gateway.close_for_shutdown()
        assert ws.sent == [{"type": "going_away"}]
        assert ws.closed_code == 1012
        assert gateway.connected is False

    asyncio.run(run())


def test_close_for_shutdown_is_a_no_op_with_no_relay_connected():
    async def run():
        gateway = RelayGateway()
        await gateway.close_for_shutdown()  # must not raise
        assert gateway.connected is False

    asyncio.run(run())


def test_close_for_shutdown_survives_a_socket_that_will_not_close():
    # A half-dead socket must not hold up process shutdown; the relay reconnects either way.
    async def run():
        class _Stuck(FakeWebSocket):
            async def send_json(self, data: dict) -> None:
                raise RuntimeError("socket is gone")

            async def close(self, code: int = 1000) -> None:
                raise RuntimeError("socket is gone")

        gateway = RelayGateway()
        ws = _Stuck()
        gateway.try_register("TUBC", ws)
        await gateway.close_for_shutdown()  # must not raise
        assert gateway.connected is False

    asyncio.run(run())


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


def test_note_hello_ignores_a_malformed_frame_without_raising():
    # The hello frame is untrusted wire input. A non-str build is dropped; a non-list op-set (or one with
    # non-str entries) is treated as 'unknown' rather than turned into a set of characters - otherwise
    # ops='list_vendors' would become {'l','i',...} and proactively reject every real op. It must not raise.
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        gateway.note_hello(123, "list_vendors")  # build is an int, ops is a bare string
        assert gateway.build is None  # non-str build dropped

        # op-set unknown -> proactive check skipped, so a real op is NOT rejected outright; it reaches
        # the wire and the relay answers it (proving _ops is not a set of characters).
        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": {"vendors": []}})

        responder_task = asyncio.create_task(responder())
        result = await gateway.relay_call("TUBC", "list_vendors", timeout=1)
        await responder_task
        assert result == {"vendors": []}

    asyncio.run(run())


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


# --- which install is live (#366) ---------------------------------------------------------------------
# The gateway knew a relay was connected but not WHICH install it was, so nothing could refuse to delete
# the row backing the live connection - deleting it revokes the secret out from under a running relay.


def test_try_register_records_the_install_backing_the_connection():
    gateway = RelayGateway()
    assert gateway.install_id is None
    install_id = uuid.uuid4()
    assert gateway.try_register("TUBC", FakeWebSocket(), install_id) is True
    assert gateway.install_id == install_id


def test_unregister_clears_the_install_id():
    gateway = RelayGateway()
    ws = FakeWebSocket()
    gateway.try_register("TUBC", ws, uuid.uuid4())
    gateway.unregister(ws)
    assert gateway.install_id is None
    assert gateway.connected is False


def test_an_older_caller_that_omits_the_install_id_still_registers():
    # try_register is also reached from tests and any path that has no row in hand; a missing id must
    # read as "unknown", never block the connection.
    gateway = RelayGateway()
    assert gateway.try_register("TUBC", FakeWebSocket()) is True
    assert gateway.install_id is None


# --- disconnect diagnosability (#384) -----------------------------------------------------------------
# The relay dropped for ~5 minutes on 2026-07-28 and reconnected on its own, and the logs could not say
# when it went, why, or for how long it had been up: unregister wrote nothing, so a socket held open for
# days produced exactly one log line (uvicorn's access log for the accept) for its entire lifetime.


def _records(caplog, level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno == level and r.name == "app.services.relay_gateway"]


def test_unregister_logs_the_disconnect_with_the_identity_and_how_long_it_was_held(caplog):
    gateway = RelayGateway()
    ws = FakeWebSocket()
    install_id = uuid.uuid4()
    gateway.try_register("TUBC", ws, install_id)
    gateway.note_hello("relay-v0.1.0-build.30", ["list_vendors"])

    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(ws)

    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1
    record = warnings[0]
    # Everything a disconnect has to be correlated against the relay's own logs must be IN THE MESSAGE,
    # not only in `extra`: uvicorn configures no root handler, so app records render through
    # logging.lastResort as the bare message and every extra field is dropped in production.
    assert str(install_id) in record.getMessage()
    assert "TUBC" in record.getMessage()
    assert "relay-v0.1.0-build.30" in record.getMessage()
    assert "held_seconds=" in record.getMessage()
    assert record.install_id == str(install_id)
    assert record.company == "TUBC"
    assert record.build == "relay-v0.1.0-build.30"
    assert record.held_seconds >= 0


def test_a_plain_disconnect_is_reported_as_peer_initiated(caplog):
    # Nothing on this side decided the disconnect, so the socket went away under us - a different
    # failure with a different owner than a reap, and the distinction is unrecoverable after the fact.
    gateway = RelayGateway()
    ws = FakeWebSocket()
    gateway.try_register("TUBC", ws)

    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(ws)

    record = _records(caplog, logging.WARNING)[0]
    assert record.reason == DISCONNECT_REASON_PEER
    assert DISCONNECT_REASON_PEER in record.getMessage()


def test_a_heartbeat_reap_is_reported_as_a_reap_with_the_miss_count(caplog):
    # register_ping_miss returning True is what makes main.py's heartbeat close the socket, which ends
    # the read loop and lands in the route's finally -> unregister. That moment is the only one that
    # knows we killed it, so the reason is stamped there and read back here.
    gateway = RelayGateway()
    ws = FakeWebSocket()
    gateway.try_register("TUBC", ws)
    gateway.note_pong()  # arm the reaper, so the tighter armed limit applies
    while not gateway.register_ping_miss():
        pass

    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(ws)

    record = _records(caplog, logging.WARNING)[0]
    assert record.reason.startswith("reaped after")
    assert f"{HEARTBEAT_MAX_MISSED} missed pings" in record.reason
    assert "armed" in record.reason
    assert record.reason in record.getMessage()


def test_a_reaped_reason_does_not_leak_into_the_next_connection(caplog):
    # try_register clears the stamp, so a relay that reconnects and later drops on its own is not
    # blamed for the previous connection's reap.
    gateway = RelayGateway()
    first_ws = FakeWebSocket()
    gateway.try_register("TUBC", first_ws)
    while not gateway.register_ping_miss():
        pass
    gateway.unregister(first_ws)

    second_ws = FakeWebSocket()
    gateway.try_register("TUBC", second_ws)
    caplog.clear()  # drop the first connection's disconnect line; only the second one is under test
    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(second_ws)

    assert _records(caplog, logging.WARNING)[0].reason == DISCONNECT_REASON_PEER


def test_the_failed_pending_calls_carry_the_disconnect_reason():
    # The reason rides the RelayUnavailableError too, so "relay unavailable" in the UI and in an outbox
    # row names the same cause as the log line.
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        call_task = asyncio.create_task(gateway.relay_call("TUBC", "list_vendors", timeout=1))
        while not ws.sent:
            await asyncio.sleep(0)
        while not gateway.register_ping_miss():
            pass
        gateway.unregister(ws)

        with pytest.raises(RelayUnavailableError) as exc_info:
            await call_task
        assert "reaped after" in exc_info.value.message

    asyncio.run(run())


def test_unregistering_a_refused_socket_leaves_the_incumbent_alone(caplog):
    # The 4409 path: a second relay is refused at try_register and torn down, sharing this gateway with
    # the live one. unregister compares identity, so that teardown must not log the incumbent away,
    # clear its company/install/build, or consume the reason stamped for its eventual disconnect.
    gateway = RelayGateway()
    live_ws = FakeWebSocket()
    install_id = uuid.uuid4()
    gateway.try_register("TUBC", live_ws, install_id)
    gateway.note_hello("relay-v0.1.0-build.30", ["list_vendors"])
    while not gateway.register_ping_miss():
        pass

    refused_ws = FakeWebSocket()
    assert gateway.try_register("TUBC", refused_ws, uuid.uuid4()) is False
    caplog.clear()  # the refusal logs a line of its own; what is under test is the teardown after it
    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(refused_ws)

    assert _records(caplog, logging.WARNING) == []  # nothing was disconnected
    assert gateway.connected is True
    assert gateway.company == "TUBC"
    assert gateway.install_id == install_id
    assert gateway.build == "relay-v0.1.0-build.30"

    # ...and the incumbent's own disconnect still reports the reap it had already earned.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        gateway.unregister(live_ws)
    assert _records(caplog, logging.WARNING)[0].reason.startswith("reaped after")


def test_a_refused_connection_is_logged_against_the_incumbent(caplog):
    # A refused reconnect is what a zombie incumbent looks like from outside - the real relay dialling
    # back in every few seconds while a dead socket holds the slot - and it used to be silent.
    gateway = RelayGateway()
    gateway.try_register("TUBC", FakeWebSocket(), uuid.uuid4())

    with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
        assert gateway.try_register("TUBC", FakeWebSocket()) is False

    record = _records(caplog, logging.WARNING)[0]
    assert "slot already held" in record.getMessage()
    assert record.held_seconds >= 0


def test_close_for_shutdown_does_not_log_the_relay_as_failed(caplog):
    # A deploy closed the socket on purpose and the relay is already reconnecting (close code 1012).
    # Logging that at WARNING beside genuine drops would train everyone to ignore the one that matters.
    async def run():
        gateway = RelayGateway()
        ws = FakeWebSocket()
        gateway.try_register("TUBC", ws)
        with caplog.at_level(logging.INFO, logger="app.services.relay_gateway"):
            await gateway.close_for_shutdown()

        assert _records(caplog, logging.WARNING) == []
        infos = _records(caplog, logging.INFO)
        assert len(infos) == 1
        assert infos[0].reason == DISCONNECT_REASON_SHUTDOWN

    asyncio.run(run())
