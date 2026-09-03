"""relay_call_with_meta: the `cost` and `server` blocks every reply now carries, and the server_busy
refusal that adaptive pacing turns into a pause.

Same shape as test_relay_gateway.py - a fake socket, a responder task that resolves the correlated
reply, and asyncio.run per test, because the codebase has no async test infra and this slice is not
where that gets decided."""

import asyncio

import pytest

from app.errors import RelayBusyError, RelayCallError, RelayOpUnsupportedError, RelayUnavailableError
from app.models.enums import RelayEventKind
from app.services import relay_gateway as relay_gateway_module
from app.services.relay_gateway import RelayGateway


@pytest.fixture(autouse=True)
def recorded_events(monkeypatch):
    """Capture the gateway's relay events rather than writing them - the real writer opens a database
    connection from a worker thread, which these tests have no use for."""
    captured: list[dict] = []
    monkeypatch.setattr(
        relay_gateway_module.relay_events, "record", lambda kind, **fields: captured.append({"kind": kind, **fields})
    )
    return captured


class FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


SAMPLE = {
    "sql_cpu_pct": 42.0,
    "other_cpu_pct": 8.0,
    "runnable_tasks": 1,
    "sampled_at": "2026-09-03T17:36:40",
    "source": "ring_buffer",
}
COST = {"cpu_ms": 812.0, "logical_reads": 91234, "elapsed_ms": 1503.0}


def _connect(gateway, websocket, companies=("TUBC",)):
    assert gateway.try_register(websocket) is True
    gateway.note_hello(None, None, list(companies))


def _run(reply, *, op="sync_pos", company="TUBC"):
    """Dispatch one call and resolve it with `reply`. Returns whatever relay_call_with_meta returns."""
    gateway = RelayGateway()
    ws = FakeWebSocket()

    async def go():
        _connect(gateway, ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], **reply})

        task = asyncio.create_task(responder())
        try:
            return await gateway.relay_call_with_meta(company, op, {}, 1)
        finally:
            await task

    return gateway, asyncio.run(go())


def test_meta_carries_the_cost_and_server_blocks():
    gateway, (result, meta) = _run({"ok": True, "result": {"pos": []}, "cost": COST, "server": SAMPLE})

    assert result == {"pos": []}
    assert meta["cost"] == COST
    assert meta["server"] == SAMPLE


def test_a_relay_that_reports_neither_yields_a_meta_of_nones():
    """An older relay build sends no accounting at all. Pacing then runs on wall-clock elapsed time,
    which still works - so this must be a plain answer, not an error."""
    gateway, (result, meta) = _run({"ok": True, "result": {"pos": []}})

    assert result == {"pos": []}
    assert meta == {"cost": None, "server": None}


def test_a_block_that_is_not_an_object_is_ignored_rather_than_believed():
    gateway, (_, meta) = _run({"ok": True, "result": None, "cost": "nope", "server": 7})

    assert meta == {"cost": None, "server": None}


def test_the_newest_server_sample_is_kept_on_the_gateway():
    gateway, _ = _run({"ok": True, "result": None, "server": SAMPLE})

    assert gateway.last_server_sample == SAMPLE


def test_the_sample_rides_whichever_op_happens_to_carry_it():
    """ "Whatever op it rode on" is the point: a list_jobs reply tells us as much about the server as a
    dedicated probe would."""
    gateway, _ = _run({"ok": True, "result": None, "server": SAMPLE}, op="list_jobs")

    assert gateway.last_server_sample == SAMPLE


def test_no_sample_before_one_arrives():
    gateway = RelayGateway()
    assert gateway.last_server_sample is None


def test_a_disconnect_drops_the_sample():
    """A reading taken before the socket died says nothing about the server now, and pacing on a stale
    number is worse than pacing on none."""
    gateway, _ = _run({"ok": True, "result": None, "server": SAMPLE})
    assert gateway.last_server_sample == SAMPLE

    gateway.unregister(gateway._socket)

    assert gateway.last_server_sample is None


def test_relay_call_still_returns_the_bare_result():
    """The signature every existing caller uses is unchanged - meta is opt-in."""
    gateway = RelayGateway()
    ws = FakeWebSocket()

    async def go():
        _connect(gateway, ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": {"pos": []}, "cost": COST})

        task = asyncio.create_task(responder())
        result = await gateway.relay_call("TUBC", "sync_pos", {}, 1)
        await task
        return result

    assert asyncio.run(go()) == {"pos": []}


# --- server_busy -------------------------------------------------------------------------------------


def _busy_reply(context=None, **extra):
    error = {"error": "server_busy", "message": "GP is busy"}
    if context is not None:
        error["context"] = context
    return {"ok": False, "error": error, **extra}


def test_a_server_busy_refusal_becomes_a_relay_busy_error():
    with pytest.raises(RelayBusyError) as e:
        _run(_busy_reply({"sql_cpu_pct": 91.0, "ceiling_pct": 70.0, "retry_after_seconds": 45.0}))

    assert e.value.sql_cpu_pct == 91.0
    assert e.value.ceiling_pct == 70.0
    assert e.value.retry_after_seconds == 45.0
    assert e.value.code == "RELAY_BUSY"
    # Still a RelayCallError, so anything catching the broad type keeps working.
    assert isinstance(e.value, RelayCallError)


def test_a_busy_refusal_with_no_context_still_raises_cleanly():
    """Every field comes off the wire, so a relay that omits one must not break the pause."""
    with pytest.raises(RelayBusyError) as e:
        _run(_busy_reply())

    assert e.value.sql_cpu_pct is None
    assert e.value.retry_after_seconds is None


def test_the_sample_on_a_refusal_is_still_recorded():
    """The reply whose sample matters most is the one saying the server is too busy to serve us."""
    gateway = RelayGateway()
    ws = FakeWebSocket()
    busy_sample = {**SAMPLE, "sql_cpu_pct": 91.0}

    async def go():
        _connect(gateway, ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], **_busy_reply(server=busy_sample)})

        task = asyncio.create_task(responder())
        try:
            with pytest.raises(RelayBusyError):
                await gateway.relay_call_with_meta("TUBC", "sync_pos", {}, 1)
        finally:
            await task

    asyncio.run(go())
    assert gateway.last_server_sample == busy_sample


