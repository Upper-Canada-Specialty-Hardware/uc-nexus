"""Shutdown lets a GP write already on the wire finish before the relay socket closes (#1292).

uvicorn closes every open connection, the relay's websocket included, before the app's lifespan
shutdown runs, so the drain runs from serve.py's server ahead of that. No database and no relay: the
drain in flight, the claim and the socket are all fakes."""

import asyncio

import pytest
import uvicorn

import main
import serve
from app.services import gp_outbox_worker


@pytest.fixture(autouse=True)
def _reset_worker_state():
    """The worker's shutdown state is module-level; leave none behind for a later test's lifespan."""
    yield
    gp_outbox_worker._stopping = False
    gp_outbox_worker._idle = None
    gp_outbox_worker._wake_event = None


def _arm_worker():
    """Put the worker in the state run_forever leaves it in, with a drain under way."""
    gp_outbox_worker._stopping = False
    gp_outbox_worker._wake_event = asyncio.Event()
    gp_outbox_worker._idle = asyncio.Event()  # clear: a row is being drained


def test_the_socket_closes_only_after_the_drain_in_flight_finishes(monkeypatch):
    order: list[str] = []

    async def _close():
        order.append("socket closed")

    monkeypatch.setattr(main.relay_gateway, "close_for_shutdown", _close)

    async def _scenario():
        _arm_worker()

        async def _drain_in_flight():
            await asyncio.sleep(0.2)  # the relay answers
            order.append("drain finished")
            gp_outbox_worker._idle.set()

        drain = asyncio.create_task(_drain_in_flight())
        await main.drain_before_shutdown()
        await drain
        assert gp_outbox_worker._stopping is True  # nothing new is claimed

    asyncio.run(_scenario())
    assert order == ["drain finished", "socket closed"]


def test_the_wait_is_bounded_and_the_socket_still_closes(monkeypatch):
    order: list[str] = []

    async def _close():
        order.append("socket closed")

    monkeypatch.setattr(main.relay_gateway, "close_for_shutdown", _close)
    monkeypatch.setattr(main, "OUTBOX_DRAIN_SECONDS", 0.1)

    async def _scenario():
        _arm_worker()  # a drain that never finishes
        await main.drain_before_shutdown()

    asyncio.run(_scenario())
    assert order == ["socket closed"]


def test_a_stopping_worker_claims_nothing(monkeypatch):
    claims: list[str] = []
    monkeypatch.setattr(type(gp_outbox_worker.relay_gateway), "connected", property(lambda self: True))
    monkeypatch.setattr(type(gp_outbox_worker.relay_gateway), "companies", property(lambda self: ["TUBC"]))
    monkeypatch.setattr(gp_outbox_worker, "_claim", lambda company: claims.append(company))
    monkeypatch.setattr(gp_outbox_worker, "_recover_in_flight", lambda: None)
    monkeypatch.setattr(gp_outbox_worker, "POLL_SECONDS", 0.05)

    async def _scenario():
        task = asyncio.create_task(gp_outbox_worker.run_forever())
        await asyncio.sleep(0.15)
        before = len(claims)
        assert before > 0  # it was claiming
        gp_outbox_worker.request_stop()
        await asyncio.sleep(0.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return before

    before = asyncio.run(_scenario())
    assert len(claims) <= before + 1  # at most the claim already under way when stop landed
    assert asyncio.run(gp_outbox_worker.wait_idle(0.1)) is True


def test_the_server_drains_before_uvicorn_closes_connections(monkeypatch):
    order: list[str] = []

    async def _drain():
        order.append("drained")

    async def _uvicorn_shutdown(self, sockets=None):
        order.append("connections closed")

    monkeypatch.setattr(main, "drain_before_shutdown", _drain)
    monkeypatch.setattr(uvicorn.Server, "shutdown", _uvicorn_shutdown)

    server = serve.DrainingServer(uvicorn.Config("main:app"))
    asyncio.run(server.shutdown())
    assert order == ["drained", "connections closed"]

    # A second signal means stop now: no drain.
    order.clear()
    server.force_exit = True
    asyncio.run(server.shutdown())
    assert order == ["connections closed"]


def test_the_platform_waits_longer_than_the_server_and_the_server_longer_than_the_drain():
    import tomllib
    from pathlib import Path

    railway = tomllib.loads((Path(__file__).resolve().parents[1] / "railway.toml").read_text())
    assert railway["deploy"]["drainingSeconds"] > serve.GRACEFUL_SHUTDOWN_SECONDS > main.OUTBOX_DRAIN_SECONDS
