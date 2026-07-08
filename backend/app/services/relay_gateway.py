"""Live-connection registry for the outbound relay WS channel, plus relay_call() - the single
function every future slice uses to run a job on the connected relay.

POC scope: ONE live connection at a time, and it wins. While a relay socket is registered, a second
connecting relay is rejected (the /relay-link route closes it 4409) rather than superseding the first.
This is deliberate: the old supersede-the-incumbent behaviour (issue #202 #6) both let two enrolled
relays thrash - each new connection force-closing the other, reconnecting, and superseding back - and
could drop a valid in-flight reply, failing a relay_call whose GP write had actually committed. Failing
pending calls now happens only on a genuine disconnect (unregister), where the reply truly can't arrive.
A briefly half-dead incumbent is detected by the websockets ping timeout, which fires unregister and
frees the slot for the next reconnect."""

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

    @property
    def company(self) -> str | None:
        """The GP company the currently-connected relay is enrolled for (None when disconnected).
        Surfaced on RelayStatus so the PO/receive/adopt dialogs offer only that company (issue #202 #6)."""
        return self._company

    def try_register(self, company: str, websocket: WebSocket) -> bool:
        """Called by the /relay-link route once a connecting socket has authenticated. Returns True and
        takes the single connection slot when it's free; returns False (route closes the socket) when a
        relay is already connected, so the incumbent's in-flight calls are never disturbed."""
        if self._socket is not None and self._socket is not websocket:
            return False
        self._socket = websocket
        self._company = company
        return True

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
        future: asyncio.Future = asyncio.get_running_loop().create_future()
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