def test_an_ordinary_refusal_is_still_a_plain_call_error():
    with pytest.raises(RelayCallError) as e:
        _run({"ok": False, "error": {"error": "eConnect", "message": "bad account index"}})

    assert not isinstance(e.value, RelayBusyError)


def test_an_unknown_op_still_maps_to_the_update_the_relay_error():
    with pytest.raises(RelayOpUnsupportedError):
        _run({"ok": False, "error": {"error": "unknown_op"}})


def test_a_fresh_connection_starts_with_no_sample(recorded_events):
    """Claiming the slot resets the per-connection state, this included, so a new relay never inherits
    the load reading of the one it replaced."""
    gateway, _ = _run({"ok": True, "result": None, "server": SAMPLE})
    gateway.unregister(gateway._socket)

    gateway.try_register(FakeWebSocket())

    assert gateway.last_server_sample is None
    assert RelayEventKind.DISCONNECTED in [e["kind"] for e in recorded_events]


# --- the background flag ------------------------------------------------------------------------------


def _sent_frame(**call_kwargs):
    """Dispatch one call and return the job frame that went out on the wire."""
    gateway = RelayGateway()
    ws = FakeWebSocket()

    async def go():
        _connect(gateway, ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": None})

        task = asyncio.create_task(responder())
        await gateway.relay_call_with_meta("TUBC", "sync_pos", {}, 1, **call_kwargs)
        await task

    asyncio.run(go())
    return ws.sent[0]


def test_a_background_call_says_so_on_the_wire():
    """The relay's busy gate keys on this flag and NOT on the op name, so it has to be on the frame."""
    assert _sent_frame(background=True)["background"] is True


def test_a_user_facing_call_is_not_marked_background():
    """A resolver, an outbox write, the admin button: served, never refused. The default is what makes
    forgetting the flag fail safe - towards being served rather than throttled."""
    assert _sent_frame()["background"] is False


def test_the_frame_still_carries_everything_it_did_before():
    frame = _sent_frame(background=True)
    assert frame["op"] == "sync_pos"
    assert frame["company"] == "TUBC"
    assert frame["payload"] == {}
    assert "id" in frame


def test_relay_call_passes_the_flag_through_too():
    gateway = RelayGateway()
    ws = FakeWebSocket()

    async def go():
        _connect(gateway, ws)

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": None})

        task = asyncio.create_task(responder())
        await gateway.relay_call("TUBC", "list_jobs", {}, 1, background=True)
        await task

    asyncio.run(go())
    assert ws.sent[0]["background"] is True


# --- the company-less probe ---------------------------------------------------------------------------


def test_an_empty_company_skips_the_channel_pin():
    """server_load is exempt from the relay's channel pin, so the load probe can run with no company in
    hand - which is the whole point: a paused policy has to be able to recover before a hello lands."""
    gateway = RelayGateway()
    ws = FakeWebSocket()

    async def go():
        assert gateway.try_register(ws) is True  # registered, but NO hello: companies is empty

        async def responder():
            while not ws.sent:
                await asyncio.sleep(0)
            gateway.resolve({"id": ws.sent[0]["id"], "ok": True, "result": None, "server": SAMPLE})

        task = asyncio.create_task(responder())
        result = await gateway.relay_call_with_meta("", "server_load", {}, 1)
        await task
        return result

    _, meta = asyncio.run(go())
    assert meta["server"] == SAMPLE
    assert ws.sent[0]["company"] == ""


def test_a_named_company_is_still_checked_against_what_the_relay_serves():
    """The exemption is for the empty company only. Everything else still has to be servable."""
    gateway = RelayGateway()

    async def go():
        _connect(gateway, FakeWebSocket(), ["TUBC"])
        with pytest.raises(RelayUnavailableError):
            await gateway.relay_call_with_meta("UCSH", "sync_pos", {}, 1)

    asyncio.run(go())


def test_an_empty_company_still_needs_a_socket():
    async def go():
        gateway = RelayGateway()
        with pytest.raises(RelayUnavailableError):
            await gateway.relay_call_with_meta("", "server_load", {}, 1)

    asyncio.run(go())
