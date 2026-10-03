import asyncio
import contextlib
import inspect
import logging
import os
import sys
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import strawberry
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from graphql import GraphQLError, GraphQLResolveInfo
from strawberry.extensions import SchemaExtension
from strawberry.fastapi import GraphQLRouter

from app.auth import get_context, require_admin_request
from app.auth_policy import enforce_root_field
from app.config import cors_allow_origins
from app.database import SessionLocal
from app.errors import AppError
from app.models.enums import RelayEventKind
from app.repositories import relay_repository
from app.schemas.mutations import Mutation
from app.schemas.queries import Query
from app.services import (
    gp_job_sync,
    gp_outbox_worker,
    gp_po_sync,
    gp_sync_state,
    relay_adopt,
    relay_events,
)
from app.services.relay_gateway import HEARTBEAT_INTERVAL_SECONDS
from app.services.relay_gateway import gateway as relay_gateway


def _configure_logging() -> None:
    """Give the root logger a stdout handler at LOG_LEVEL (default INFO), at import, before anything
    logs.

    Nothing did this before, so every logger.info() under app.* fell through to Python's last-resort
    handler, which emits WARNING and above and drops the rest - which is why the GP sync services
    logged nothing at all in production while a backfill ran for fifteen hours.

    basicConfig is a no-op once the root logger already has handlers, and that is the guard: a pytest
    or TestClient import finds pytest's own handlers in place and is left alone. Uvicorn configures
    its own loggers separately and is unaffected either way."""
    level = logging.getLevelName(os.getenv("LOG_LEVEL", "").strip().upper() or "INFO")
    if not isinstance(level, int):  # an unknown LOG_LEVEL must not be a boot failure
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)


_configure_logging()

logger = logging.getLogger(__name__)

# An adopted socket has to prove it is a relay before it is trusted with the connection slot: a
# legitimate relay always sends {"type": "hello"} as its first frame (channel.py `_run_once` sends it
# before entering the read loop), so a short wait for one costs a real relay nothing.
ADOPT_HELLO_TIMEOUT_SECONDS = 5.0

# How long the CONNECTED event waits for the hello frame before recording the connection without a
# build. The hello is the relay's first frame, so this is only ever spent on a relay old enough not to
# send one - and recording that connection late, with an unknown build, still beats not recording it.
CONNECTED_EVENT_HELLO_GRACE_SECONDS = 5.0

# What uuid.UUID() says about a string that is not one; matched to tell a malformed id argument from a
# real fault (#1114).
_MALFORMED_UUID = "badly formed hexadecimal UUID string"
_INTERNAL_MESSAGE = "Something went wrong on the server. Try again, and report it if it keeps happening."


