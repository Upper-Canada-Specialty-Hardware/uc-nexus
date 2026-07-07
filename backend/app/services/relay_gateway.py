"""Live-connection registry for the outbound relay WS channel, plus relay_call() - the single
function every future slice uses to run a job on the connected relay.

POC scope: one live connection at a time. A new connection replaces whatever was there; anything still
awaiting a reply on the old connection fails with RelayUnavailableError rather than hanging."""

import asyncio
import uuid

from fastapi import WebSocket

from app.errors import RelayCallError, RelayTimeoutError, RelayUnavailableError

DEFAULT_TIMEOUT_SECONDS = 30.0


class RelayGateway:
    def __init__(self) -> None:
        self._socket: WebSocket | None = None
        self._company: str | None = None
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._socket is not None

    async def register(self, company: str, websocket: WebSocket) -> None:
        """Called by the /relay-link route once a connecting socket has authenticated."""
        old = self._socket
        self._socket = websocket
        self._company = company
        if old is not None and old is not websocket:
            self._fail_all("superseded by a new relay connection")
            try:
                await old.close(code=4409)
            except Exception:
                pass

    def unregister(self, websocket: WebSocket) -> None:
        """Called by the /relay-link route when its socket disconnects."""
        if self._socket is websocket:
            self._socket = None
            self._company = None
            self._fail_all("relay disconnected")

    def _fail_all(self, message: str) -> None:
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(RelayUnavailableError(message))

    def resolve(self, reply: dict) -> None:
        """Called by the /relay-link route's read loop with each {id, ok, result|error} reply."""
        future = self._pending.pop(reply.get("id"), None)
        if future is not None and not future.done():
            future.set_result(reply)

    async def relay_call(
        self, company: str, op: str, payload: dict | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> dict | list | None:
        """Send {id, op, company, payload} to the connected relay and await its correlated reply.
        Raises RelayUnavailableError (no/wrong-company connection or send failure), RelayTimeoutError,
        or RelayCallError (the relay itself answered ok=false)."""
        if self._socket is None:
            raise RelayUnavailableError()
        if self._company and company != self._company:
            raise RelayUnavailableError(f"connected relay is enrolled for {self._company}, not {company}")

        job_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[job_id] = future
        try:
            await self._socket.send_json({"id": job_id, "op": op, "company": company, "payload": payload or {}})
        except Exception as e:
            self._pending.pop(job_id, None)
            raise RelayUnavailableError(f"failed to send job to relay: {e}") from e

        try:
            reply = await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            self._pending.pop(job_id, None)
            raise RelayTimeoutError(f"relay did not answer {op!r} within {timeout}s") from None

        if not reply.get("ok"):
            error = reply.get("error") or {}
            raise RelayCallError(error.get("message") or f"{op} failed", detail=error)
        return reply.get("result")


gateway = RelayGateway()
