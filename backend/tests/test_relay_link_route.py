"""Regression coverage for the /relay-link WebSocket handshake - the relay's outbound channel connect
path, which the PR that introduced it did not exercise in CI ("channel connect path not exercised").

The route authenticated the relay's secret inside a `with SessionLocal()` block that ran
session.commit() and then closed, which expired + detached the RelayInstall. Reading install.company
afterwards (right after websocket.accept()) raised DetachedInstanceError, tearing down every accepted
relay socket, so no relay ever registered and relayStatus stayed false. These tests drive the real
route so that failure mode can't come back unnoticed.
"""

import asyncio
import os
import time

import pytest
from cryptography.fernet import Fernet

# The crypto layer reads RELAY_SECRET_ENC_KEY at call time; provide one before enroll/authenticate.
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import main  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.relay_install import RelayInstall  # noqa: E402
from app.repositories import relay_repository  # noqa: E402
from app.services.relay_gateway import gateway  # noqa: E402
from main import app  # noqa: E402


def _enroll_committed(label: str, company: str, secret: str) -> str:
    """Enroll an install and COMMIT it: the route opens its own SessionLocal(), so it only sees
    committed rows, not this test's transaction. Returns the install id for cleanup."""
    with SessionLocal() as session:
        _, token = relay_repository.provision_install(session, label=label, company=company)
        enrolled = relay_repository.enroll_install(session, token, hostname=label, secret=secret)
        install_id = enrolled.id
        session.commit()
    return install_id


def _delete_install(install_id: str) -> None:
    with SessionLocal() as session:
        obj = session.get(RelayInstall, install_id)
        if obj is not None:
            session.delete(obj)
            session.commit()


def _wait_until(predicate, timeout: float = 3.0) -> None:
    # try_register runs just after accept(), concurrently with the test thread - poll rather than race.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(0.02)


def test_relay_link_handshake_registers_the_company(_migrate_database):
    secret = "relay-link-regression-secret"
    install_id = _enroll_committed("WS-REGRESSION", "TUBC", secret)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}):
                _wait_until(lambda: gateway.connected)
                assert gateway.connected is True
                assert gateway.company == "TUBC"
            # Leaving the context closes the socket; the route's finally unregisters it.
            _wait_until(lambda: not gateway.connected)
            assert gateway.connected is False
    finally:
        _delete_install(install_id)


def test_relay_link_rejects_an_unknown_secret(_migrate_database):
    # An unenrolled secret closes with 4401 before accept(), which TestClient surfaces as a disconnect.
    with TestClient(app) as client:
        try:
            with client.websocket_connect("/relay-link", headers={"Authorization": "Bearer not-enrolled"}):
                pass
        except WebSocketDisconnect:
            pass
    assert gateway.connected is False


def test_relay_link_heartbeat_keeps_a_responsive_relay_connected(_migrate_database, monkeypatch):
    # issue #277: a relay that answers the data-message pings must stay registered - the heartbeat only
    # reaps a relay that has gone silent, never one that keeps ponging.
    monkeypatch.setattr(main, "HEARTBEAT_INTERVAL_SECONDS", 0.1)
    secret = "relay-link-heartbeat-alive"
    install_id = _enroll_committed("WS-HB-ALIVE", "TUBC", secret)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}) as ws:
                _wait_until(lambda: gateway.connected)
                for _ in range(3):
                    assert ws.receive_json() == {"type": "ping"}
                    ws.send_json({"type": "pong"})
                assert gateway.connected is True
    finally:
        _delete_install(install_id)


def test_relay_link_heartbeat_reaps_a_relay_that_stops_answering(_migrate_database, monkeypatch):
    # issue #277: answer the first ping to arm the reaper, then go silent. The route must close the
    # socket so the gateway unregisters and relayStatus flips, instead of reading connected for ~an hour.
    monkeypatch.setattr(main, "HEARTBEAT_INTERVAL_SECONDS", 0.05)
    secret = "relay-link-heartbeat-drop"
    install_id = _enroll_committed("WS-HB-DROP", "TUBC", secret)
    try:
        with TestClient(app) as client:
            try:
                with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}) as ws:
                    _wait_until(lambda: gateway.connected)
                    assert ws.receive_json() == {"type": "ping"}
                    ws.send_json({"type": "pong"})  # arm, then stop answering
                    _wait_until(lambda: not gateway.connected, timeout=5.0)
            except WebSocketDisconnect:
                # The server-side close (heartbeat reap) surfaces here as the context exits; expected.
                pass
        assert gateway.connected is False
    finally:
        _delete_install(install_id)


class _FakeRelaySocket:
    """A minimal WebSocket stand-in for driving _serve_relay_link directly (no DB, no TestClient thread).
    receive_json yields the queued messages/exceptions in order, then blocks as an idle relay would."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self.closed_code: int | None = None

    async def receive_json(self):
        if self._incoming:
            item = self._incoming.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        await asyncio.Event().wait()  # nothing more to read: block until the heartbeat/cancel ends us

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code


def test_serve_relay_link_reraises_a_reader_disconnect():
    # A genuine client disconnect must surface as WebSocketDisconnect so the route's except handles it.
    async def run():
        ws = _FakeRelaySocket([WebSocketDisconnect()])
        gateway.try_register("TEST", ws)
        try:
            with pytest.raises(WebSocketDisconnect):
                await main._serve_relay_link(ws)
        finally:
            gateway.unregister(ws)

    asyncio.run(run())


def test_serve_relay_link_swallows_a_cancelled_reader():
    # Regression for the CI failure on the responsive-relay test: when the read task ends by cancellation
    # (a clean teardown races the active heartbeat), _serve_relay_link must return normally. Re-raising
    # there marked the whole route task cancelled, which TestClient surfaced as a CancelledError.
    async def run():
        ws = _FakeRelaySocket([asyncio.CancelledError()])
        gateway.try_register("TEST", ws)
        try:
            await main._serve_relay_link(ws)  # must not raise
        finally:
            gateway.unregister(ws)

    asyncio.run(run())