class ResolverGuardExtension(SchemaExtension):
    """The one hook every GraphQL field resolution passes through. It does two jobs.

    1. **Authorizes root fields** against ROOT_FIELD_POLICY (app/auth_policy.py), before the resolver
       runs. Deny-by-default: a field with no policy entry and no place on the open-operations
       allowlist is refused, so #415's "a resolver that forgets its gate is public" cannot recur.
       Only root fields are checked (`info.path.prev is None`) - a nested field is reachable only
       through a root field that already passed, and checking every one would put a Clerk decision on
       every node of every response.
    2. **Maps AppError to GraphQLError**, publishing `extensions.code` (and `relayError` where the
       error carries a detail body).
    3. **Masks everything else** (#1114). An exception that is not an AppError is a bug, and its text
       is not for the browser: a SQLAlchemy IntegrityError carries the statement and its bound
       parameters. It is answered with a generic INTERNAL error and kept as the error's
       original_error, which Strawberry logs with its traceback.
       The one routine case, an id argument that is not a UUID, is a VALIDATION_ERROR instead.
       A GraphQLError raised on purpose passes through untouched.

    Both live in one extension rather than two on purpose:

      - The gate's own refusals are AppErrors, and they MUST reach the browser as
        `extensions.code = UNAUTHENTICATED` / `FORBIDDEN`; the frontend's Apollo link keys its token
        re-mint and replay off exactly that (#429). Sharing one try/except makes that structural. As
        two extensions it would depend on their order in the `extensions=[...]` list, which nothing
        would fail on if someone swapped it.
      - `resolve` is graphql-core middleware: it runs per FIELD, not per operation, including every
        scalar of every row in a list of hundreds. A second extension would double that wrapper cost
        for no functional gain.
    """

    @staticmethod
    def _to_graphql_error(e: Exception) -> GraphQLError:
        if isinstance(e, AppError):
            extensions: dict[str, Any] = {"code": e.code}
            if e.field:
                extensions["field"] = e.field
            # A RelayCallError carries the relay's own error body ({error, message, context}) - the eConnect
            # proc, numeric error_state, and its DYNAMICS.taErrorCode description. Surface it under
            # `relayError` so the frontend can show the full GP failure (issue #187: end-user error
            # screenshots are the main way these get reported, so the detail must reach the browser, not
            # just the generic RELAY_CALL_FAILED code). Generic: any AppError that sets `.detail`.
            detail = getattr(e, "detail", None)
            if detail:
                extensions["relayError"] = detail
            return GraphQLError(message=e.message, extensions=extensions)
        return GraphQLError(message=str(e), extensions={"code": "NOT_IMPLEMENTED"})

    @staticmethod
    def _mask(e: Exception, info: GraphQLResolveInfo) -> GraphQLError:
        """The answer for an exception no resolver meant to raise (#1114).

        `uuid.UUID(str(id))` is how resolvers parse every ID argument, so a malformed one surfaces as
        this ValueError; it is the caller's mistake, not ours, and says so.

        The original rides along as `original_error`, which graphql-core never serialises: Strawberry's
        execution logger writes it out with its traceback, so the server log keeps everything the
        browser no longer sees."""
        if isinstance(e, ValueError) and str(e) == _MALFORMED_UUID:
            return GraphQLError(
                message=f"{info.field_name}: that id is not valid.",
                original_error=e,
                extensions={"code": "VALIDATION_ERROR"},
            )
        return GraphQLError(message=_INTERNAL_MESSAGE, original_error=e, extensions={"code": "INTERNAL"})

    @staticmethod
    def _is_root_field(info: GraphQLResolveInfo) -> bool:
        """A field selected directly on Query/Mutation, and ours rather than graphql-core's.

        The `__`-prefixed introspection fields (`__schema`, `__type`, `__typename`) are root fields
        too, and they are resolved by graphql-core's own resolvers, which this middleware also wraps.
        They expose the schema's shape, never any data, and they were reachable before #423 - gating
        them would break GraphiQL and every introspection-driven tool for no security gain.
        """
        return info.path.prev is None and not info.field_name.startswith("__")

    def resolve(self, _next: Callable, root: Any, info: GraphQLResolveInfo, *args, **kwargs):
        # For async resolvers _next() returns a coroutine that strawberry awaits *after* this method
        # returns, so a synchronous try/except here would never see the exception - the AppError -> code
        # mapping would be silently dropped. Handle the awaitable case in an async wrapper so both sync
        # and async resolvers get the extension pattern.
        try:
            # Inside the try so a refusal is mapped by the same code path as any other AppError, and
            # ahead of _next so the resolver body never starts for a caller who is about to be
            # refused - the ordering #415's gates could only achieve by convention.
            if self._is_root_field(info):
                enforce_root_field(info.field_name, info.context)
            result = _next(root, info, *args, **kwargs)
        except (AppError, NotImplementedError) as e:
            raise self._to_graphql_error(e) from e
        except GraphQLError:
            raise
        except Exception as e:
            raise self._mask(e, info) from e
        if inspect.isawaitable(result):
            return self._resolve_async(result, info)
        return result

    async def _resolve_async(self, awaitable, info: GraphQLResolveInfo):
        try:
            return await awaitable
        except (AppError, NotImplementedError) as e:
            raise self._to_graphql_error(e) from e
        except GraphQLError:
            raise
        except Exception as e:
            raise self._mask(e, info) from e


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[ResolverGuardExtension],
)

