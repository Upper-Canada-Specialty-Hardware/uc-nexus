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

from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import main  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.relay_install import RelayInstall  # noqa: E402
from app.repositories import relay_repository  # noqa: E402
from app.services import relay_adopt  # noqa: E402
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
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}) as ws:
                _wait_until(lambda: gateway.connected)
                assert gateway.connected is True
                assert gateway.company == "TUBC"
                # Close client-side and let the route's finally unregister BEFORE leaving the context, so
                # the app task has already returned when the test client tears its portal down. Now that
                # the route also runs a background heartbeat task, its disconnect teardown yields once,
                # which otherwise races the portal's cancel-on-exit and surfaces a spurious CancelledError.
                ws.close()
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
                # Close and let the route unregister before the context tears the portal down (see the
                # handshake test) so a clean teardown doesn't race the heartbeat into a spurious cancel.
                ws.close()
                _wait_until(lambda: not gateway.connected)
            assert gateway.connected is False
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


def test_relay_link_serves_a_relay_call_concurrently_with_heartbeat_pings(monkeypatch):
    # issue #304 (follow-up to #277/#303): the heartbeat added a SECOND concurrent sender on the one
    # /relay-link socket - _relay_heartbeat_loop sends {"type": "ping"} while relay_call() sends its
    # {id, op, company, payload} job from a separate task. No test drove the two senders on one socket.
    # Run a real relay_call() on the server's event loop while pings are in flight and assert both frames
    # reach the relay intact (complete JSON, not interleaved bytes) and the call still correlates to its
    # reply.
    #
    # This mounts the real _serve_relay_link on a throwaway app rather than going through the DB-authed
    # /relay-link route: the concurrent-sender behaviour is identical either way (same event loop, same
    # Starlette WebSocket send path), and skipping the enroll keeps this runnable without a DATABASE_URL,
    # unlike the route tests above.
    monkeypatch.setattr(main, "HEARTBEAT_INTERVAL_SECONDS", 0.05)

    link_app = FastAPI()

    @link_app.websocket("/relay-link")
    async def _link(websocket: WebSocket):  # mirrors main.relay_link's teardown, minus the DB auth
        await websocket.accept()
        gateway.try_register("TUBC", websocket)
        try:
            await main._serve_relay_link(websocket)
        except WebSocketDisconnect:
            pass
        except asyncio.CancelledError:
            pass
        finally:
            gateway.unregister(websocket)

    assert gateway.connected is False
    with TestClient(link_app) as client:
        with client.websocket_connect("/relay-link") as ws:
            _wait_until(lambda: gateway.connected)

            # Arm the reaper with one pong so it's live for the rest of the exchange, and prove a ping is
            # already flowing before the job goes out.
            assert ws.receive_json() == {"type": "ping"}
            ws.send_json({"type": "pong"})

            # Run relay_call() on the server's event loop (the loop the heartbeat runs on) so its job send
            # races the pings, exactly as in production. start_task_soon hands back a concurrent Future.
            async def _do_call():
                return await gateway.relay_call("TUBC", "list_vendors", timeout=5)

            call_future = ws.portal.start_task_soon(_do_call)

            # Service frames until the job has gone out AND at least one ping has followed it - i.e. both
            # senders were on the wire together. receive_json raises if a frame is not complete JSON, so
            # each pass also asserts the two senders did not interleave into one corrupt frame.
            job_frame = None
            pings_after_job = 0
            deadline = time.monotonic() + 5.0
            while job_frame is None or pings_after_job < 1:
                if time.monotonic() > deadline:
                    if call_future.done():
                        call_future.result()  # re-raise a server-side relay_call failure with its traceback
                    raise AssertionError(f"timed out; job_frame={job_frame} pings_after_job={pings_after_job}")
                msg = ws.receive_json()
                if msg.get("type") == "ping":
                    ws.send_json({"type": "pong"})
                    if job_frame is not None:
                        pings_after_job += 1
                else:
                    assert job_frame is None, "relay_call sent more than one job frame"
                    job_frame = msg

            # The job frame arrived whole and correlatable, not shredded by the interleaved ping.
            assert job_frame["op"] == "list_vendors"
            assert job_frame["company"] == "TUBC"
            assert job_frame["payload"] == {}
            assert isinstance(job_frame["id"], str) and job_frame["id"]

            # Answer the job: the read loop must still route this reply to relay_call's pending future
            # despite the pings threaded through, and the call resolves to the reply's result.
            ws.send_json({"id": job_frame["id"], "ok": True, "result": {"vendors": []}})
            assert call_future.result(timeout=5) == {"vendors": []}

            ws.close()
            _wait_until(lambda: not gateway.connected)
        assert gateway.connected is False


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


