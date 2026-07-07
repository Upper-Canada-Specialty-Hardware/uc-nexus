"""Relay gateway: the /relay-link WebSocket endpoint + the internal relay_call broker.

Single-workstation model: one relay dials in at a time. The backend holds that connection
process-wide (module-level `gateway` singleton) and multiplexes concurrent relay_call()
invocations over it by correlating replies to the job id the caller generated.

Wire protocol (pinned, must match the relay-side channel exactly):
  job out  -> {"id": <str>, "op": <str>, "company": <str>, "payload": <dict>}
  reply in <- {"id": <str>, "ok": true, "result": <any>} | {"id": <str>, "ok": false, "error": <str>}
  keepalive in <- {"type": "ping"} sent by the relay every 20s while idle; the gateway answers
  {"type": "pong"} and treats any inbound frame as liveness. A connection that goes quiet for
  longer than _DEAD_AFTER is presumed dead and dropped even if the socket hasn't errored yet.

Auth: the relay sends its enrolled Bearer secret as an `Authorization: Bearer <secret>` header
on the WebSocket upgrade request. Verified against relay_repository's enrolled-install lookup
before the handshake is accepted.
"""

import asyncio
import logging
import secrets
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.errors import AppError, NotFoundError
from app.repositories import relay_repository

logger = logging.getLogger(__name__)

_KEEPALIVE_INTERVAL = 20  # seconds; the relay is expected to send a ping at least this often
_DEAD_AFTER = 50  # seconds of silence (no ping, no reply) before a connection is presumed dead
_WATCHDOG_TICK = 5  # seconds between liveness checks
_DEFAULT_CALL_TIMEOUT = 30  # seconds to wait for a correlated reply


class RelayError(AppError):
    def __init__(self, message: str, code: str):
        super().__init__(message, code)


class RelayNotConnectedError(RelayError):
    def __init__(self):
        super().__init__("no relay connected", "RELAY_NOT_CONNECTED")


class RelayTimeoutError(RelayError):
    def __init__(self, op: str):
        super().__init__(f"relay call '{op}' timed out waiting for a reply", "RELAY_TIMEOUT")


class RelayCallError(RelayError):
    """The relay answered the job with {ok: false, error}."""

    def __init__(self, message: str):
        super().__init__(message, "RELAY_CALL_FAILED")


def _bearer_token(websocket: WebSocket) -> str | None:
    header = websocket.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


class _Connection:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.last_seen = time.monotonic()
        self.pending: dict[str, asyncio.Future] = {}
        self.alive = True


class RelayGateway:
    """Tracks the single live relay connection and brokers relay_call over it."""

    def __init__(self):
        self._conn: _Connection | None = None

    def is_connected(self) -> bool:
        return self._conn is not None and self._conn.alive

    async def accept(self, websocket: WebSocket) -> None:
        """Entry point for the /relay-link route: authenticate, then own the connection
        until it disconnects, times out on keepalive, or is superseded."""
        secret = _bearer_token(websocket)
        if not secret or not self._authenticate(secret):
            await websocket.close(code=4401)
            return

        await websocket.accept()
        conn = _Connection(websocket)
        previous, self._conn = self._conn, conn
        if previous is not None:
            await self._retire(previous, RelayNotConnectedError())

        watchdog = asyncio.create_task(self._watchdog(conn))
        try:
            await self._receive_loop(conn)
        finally:
            watchdog.cancel()
            if self._conn is conn:
                self._conn = None
            await self._retire(conn, RelayNotConnectedError())

    def _authenticate(self, secret: str) -> bool:
        with SessionLocal() as session:
            try:
                expected = relay_repository.get_credential(session)
            except NotFoundError:
                return False
            if not secrets.compare_digest(secret, expected):
                return False
            session.commit()  # persist the last_seen_at bump only for a real, successful auth
            return True

    async def _receive_loop(self, conn: _Connection) -> None:
        try:
            while True:
                message = await conn.websocket.receive_json()
                conn.last_seen = time.monotonic()

                if message.get("type") == "ping":
                    await conn.websocket.send_json({"type": "pong"})
                    continue

                job_id = message.get("id")
                future = conn.pending.pop(job_id, None) if job_id else None
                if future is None or future.done():
                    continue
                if message.get("ok"):
                    future.set_result(message.get("result"))
                else:
                    future.set_exception(RelayCallError(message.get("error") or "relay call failed"))
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("relay connection errored; dropping it")
            return

    async def _watchdog(self, conn: _Connection) -> None:
        try:
            while True:
                await asyncio.sleep(_WATCHDOG_TICK)
                if time.monotonic() - conn.last_seen > _DEAD_AFTER:
                    logger.warning("relay connection missed keepalive; closing it")
                    await conn.websocket.close()
                    return
        except asyncio.CancelledError:
            return

    async def _retire(self, conn: _Connection, error: Exception) -> None:
        conn.alive = False
        for future in conn.pending.values():
            if not future.done():
                future.set_exception(error)
        conn.pending.clear()

    async def relay_call(
        self, company: str, op: str, payload: dict[str, Any], timeout: float = _DEFAULT_CALL_TIMEOUT
    ) -> Any:
        """Send a job to the connected relay and await its correlated reply.

        Raises RelayNotConnectedError if no relay is connected (or the send fails),
        RelayTimeoutError if no reply arrives in time, or RelayCallError if the relay
        answered {ok: false}.
        """
        conn = self._conn
        if conn is None or not conn.alive:
            raise RelayNotConnectedError()

        job_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        conn.pending[job_id] = future

        try:
            await conn.websocket.send_json({"id": job_id, "op": op, "company": company, "payload": payload})
        except Exception as e:
            conn.pending.pop(job_id, None)
            raise RelayNotConnectedError() from e

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            conn.pending.pop(job_id, None)
            raise RelayTimeoutError(op) from None


gateway = RelayGateway()
