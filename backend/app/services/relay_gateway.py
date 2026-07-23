"""Live-connection registry for the outbound relay WS channel, plus relay_call() - the single
function every future slice uses to run a job on the connected relay.

POC scope: ONE live connection at a time, and it wins. While a relay socket is registered, a second
connecting relay is rejected (the /relay-link route closes it 4409) rather than superseding the first.
This is deliberate: the old supersede-the-incumbent behaviour (issue #202 #6) both let two enrolled
relays thrash - each new connection force-closing the other, reconnecting, and superseding back - and
could drop a valid in-flight reply, failing a relay_call whose GP write had actually committed. Failing
pending calls now happens only on a genuine disconnect (unregister), where the reply truly can't arrive.
A briefly half-dead incumbent is detected by the app-level heartbeat (issue #277): the /relay-link route
pings the relay on a data message every HEARTBEAT_INTERVAL_SECONDS and, after HEARTBEAT_MAX_MISSED
unanswered pings, closes the socket - which fires unregister, frees the slot, and flips relayStatus
within ~a minute instead of the ~hour it took the platform to reap the dead TCP connection."""

import asyncio
import uuid

from fastapi import WebSocket

from app.errors import RelayCallError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError

DEFAULT_TIMEOUT_SECONDS = 30.0

# App-level heartbeat (issue #277). ASGI exposes no WS ping/pong control frame, so the route rides a
# {"type": "ping"} / {"type": "pong"} data exchange rather than protocol pings. The relay's websockets
# client answers protocol pings automatically but NOT these data pings, so it carries a matching handler
# (relay channel.py). Detection is up to HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MAX_MISSED (~40s here).
HEARTBEAT_INTERVAL_SECONDS = 20.0
HEARTBEAT_MAX_MISSED = 2


class RelayGateway:
    def __init__(self) -> None:
        self._socket: WebSocket | None = None
        self._company: str | None = None
        self._pending: dict[str, asyncio.Future] = {}
        # Relay identity advertised on the connect `hello` frame (issue #315). `_build` is the relay's
        # build tag (e.g. 'relay-v0.1.0-build.30'); `_ops` is its supported op-set. Both stay None for an
        # older relay build that doesn't send a hello - in that case relay_call skips the proactive parity
        # check and relies on the reactive `unknown_op` mapping, so an out-of-date relay still yields a
        # clean RELAY_OP_UNSUPPORTED instead of a cryptic error.
        self._build: str | None = None
        self._ops: frozenset[str] | None = None
        # Heartbeat bookkeeping for the current connection (issue #277). `_unanswered_pings` counts pings
        # sent since the last pong; `_heartbeat_armed` only turns True after the relay answers its first
        # ping, so a relay build that doesn't speak the data heartbeat yet is never falsely reaped - it
        # just falls back to the old disconnect-on-read behaviour.
        self._unanswered_pings = 0
        self._heartbeat_armed = False

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def company(self) -> str | None:
        """The GP company the currently-connected relay is enrolled for (None when disconnected).
        Surfaced on RelayStatus so the PO/receive/adopt dialogs offer only that company (issue #202 #6)."""
        return self._company

    @property
    def build(self) -> str | None:
        """The connected relay's build tag from its hello frame (issue #315), None when disconnected or
        when an older relay that predates the hello frame is connected. Surfaced on RelayStatus so the
        Admin -> Relay Installs page can show which build is live."""
        return self._build

    def try_register(self, company: str, websocket: WebSocket) -> bool:
        """Called by the /relay-link route once a connecting socket has authenticated. Returns True and
        takes the single connection slot when it's free; returns False (route closes the socket) when a
        relay is already connected, so the incumbent's in-flight calls are never disturbed."""
        if self._socket is not None and self._socket is not websocket:
            return False
        self._socket = websocket
        self._company = company
        self._build = None
        self._ops = None
        self._unanswered_pings = 0
        self._heartbeat_armed = False
        return True

    def unregister(self, websocket: WebSocket) -> None:
        """Called by the /relay-link route when its socket disconnects."""
        if self._socket is websocket:
            self._socket = None
            self._company = None
            self._build = None
            self._ops = None
            self._unanswered_pings = 0
            self._heartbeat_armed = False
            self._fail_all("relay disconnected")

    def note_hello(self, build: str | None, ops: list[str] | None) -> None:
        """Called by the route's read loop for the relay's one {"type": "hello", build, ops} frame,
        sent right after it connects (issue #315). Records the build tag and op-set so relay_call can
        reject an unsupported op before the round-trip and RelayStatus can report the live build. Only
        honoured for the currently-registered socket."""
        if self._socket is not None:
            self._build = build
            self._ops = frozenset(ops) if ops is not None else None

    def note_pong(self) -> None:
        """Called by the route's read loop for each {"type": "pong"} the relay sends. Clears the miss
        counter and arms the reaper - once the relay has answered one ping, missed pings mean it's gone."""
        if self._socket is not None:
            self._unanswered_pings = 0
            self._heartbeat_armed = True

    def register_ping_miss(self) -> bool:
        """Called by the route's heartbeat once per interval, just before it sends the next ping. Counts
        the pings the relay hasn't answered yet and returns True when it has gone quiet long enough to
        reap (HEARTBEAT_MAX_MISSED unanswered pings) - but only once armed, so a relay that never answers
        a ping is left to the disconnect-on-read path rather than being killed on a false positive."""
        self._unanswered_pings += 1
        return self._heartbeat_armed and self._unanswered_pings >= HEARTBEAT_MAX_MISSED

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
        RelayOpUnsupportedError (relay too old for this op, issue #315), or RelayCallError (the relay
        itself answered ok=false)."""
        if self._socket is None:
            raise RelayUnavailableError()
        if self._company and company != self._company:
            raise RelayUnavailableError(f"connected relay is enrolled for {self._company}, not {company}")
        # Proactive parity (issue #315): if the relay advertised its op-set on connect and this op isn't
        # in it, fail fast with a clear 'update the relay' error rather than a 30s round-trip. Skipped when
        # `_ops` is None (an older relay that sends no hello) - the reactive `unknown_op` mapping below
        # still catches it.
        if self._ops is not None and op not in self._ops:
            raise RelayOpUnsupportedError(op)

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
            # Reactive parity (issue #315): an out-of-date relay answers a call for an op it lacks with
            # `unknown_op`. Map that to the same clear 'update the relay' error the proactive check raises,
            # so a relay that predates the hello frame still surfaces cleanly instead of as a raw
            # `unknown op '...'` string.
            if error.get("error") == "unknown_op":
                raise RelayOpUnsupportedError(op, detail=error)
            raise RelayCallError(error.get("message") or f"{op} failed", detail=error)
        return reply.get("result")


gateway = RelayGateway()