def _read_install(install_id):
    with SessionLocal() as session:
        return session.get(RelayInstall, install_id)


def test_relay_link_adopts_an_unknown_secret_while_a_window_is_armed(_migrate_database):
    # #353 PR B: the live recovery path. The install's stored secret does NOT match what the relay is
    # dialling with; with a window armed, that connection is accepted and the presented secret is bound.
    relay_adopt.disarm()
    install_id = _enroll_committed("WS-ADOPT", "TUBC", "the-secret-the-backend-has")
    try:
        relay_adopt.arm(install_id, "WS-ADOPT", "user_admin")
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer what-the-relay-is-actually-presenting"}
            with client.websocket_connect("/relay-link", headers=headers) as ws:
                # An adopted socket must prove it speaks the relay protocol before it is trusted.
                ws.send_json({"type": "hello", "build": "relay-v0.1.0-build.42", "ops": ["list_vendors"]})
                _wait_until(lambda: gateway.connected)
                assert gateway.connected is True
                assert gateway.company == "TUBC"
                _wait_until(lambda: gateway.build == "relay-v0.1.0-build.42")
                assert gateway.build == "relay-v0.1.0-build.42"
                ws.close()
                _wait_until(lambda: not gateway.connected)

        # The adoption is durable on the row, and the window is spent.
        row = _read_install(install_id)
        assert row.adopted_at is not None
        assert row.adopted_by == "user_admin"
        assert relay_adopt.peek() is None

        # A second unknown secret is refused now that the flag is consumed.
        with TestClient(app) as client:
            try:
                with client.websocket_connect("/relay-link", headers={"Authorization": "Bearer another-one"}):
                    pass
            except WebSocketDisconnect:
                pass
        assert gateway.connected is False
    finally:
        relay_adopt.disarm()
        _delete_install(install_id)


def test_relay_link_still_rejects_an_unknown_secret_with_no_window_armed(_migrate_database):
    # The gate only opens when an admin opens it: no window means the pre-adopt behaviour, verbatim.
    relay_adopt.disarm()
    install_id = _enroll_committed("WS-NO-ADOPT", "TUBC", "stored-secret")
    try:
        with TestClient(app) as client:
            try:
                with client.websocket_connect("/relay-link", headers={"Authorization": "Bearer drifted"}):
                    pass
            except WebSocketDisconnect:
                pass
        assert gateway.connected is False
        row = _read_install(install_id)
        assert row.adopted_at is None
    finally:
        _delete_install(install_id)


def test_serve_relay_link_closes_an_adopted_socket_that_does_not_say_hello():
    # The hello gate: an adopted connection that is not a relay gets 4403 and never reaches the read loop.
    async def run():
        ws = _FakeRelaySocket([{"id": "1", "ok": True, "result": {}}])
        await main._serve_relay_link(ws, require_hello=True)
        assert ws.closed_code == 4403

    asyncio.run(run())


