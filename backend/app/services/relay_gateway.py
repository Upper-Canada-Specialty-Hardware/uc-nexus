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
within ~a minute instead of the ~hour it took the platform to reap the dead TCP connection.

Every connection-slot transition is logged (issue #384). On 2026-07-28 the relay dropped for ~5 minutes
and reconnected on its own, and the backend logs could not say when it went, why, or how long it had
been up: unregister wrote nothing, and the only relay line uvicorn emits is the access log for the
accepted socket, so a socket held open for days produced exactly one log line for its whole lifetime.
An absent disconnect line carries no information, so there was nothing to correlate against the relay's
own logs. The gateway now names the disconnect and, crucially, says WHOSE fault it was: a heartbeat reap
(we closed a relay that stopped answering) and a peer close (the socket went away under us) are different
failures with different owners, and by the time unregister runs in the route's `finally` neither is
distinguishable from the other."""

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence

from fastapi import WebSocket

from app.errors import RelayCallError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError

logger = logging.getLogger(__name__)


def normalize_company(company: str | None) -> str:
    """A GP company code in the one form everything compares on: trimmed and uppercase.

    GP's own codes are uppercase, and a company reaches this backend from three places that spell it
    differently - a relay_installs row, a Clerk publicMetadata value an admin typed, and a GraphQL
    argument - so the normalization has to happen somewhere shared or the membership checks quietly
    fail on case alone."""
    return (company or "").strip().upper()


def _normalize_companies(companies: Sequence[str] | str | None) -> frozenset[str]:
    """The allowed-company set for an install. A bare string is treated as the one-company case: a
    str is itself a Sequence[str], so iterating it would yield characters."""
    if companies is None:
        return frozenset()
    if isinstance(companies, str):
        companies = [companies]
    return frozenset(filter(None, (normalize_company(c) for c in companies)))


DEFAULT_TIMEOUT_SECONDS = 30.0

# App-level heartbeat (issue #277). ASGI exposes no WS ping/pong control frame, so the route rides a
# {"type": "ping"} / {"type": "pong"} data exchange rather than protocol pings. The relay's websockets
# client answers protocol pings automatically but NOT these data pings, so it carries a matching handler
# (relay channel.py). Detection is up to HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MAX_MISSED (~40s here).
HEARTBEAT_INTERVAL_SECONDS = 20.0
HEARTBEAT_MAX_MISSED = 2
# Limit for a connection that has NEVER answered a ping (#353 PR F). The original conservatism -
# never reaping an unarmed connection - existed to protect relay builds that predated the data
# heartbeat (issue #277). Every shipped build answers it now, and the asymmetry of being wrong is
# stark: reaping a hypothetical old relay costs one automatic reconnect, while NOT reaping a relay
# that connected and then went silent wedges the single connection slot for the ~hour the platform
# takes to reap the dead TCP socket - during which no other relay can take the slot and every GP
# write fails. A longer limit than the armed one still gives a slow starter room.
HEARTBEAT_MAX_MISSED_UNARMED = 4

# RFC 6455 close code 1012, "Service Restart". Sent on a graceful backend shutdown so the relay can
# tell a deploy from a network blip and reconnect immediately instead of backing off (#353 PR F).
SERVICE_RESTART_CLOSE_CODE = 1012
_SHUTDOWN_TIMEOUT_SECONDS = 2.0

# Why the live socket went away (issue #384). unregister() is called from the /relay-link route's
# `finally`, which by then cannot tell one ending from another - a heartbeat reap, the relay closing,
# and the TCP connection dying all just end the read loop. So whichever path DECIDES the disconnect
# stamps its reason on the gateway first, and unregister reports what it finds. No stamp means nobody
# on this side decided, i.e. the peer closed or the socket dropped under us.
DISCONNECT_REASON_PEER = "peer closed or socket dropped"
DISCONNECT_REASON_SHUTDOWN = "closed for server shutdown"


class RelayGateway:
    def __init__(self) -> None:
        self._socket: WebSocket | None = None
        # Every GP company the live install may be called for (#637). A frozenset because the only
        # question relay_call asks of it is membership, and the relay has always been able to serve
        # more than one company - the single value this replaces was a backend-side assumption.
        self._companies: frozenset[str] = frozenset()
        # Which relay_installs row authenticated the live connection (#366). Without it the backend knows
        # a relay is connected but not WHICH install it is, so delete_relay_install cannot refuse to
        # revoke the credential currently holding the connection.
        self._install_id: uuid.UUID | None = None
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
        # Disconnect diagnosability (issue #384). `_registered_at` is a monotonic stamp taken when the
        # connection slot is claimed, so the disconnect line can report how long the socket was actually
        # held - the difference between "it had been up for days" and "it never got past the handshake"
        # is most of the diagnosis. `_disconnect_reason` is stamped by whichever path decided the
        # disconnect (see DISCONNECT_REASON_* above); None at unregister time means the peer did.
        self._registered_at: float | None = None
        self._disconnect_reason: str | None = None

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def companies(self) -> list[str]:
        """The GP companies the currently-connected relay is enrolled for; empty when disconnected.
        Surfaced on RelayStatus so the PO/receive/adopt dialogs offer only companies the live relay can
        actually serve (issue #202 #6, widened to a list in #637). Sorted so the answer is stable."""
        return sorted(self._companies)

    @property
    def install_id(self) -> uuid.UUID | None:
        """The relay_installs row backing the live connection (None when disconnected). Lets
        delete_relay_install refuse to revoke the credential that is currently holding the connection,
        and lets RelayStatus name which install is live instead of the grid inferring it (#366)."""
        return self._install_id

    @property
    def build(self) -> str | None:
        """The connected relay's build tag from its hello frame (issue #315), None when disconnected or
        when an older relay that predates the hello frame is connected. Surfaced on RelayStatus so the
        Admin -> Relay Installs page can show which build is live."""
        return self._build

    def try_register(self, companies: Sequence[str], websocket: WebSocket, install_id: uuid.UUID | None = None) -> bool:
        """Called by the /relay-link route once a connecting socket has authenticated. Returns True and
        takes the single connection slot when it's free; returns False (route closes the socket) when a
        relay is already connected, so the incumbent's in-flight calls are never disturbed.

        `companies` is the install's whole allowed list (#637). A bare string is accepted as the
        one-company case: a str is itself a Sequence[str], so without this it would silently register
        the set of its CHARACTERS and reject every real company."""
        incoming = _normalize_companies(companies)
        if self._socket is not None and self._socket is not websocket:
            # A refused reconnect is otherwise completely silent (issue #384), and it is exactly what a
            # zombie incumbent looks like from the outside: the real relay dialling back in every few
            # seconds and being turned away while a dead socket holds the slot, until the heartbeat
            # reaps it up to HEARTBEAT_INTERVAL_SECONDS * HEARTBEAT_MAX_MISSED later. Name the incumbent
            # and how long it has held the slot so that window is readable in the logs.
            logger.warning(
                "relay connection refused: slot already held (holder install=%s companies=%s build=%s "
                "held_seconds=%s, refused install=%s companies=%s)",
                self._install_id,
                self.companies,
                self._build,
                self._held_seconds(),
                install_id,
                sorted(incoming),
                extra={
                    "install_id": str(self._install_id) if self._install_id is not None else None,
                    "companies": self.companies,
                    "build": self._build,
                    "held_seconds": self._held_seconds(),
                    "refused_install_id": str(install_id) if install_id is not None else None,
                    "refused_companies": sorted(incoming),
                },
            )
            return False
        self._socket = websocket
        self._companies = incoming
        self._install_id = install_id
        self._build = None
        self._ops = None
        self._unanswered_pings = 0
        self._heartbeat_armed = False
        self._registered_at = time.monotonic()
        self._disconnect_reason = None
        return True

    def unregister(self, websocket: WebSocket) -> None:
        """Called by the /relay-link route's `finally` when its socket disconnects, and by
        close_for_shutdown once it has said goodbye.

        The identity check is load-bearing, not defensive noise: a second relay refused at try_register
        (the route closes it 4409) shares this gateway with the live one, so tearing that socket down
        must not clear the incumbent's company/install/heartbeat state, consume its stamped disconnect
        reason, or log the live connection away as if it had dropped.

        Logs the disconnect (issue #384) with everything needed to correlate against the relay's own
        logs: which install and company, which relay build (learned from the hello frame), how long the
        socket was held, how many in-flight calls died with it, and - the part nothing else can
        reconstruct after the fact - whether we reaped it or it went away on its own."""
        if self._socket is not websocket:
            return
        reason = self._disconnect_reason or DISCONNECT_REASON_PEER
        # A shutdown is not a relay failure: the deploy closed the socket on purpose and the relay is
        # already reconnecting (close code 1012). Logging it at WARNING beside genuine drops would
        # train everyone to ignore the warning that matters. Note that INFO is effectively dev-only
        # here - uvicorn's default logging config configures only the `uvicorn*` loggers, so records
        # from app modules reach an unconfigured root logger and render through logging.lastResort,
        # which is WARNING-and-above - but a deploy is already visible in uvicorn's own shutdown lines.
        level = logging.INFO if reason == DISCONNECT_REASON_SHUTDOWN else logging.WARNING
        # The facts are repeated into the message rather than left to `extra` alone, for that same
        # reason: lastResort renders "%(message)s" and drops every extra field, so anything not in the
        # message is invisible in exactly the Railway logs this line exists to serve. `extra` is kept
        # for whenever a structured handler is configured, matching how the rest of the backend logs.
        logger.log(
            level,
            "relay disconnected: %s (install=%s companies=%s build=%s held_seconds=%s pending_calls=%d)",
            reason,
            self._install_id,
            self.companies,
            self._build,
            self._held_seconds(),
            len(self._pending),
            extra={
                "install_id": str(self._install_id) if self._install_id is not None else None,
                "companies": self.companies,
                "build": self._build,
                "held_seconds": self._held_seconds(),
                "reason": reason,
                "pending_calls": len(self._pending),
            },
        )
        self._socket = None
        self._companies = frozenset()
        self._install_id = None
        self._build = None
        self._ops = None
        self._unanswered_pings = 0
        self._heartbeat_armed = False
        self._registered_at = None
        self._disconnect_reason = None
        # The reason rides the error too: it lands on the failed GraphQL call and on any outbox row, so
        # the person looking at "relay unavailable" in the UI sees the same cause as the log line.
        self._fail_all(f"relay disconnected: {reason}")

    def _held_seconds(self) -> float | None:
        """How long the live socket has held the connection slot, None when nothing is registered.
        Monotonic, so it survives a clock adjustment on the host (issue #384)."""
        if self._registered_at is None:
            return None
        return round(time.monotonic() - self._registered_at, 1)

    def note_hello(self, build: object, ops: object) -> None:
        """Called by the route's read loop for the relay's one {"type": "hello", build, ops} frame,
        sent right after it connects (issue #315). Records the build tag and op-set so relay_call can
        reject an unsupported op before the round-trip and RelayStatus can report the live build. Only
        honoured for the currently-registered socket.

        The frame is untrusted wire input, so both fields are shape-checked: only a str build and a
        list-of-str op-set are accepted. A malformed op-set (a bare string would otherwise become a set
        of characters and reject every real op; a non-iterable would raise inside the read loop) is
        treated as 'unknown' (None), so relay_call falls back to the reactive unknown_op mapping."""
        if self._socket is not None:
            self._build = build if isinstance(build, str) else None
            self._ops = frozenset(ops) if isinstance(ops, list) and all(isinstance(o, str) for o in ops) else None

    def note_pong(self) -> None:
        """Called by the route's read loop for each {"type": "pong"} the relay sends. Clears the miss
        counter and arms the reaper - once the relay has answered one ping, missed pings mean it's gone."""
        if self._socket is not None:
            self._unanswered_pings = 0
            self._heartbeat_armed = True

    def register_ping_miss(self) -> bool:
        """Called by the route's heartbeat once per interval, just before it sends the next ping.
        Counts the pings the relay hasn't answered yet and returns True once it has gone quiet long
        enough to reap.

        Two limits (#353 PR F). An ARMED connection - one that has answered at least one ping - is
        reaped after HEARTBEAT_MAX_MISSED (~40s), as before. An UNARMED one, which previously could
        never be reaped at all, is reaped after the longer HEARTBEAT_MAX_MISSED_UNARMED (~80s): a
        relay that connects, takes the single slot and never pongs used to hold that slot until the
        platform reaped the dead TCP connection about an hour later, blocking every other relay
        (try_register -> close 4409) and failing every GP write for the duration."""
        self._unanswered_pings += 1
        limit = HEARTBEAT_MAX_MISSED if self._heartbeat_armed else HEARTBEAT_MAX_MISSED_UNARMED
        if self._unanswered_pings < limit:
            return False
        # Stamp the reason for the disconnect this return value is about to cause (issue #384). The
        # heartbeat loop closes the socket on True, which ends the read loop and lands in the route's
        # `finally` -> unregister, where nothing can tell a reap from the relay having dropped on its
        # own. Recording it here is the only moment that knowledge exists. Counts come from the live
        # constants so the line stays true if the limits are retuned.
        self._disconnect_reason = (
            f"reaped after {self._unanswered_pings} missed pings "
            f"({'armed' if self._heartbeat_armed else 'unarmed'} limit {limit}, "
            f"{HEARTBEAT_INTERVAL_SECONDS:g}s interval)"
        )
        return True

    async def close_for_shutdown(self) -> None:
        """Say goodbye to the relay before the process goes (#353 PR F).

        A container restart otherwise just drops the TCP connection, and the relay treats that like
        any other drop: it grows its exponential backoff and can sit out the first 30s of the new
        deployment for no reason. A `going_away` frame plus close code 1012 (Service Restart) tells
        it this is a restart, so a relay carrying the matching client change reconnects immediately.

        Best-effort throughout, with a short timeout: a half-dead socket must not hold up shutdown,
        and the relay reconnects either way."""
        socket = self._socket
        if socket is None:
            return
        # Stamp before the goodbye, not after: the send/close below can wake the route's read loop and
        # get it to unregister first, and either way this is the one path that knows the drop was ours
        # and deliberate. Without the stamp a deploy reads in the logs exactly like a relay failure
        # (issue #384).
        self._disconnect_reason = DISCONNECT_REASON_SHUTDOWN
        try:
            await asyncio.wait_for(socket.send_json({"type": "going_away"}), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            pass
        try:
            await asyncio.wait_for(socket.close(code=SERVICE_RESTART_CLOSE_CODE), timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except Exception:
            pass
        self.unregister(socket)

    def _fail_all(self, message: str) -> None:
        # dispatched=True: every job in `_pending` was already sent to the relay, so GP may have run
        # it and the reply was lost with the socket. The outbox (#353 PR E) must NOT queue these - a
        # blind retry would post a second receipt or reserve a second PO number.
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(RelayUnavailableError(message, dispatched=True))

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
        if self._companies and company not in self._companies:
            raise RelayUnavailableError(f"connected relay is enrolled for {', '.join(self.companies)}, not {company}")
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