graphql_app = GraphQLRouter(schema, context_getter=get_context)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Own the background GP outbox drainer (#353 PR E) and the GP job sync (#380).

    Started here rather than lazily on first use so a queue that filled during a deploy starts
    draining as soon as the new container is up, with nobody having to visit a page. Under
    TestClient(app) this runs too, and is harmless: with no relay registered neither loop queries."""
    tasks: list[asyncio.Task] = []
    if gp_outbox_worker.enabled():
        tasks.append(asyncio.create_task(gp_outbox_worker.run_forever()))
    if gp_job_sync.enabled():
        tasks.append(asyncio.create_task(gp_job_sync.run_forever()))
    if gp_po_sync.enabled():
        tasks.append(asyncio.create_task(gp_po_sync.run_forever()))
    # Hands the connected relay this backend's own GP SYNC STATE every few seconds, so the NEXUS GP
    # TRAFFIC tab on the workstation shows MIRROR PROGRESS and pacing and not only what the relay saw.
    # Inert until a relay advertising the feature connects (#679).
    if gp_sync_state.enabled():
        tasks.append(asyncio.create_task(gp_sync_state.run_forever()))
    try:
        yield
    finally:
        # Close the relay socket cleanly BEFORE stopping the workers (#353 PR F). The relay then knows
        # this is a restart rather than a blip and reconnects at once; anything it was about to send
        # will queue on the outbox and drain when it does.
        await relay_gateway.close_for_shutdown()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="UC Nexus - Hardware Management System", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
def health():
    """Liveness, plus the one fact worth asking a backend without a session: is the relay up.

    Deliberately unauthenticated and database-free - it is what Railway's healthcheck calls, and what
    somebody curls when a GP-dependent page is failing. The relay facts come from the gateway's
    in-memory state, so this stays a constant-cost answer even when the database is the thing that is
    unwell.

    The three timestamps deliberately outlive the connection they describe: "it went at 14:02 with
    this reason and has not been back" is the answer somebody wants when `relay_connected` is false,
    and it is the difference between "the relay never dialled this backend" and "it dialled and was
    dropped" without a session or a log dive.

    `backfill_window` / `backfill_window_open` say when GP's history drain may run and whether it may
    right now - the first thing to check when the backfill looks stalled during the day, because
    during the day it is supposed to be."""

    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "status": "ok",
        "relay_connected": relay_gateway.connected,
        "relay_companies": relay_gateway.companies,
        "relay_last_connected_at": _iso(relay_gateway.last_connected_at),
        "relay_last_disconnected_at": _iso(relay_gateway.last_disconnected_at),
        "relay_last_disconnect_reason": relay_gateway.last_disconnect_reason,
        # When the PO history drain is allowed to run, and whether it is allowed right now. Two string
        # comparisons against a converted clock - no database, no relay round trip - so it costs the
        # probe nothing, and it answers "why has the backfill not moved since this morning" without a
        # log dive.
        "backfill_window": gp_po_sync.BACKFILL_WINDOW.label,
        "backfill_window_open": gp_po_sync.BACKFILL_WINDOW.allows(datetime.utcnow()),
    }


async def _relay_read_loop(websocket: WebSocket) -> None:
    """Feed each frame the relay sends to relay_gateway: a {"type": "hello"} advertises the relay's build,
    op-set, discovered GP companies and features on connect (issue #315, #654), a {"type": "pong"} answers
    the heartbeat (issue #277), anything else is a {id, ok, result|error} job reply to correlate with
    relay_call().

    It also re-wakes the GP sync loops, because the hello is where the GP company list actually
    arrives: the wake they get from /relay-link fires at try_register, one frame too early to be
    useful."""
    while True:
        message = await websocket.receive_json()
        if isinstance(message, dict) and message.get("type") == "hello":
            relay_gateway.note_hello(
                message.get("build"),
                message.get("ops"),
                message.get("companies"),
                message.get("features"),
                message.get("company_names"),
                message.get("companies_error"),
            )
            # And the first GP SYNC STATE goes out now rather than up to a push interval later, so the
            # relay window's NEXUS GP TRAFFIC tab has something to show the moment it connects (#679).
            gp_sync_state.wake()
            # The company list arrives HERE, not at try_register - and the sync loops were woken back
            # there, when `companies` was still empty. Without this second nudge each loop sits on its
            # own timer with a pending all-companies pass it cannot run, which on 2026-09-03 left the
            # PO mirror silent for over ten minutes after a reconnect. wake() is idempotent and costs
            # nothing when a loop is already running.
            if relay_gateway.companies:
                gp_po_sync.wake()
                gp_job_sync.wake()
        elif isinstance(message, dict) and message.get("type") == "pong":
            relay_gateway.note_pong()
        else:
            relay_gateway.resolve(message)


async def _relay_heartbeat_loop(websocket: WebSocket) -> None:
    """Ping the connected relay on a data message every interval; once it misses too many pongs, close
    the socket so the route's finally unregisters it and relayStatus flips (issue #277). ASGI has no WS
    ping frame, so this is an application-level {"type": "ping"} the relay answers with {"type": "pong"}."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
        if relay_gateway.register_ping_miss():
            # The relay has gone quiet: close so the read loop ends and finally -> unregister runs, which
            # also fails any in-flight relay_call fast instead of letting it burn the full 30s timeout.
            # A half-dead socket may fail to close; reaping is decided either way, so swallow and return.
            try:
                await websocket.close(code=1011)
            except Exception:
                pass
            return
        try:
            await websocket.send_json({"type": "ping"})
        except Exception:
            # Socket already gone; let the read loop's disconnect drive unregister via the route's finally.
            return


async def _await_hello(websocket: WebSocket) -> bool:
    """Read one frame and require it to be the relay's hello. Used only for connections accepted
    through an adopt window (#353 PR B), where the presented secret was unknown until an admin armed
    the window - so the socket must still show it speaks the relay protocol before it is trusted with
    the single connection slot. The hello is fed to the gateway exactly as the read loop would, so an
    adopted relay reports its build like any other. Returns False (socket closed 4403) on a timeout or
    a first frame that is not a hello."""
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=ADOPT_HELLO_TIMEOUT_SECONDS)
    except Exception:
        message = None
    if not isinstance(message, dict) or message.get("type") != "hello":
        logger.warning("relay adopt: connection did not send a hello frame; closing")
        try:
            await websocket.close(code=4403)
        except Exception:
            pass
        return False
    relay_gateway.note_hello(
        message.get("build"),
        message.get("ops"),
        message.get("companies"),
        message.get("features"),
        message.get("company_names"),
        message.get("companies_error"),
    )
    # The same immediate GP SYNC STATE push the read loop's hello branch asks for (#679): an adopted
    # relay's NEXUS GP TRAFFIC tab must not wait out a push interval that a re-enrolled one does not.
    gp_sync_state.wake()
    return True


async def _serve_relay_link(websocket: WebSocket, require_hello: bool = False) -> None:
    """Run the relay read loop and the heartbeat concurrently. Whichever finishes first (a disconnect,
    or the heartbeat reaping a silent relay) cancels the other; a read-loop disconnect is re-raised so
    the route's `except WebSocketDisconnect` handles it exactly as before the heartbeat existed.

    `require_hello` gates an adopted connection on a hello frame first; it is never set for a normally
    authenticated relay, so the ordinary handshake cannot regress."""
    if require_hello and not await _await_hello(websocket):
        return
    reader = asyncio.create_task(_relay_read_loop(websocket))
    heartbeat = asyncio.create_task(_relay_heartbeat_loop(websocket))
    try:
        done, _ = await asyncio.wait({reader, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        reader.cancel()
        heartbeat.cancel()
        await asyncio.gather(reader, heartbeat, return_exceptions=True)
    # Surface a genuine reader disconnect so the route handles it as before. Skip a task that finished by
    # cancellation: task.exception() re-raises CancelledError there, which would propagate out of the
    # route uncaught and mark the whole route task cancelled (a spurious failure on a clean teardown).
    for task in done:
        if task.cancelled():
            continue
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            continue
        if exc is not None:
            raise exc


# Strong references to the in-flight CONNECTED writers below; asyncio only holds a weak one.
_connected_event_tasks: set[asyncio.Task] = set()


async def _record_connected(websocket: WebSocket, install_id, connected_at: datetime) -> None:
    """Write the CONNECTED event once the hello frame has told us which relay build this is.

    Stamped with the moment the slot was claimed, not the moment this runs, so the row still orders
    correctly against the DISCONNECTED that may already have been written for a connection that lasted
    less than the grace period."""
    hello = relay_gateway.hello_seen()
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(hello.wait(), timeout=CONNECTED_EVENT_HELLO_GRACE_SECONDS)
    # Only report a build and companies while THIS socket still holds the slot: a relay that dropped and
    # was replaced inside the grace window would otherwise stamp its successor's identity on this row.
    live = relay_gateway.holds(websocket)
    await relay_events.write(
        RelayEventKind.CONNECTED,
        at=connected_at,
        install_id=install_id,
        build=relay_gateway.build if live else None,
        companies=relay_gateway.companies if live else None,
    )


@app.websocket("/relay-link")
async def relay_link(websocket: WebSocket):
    """The relay's outbound wss channel. It dials in with `Authorization: Bearer <enrolled secret>`
    on the connect handshake; once verified, this holds the socket open and feeds every {id, ok,
    result|error} reply it sends back to relay_gateway so relay_call() can correlate it to the job
    that requested it. Every other slice reaches the relay through relay_call(), never this route
    directly."""
    auth_header = websocket.headers.get("authorization") or ""
    scheme, _, secret = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not secret.strip():
        await websocket.close(code=4401)
        return

    adopted = False
    adopted_by: str | None = None
    with SessionLocal() as session:
        install = relay_repository.authenticate_secret(session, secret.strip())
        if install is None:
            # No install matched. If an admin has armed an adopt window, bind the presented secret to
            # that install instead of refusing (#353 PR B): this is the only recovery path for a relay
            # whose stored secret has drifted from the one it is dialling with, when nobody can reach
            # the workstation to restart it. Adoption is consumed here, single-use.
            window = relay_adopt.peek()
            if window is not None:
                install = relay_repository.adopt_secret(session, window.install_id, secret.strip(), window.armed_by)
                if install is not None and relay_adopt.consume(window.install_id):
                    adopted = True
                    adopted_by = window.armed_by
                    logger.warning(
                        "relay adopt: presented secret bound to install",
                        extra={
                            "install_id": str(window.install_id),
                            "label": window.label,
                            "hostname": install.hostname,
                            "armed_by": window.armed_by,
                        },
                    )
                else:
                    # The window was consumed by a racing connection (or the row vanished): fall back
                    # to a plain rejection and let the rebind roll back with the session.
                    install = None
                    session.rollback()
        # Read the id while the row is still bound to the session (#366). session.commit() below expires
        # every attribute (expire_on_commit), and leaving the `with` block detaches `install` - so a
        # later attribute access raises DetachedInstanceError. Because that access sat AFTER
        # websocket.accept(), the exception tore down every already-accepted relay socket, so no relay
        # could ever register (relayStatus stayed false).
        install_id = install.id if install is not None else None
        session.commit()
    if install_id is None:
        # Nothing matched the presented secret. Recorded because a drifted credential is otherwise
        # invisible from this side: the relay retries forever and nothing but a log line ever says so
        # (throttled inside relay_events).
        await relay_events.write(
            RelayEventKind.REFUSED_SECRET,
            install_id=None,
            reason="the presented secret matched no relay install",
        )
        await websocket.close(code=4401)
        return

    await websocket.accept()
    # POC scope: one relay at a time, incumbent wins (issue #202 #6). If a relay is already connected,
    # reject this one rather than superseding - superseding could drop an in-flight reply for a GP write
    # that committed, and two enrolled relays would otherwise thrash by force-closing each other.
    if not relay_gateway.try_register(websocket, install_id):
        await websocket.close(code=4409)
        return
    connected_at = datetime.utcnow()
    if adopted:
        await relay_events.write(
            RelayEventKind.ADOPTED,
            at=connected_at,
            install_id=install_id,
            # Null, not the gateway's list: the hello has not landed yet, so what this relay serves is
            # unknown at this instant rather than empty.
            companies=None,
            reason="an armed adopt window bound the presented secret to this install",
            detail={"armed_by": adopted_by},
        )
    # CONNECTED is written from a task rather than here so the hello frame - the relay's first, and the
    # only source of its build tag - has a moment to land. Nothing waits on it either way.
    connected_task = asyncio.create_task(_record_connected(websocket, install_id, connected_at))
    _connected_event_tasks.add(connected_task)
    connected_task.add_done_callback(_connected_event_tasks.discard)
    # A relay just came back: drain anything that queued while it was gone, now, rather than up to a
    # poll interval later (#353 PR E), and pick up any GP job created while it was away (#380).
    gp_outbox_worker.wake()
    gp_job_sync.wake()
    gp_po_sync.wake()
    try:
        await _serve_relay_link(websocket, require_hello=adopted)
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        # The connection is being torn down (server shutdown, or a test harness closing its portal) while
        # the background heartbeat task made the read loop's teardown yield. The relay is gone either way,
        # so treat it as a clean disconnect and let the handler end normally rather than error out.
        pass
    finally:
        relay_gateway.unregister(websocket)


@app.post("/admin/reset-data")
def reset_data(request: Request):
    """Drop and rebuild the entire public schema via alembic. Dev use only.

    Gated twice on purpose. This endpoint is total data loss on one unauthenticated POST, and it was
    previously reachable by anyone who knew the URL on a public Railway domain - no auth, no
    environment check. TESTING_ENABLED keeps it off any deployment that isn't a test target, and
    require_admin_request means it is not enough to merely reach the box.

    It also PRESERVES the tables that hold setup rather than project data - app/services/
    reset_preservation.py owns that list and the reasoning per table. relay_installs is the one that
    hurts most: dropping those rows silently orphans the on-prem relay, because its enrolled secret no
    longer matches any row, so /relay-link refuses every handshake and all GP writes fail until someone
    re-enrols on the workstation. A dev-convenience reset must not take GP down as a side effect.

    Projects are deliberately NOT preserved - they are re-adopted straight from GP by a forced sync
    pass right after the rebuild, since GP owns them."""
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.config import TESTING_ENABLED
    from app.database import engine
    from app.services import reset_preservation

    if not TESTING_ENABLED:
        return JSONResponse(status_code=403, content={"error": "Data reset is not enabled on this deployment"})

    try:
        require_admin_request(request)
    except AppError as e:
        status = 403 if e.code == "FORBIDDEN" else 401
        return JSONResponse(status_code=status, content={"error": str(e), "code": e.code})

    with engine.connect() as conn:
        snap = reset_preservation.snapshot(conn)

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    # Rebuild via alembic
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        preserved = reset_preservation.restore(conn, snap)
        conn.commit()

    # Re-adopt every GP job straight after the rebuild, since GP owns them. Skipped silently when no
    # relay is connected - see run_once_blocking - and the background poll re-adopts them later.
    sync_result = gp_job_sync.run_once_blocking()

    # The frontend alerts `message` verbatim, so it carries the summary; the fields below are for
    # anyone reading the response itself.
    parts = reset_preservation.describe_counts(preserved)
    message = "Schema dropped and rebuilt"
    if parts:
        message += f". Preserved {', '.join(parts)}"
    if sync_result:
        total, adopted = sync_result
        message += f". Re-adopted {adopted} of {total} GP {'job' if total == 1 else 'jobs'}"
    else:
        message += ". GP job sync did not run, so projects were not re-adopted"

    return {
        "status": "ok",
        "message": message,
        "preserved": preserved,
        "relay_installs_preserved": preserved.get("relay_installs", 0),
        # null, not 0, when no sync pass ran - "GP had no new jobs" and "GP was never asked" are
        # different answers.
        "jobs_adopted": sync_result[1] if sync_result else None,
    }


@app.get("/testing/clerk-sign-in")
def get_clerk_sign_in_token(request: Request, email: str = "jayp@ucsh.com"):
    """Create a Clerk sign-in token for E2E testing.

    Gated twice, like /admin/reset-data (#422). TESTING_ENABLED keeps it off any deployment that is
    not a test target, checked first so a production deployment refuses outright rather than leaking
    whether the caller's credential would have been good enough. Then the caller must prove they are
    already a UC Nexus Admin, or present the shared testing secret in X-Testing-Secret - the
    bootstrap path for a deployment where no session exists yet. Auth is not optional here: every
    environment shares the production Clerk instance, so what this mints is a real session for a real
    staff account, a UC Nexus Admin included, and with only the environment switch this route was a
    full impersonation primitive on any deployment where the switch was left on."""
    import hashlib
    import hmac

    import httpx

    from app.config import CLERK_SECRET_KEY, TESTING_ENABLED, testing_sign_in_secret_hash

    if not TESTING_ENABLED:
        return JSONResponse(status_code=403, content={"error": "Testing is not enabled"})

    expected_hash = testing_sign_in_secret_hash()
    presented = (request.headers.get("x-testing-secret") or "").strip()
    secret_ok = bool(expected_hash) and bool(presented)
    if secret_ok:
        digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
        secret_ok = hmac.compare_digest(digest, expected_hash.lower())
    if not secret_ok:
        try:
            require_admin_request(request)
        except AppError as e:
            status = 403 if e.code == "FORBIDDEN" else 401
            return JSONResponse(status_code=status, content={"error": str(e), "code": e.code})

    headers = {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}

    # Find user by email
    users_resp = httpx.get(
        "https://api.clerk.com/v1/users",
        headers=headers,
        params={"email_address": email},
    )
    users_resp.raise_for_status()
    users = users_resp.json()
    if not users:
        return JSONResponse(status_code=404, content={"error": f"No user found with email {email}"})

    user_id = users[0]["id"]

    # Create sign-in token
    token_resp = httpx.post(
        "https://api.clerk.com/v1/sign_in_tokens",
        headers=headers,
        json={"user_id": user_id},
    )
    token_resp.raise_for_status()
    data = token_resp.json()
    return {"token": data["token"], "url": data.get("url", ""), "user_id": user_id}