def test_serve_relay_link_accepts_an_adopted_socket_that_says_hello():
    async def run():
        ws = _FakeRelaySocket(
            [
                {"type": "hello", "build": "relay-v0.1.0-build.42", "ops": ["list_vendors"]},
                WebSocketDisconnect(),
            ]
        )
        gateway.try_register("TEST", ws)
        try:
            with pytest.raises(WebSocketDisconnect):
                await main._serve_relay_link(ws, require_hello=True)
            assert gateway.build == "relay-v0.1.0-build.42"
            assert ws.closed_code is None
        finally:
            gateway.unregister(ws)

    asyncio.run(run())


def test_read_loop_records_the_relay_hello_frame(monkeypatch):
    # Issue #315: the relay's first frame advertises its build + op-set; the read loop must record it on
    # the gateway (not treat it as a job reply) so relayStatus reports the build and relay_call can gate ops.
    async def run():
        ws = _FakeRelaySocket(
            [
                {"type": "hello", "build": "relay-v0.1.0-build.30", "ops": ["list_vendors", "list_tax_details"]},
                WebSocketDisconnect(),
            ]
        )
        gateway.try_register("TEST", ws)
        try:
            with pytest.raises(WebSocketDisconnect):
                await main._relay_read_loop(ws)
            assert gateway.build == "relay-v0.1.0-build.30"
        finally:
            gateway.unregister(ws)
        assert gateway.build is None  # cleared on unregister

    asyncio.run(run())


# --- deleting an install while a relay is live (#366) --------------------------------------------------


class _FakeInfo:
    """A resolver `info` with no real request. require_admin is patched out per test - what is under
    test here is the connected-install guard, not the auth gate (that lives in
    test_resolver_auth_gates)."""

    context = {"request": None}


def _as_admin(monkeypatch):
    from app.schemas import relay as relay_module

    monkeypatch.setattr(relay_module, "require_admin", lambda info: {"user_id": "user_admin", "roles": ["Admin"]})


def test_delete_refuses_the_install_holding_the_live_connection(_migrate_database, monkeypatch):
    """Revoking the secret under a running relay would take GP down mid-write, so the resolver refuses
    it. This drives the real route because the id it compares against is set by the route - reading
    install.id in the same pre-commit block as install.company, per the DetachedInstanceError rule."""
    from app.errors import ConflictError
    from app.schemas.relay import RelayMutations

    _as_admin(monkeypatch)
    secret = "relay-link-delete-guard-secret"
    install_id = _enroll_committed("WS-DELETE-GUARD", "TUBC", secret)
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}) as ws:
                _wait_until(lambda: gateway.connected)
                assert gateway.install_id == install_id  # the route recorded WHICH row authenticated

                with pytest.raises(ConflictError):
                    RelayMutations().delete_relay_install(_FakeInfo(), str(install_id))

                ws.close()
                _wait_until(lambda: not gateway.connected)
        # Refused, not half-done: the row and its credential are still there.
        with SessionLocal() as session:
            assert session.get(RelayInstall, install_id) is not None
    finally:
        _delete_install(install_id)


def test_delete_allows_a_different_disconnected_install_while_one_is_live(_migrate_database, monkeypatch):
    # Retiring a workstation is the normal case and must not be blocked by an unrelated relay being up.
    from app.schemas.relay import RelayMutations

    _as_admin(monkeypatch)
    live_secret = "relay-link-delete-live-secret"
    live_id = _enroll_committed("WS-DELETE-LIVE", "TUBC", live_secret)
    other_id = _enroll_committed("WS-DELETE-OTHER", "TUBC", "relay-link-delete-other-secret")
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {live_secret}"}) as ws:
                _wait_until(lambda: gateway.connected)

                assert RelayMutations().delete_relay_install(_FakeInfo(), str(other_id)) is True

                assert gateway.connected is True  # the live relay is undisturbed
                assert gateway.install_id == live_id
                ws.close()
                _wait_until(lambda: not gateway.connected)
        with SessionLocal() as session:
            assert session.get(RelayInstall, other_id) is None
    finally:
        _delete_install(live_id)
        _delete_install(other_id)
