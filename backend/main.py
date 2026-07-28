import asyncio
import contextlib
import inspect
import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

import strawberry
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from graphql import GraphQLError, GraphQLResolveInfo
from strawberry.extensions import SchemaExtension
from strawberry.fastapi import GraphQLRouter

from app.auth import get_context, require_admin_request
from app.database import SessionLocal
from app.errors import AppError
from app.repositories import relay_repository
from app.schemas.mutations import Mutation
from app.schemas.queries import Query
from app.services import gp_job_sync, gp_outbox_worker, relay_adopt
from app.services.relay_gateway import HEARTBEAT_INTERVAL_SECONDS
from app.services.relay_gateway import gateway as relay_gateway

logger = logging.getLogger(__name__)

# An adopted socket has to prove it is a relay before it is trusted with the connection slot: a
# legitimate relay always sends {"type": "hello"} as its first frame (channel.py `_run_once` sends it
# before entering the read loop), so a short wait for one costs a real relay nothing.
ADOPT_HELLO_TIMEOUT_SECONDS = 5.0


class ErrorHandlerExtension(SchemaExtension):
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

    def resolve(self, _next: Callable, root: Any, info: GraphQLResolveInfo, *args, **kwargs):
        # For async resolvers _next() returns a coroutine that strawberry awaits *after* this method
        # returns, so a synchronous try/except here would never see the exception - the AppError -> code
        # mapping would be silently dropped. Handle the awaitable case in an async wrapper so both sync
        # and async resolvers get the extension pattern.
        try:
            result = _next(root, info, *args, **kwargs)
        except (AppError, NotImplementedError) as e:
            raise self._to_graphql_error(e) from e
        if inspect.isawaitable(result):
            return self._resolve_async(result)
        return result

    async def _resolve_async(self, awaitable):
        try:
            return await awaitable
        except (AppError, NotImplementedError) as e:
            raise self._to_graphql_error(e) from e


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[ErrorHandlerExtension],
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
def health():
    return {"status": "ok"}


async def _relay_read_loop(websocket: WebSocket) -> None:
    """Feed each frame the relay sends to relay_gateway: a {"type": "hello"} advertises the relay's build
    and op-set on connect (issue #315), a {"type": "pong"} answers the heartbeat (issue #277), anything
    else is a {id, ok, result|error} job reply to correlate with relay_call()."""
    while True:
        message = await websocket.receive_json()
        if isinstance(message, dict) and message.get("type") == "hello":
            relay_gateway.note_hello(message.get("build"), message.get("ops"))
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
    relay_gateway.note_hello(message.get("build"), message.get("ops"))
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
        # Read the company while the row is still bound to the session. session.commit() below expires
        # every attribute (expire_on_commit), and leaving the `with` block detaches `install` - so any
        # later install.company access raises DetachedInstanceError. Because that access sat AFTER
        # websocket.accept(), the exception tore down every already-accepted relay socket, so no relay
        # could ever register (relayStatus stayed false).
        company = install.company if install is not None else None
        # Same rule for the id (#366): read it here, beside company, while the row is still attached.
        install_id = install.id if install is not None else None
        session.commit()
    if company is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    # POC scope: one relay at a time, incumbent wins (issue #202 #6). If a relay is already connected,
    # reject this one rather than superseding - superseding could drop an in-flight reply for a GP write
    # that committed, and two enrolled relays would otherwise thrash by force-closing each other.
    if not relay_gateway.try_register(company, websocket, install_id):
        await websocket.close(code=4409)
        return
    # A relay just came back: drain anything that queued while it was gone, now, rather than up to a
    # poll interval later (#353 PR E), and pick up any GP job created while it was away (#380).
    gp_outbox_worker.wake()
    gp_job_sync.wake()
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

    It also PRESERVES relay_installs across the rebuild. Dropping those rows silently orphans the
    on-prem relay: its enrolled secret no longer matches any row, so /relay-link refuses every
    handshake and all GP writes fail until someone re-enrols on the workstation. A dev-convenience
    reset must not take GP down as a side effect."""
    from alembic.config import Config
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from alembic import command
    from app.config import TESTING_ENABLED
    from app.database import engine

    if not TESTING_ENABLED:
        return JSONResponse(status_code=403, content={"error": "Data reset is not enabled on this deployment"})

    try:
        require_admin_request(request)
    except AppError as e:
        status = 403 if e.code == "FORBIDDEN" else 401
        return JSONResponse(status_code=status, content={"error": str(e), "code": e.code})

    # Snapshot the relay enrolments before the schema goes. Read as plain mappings: the ORM model is
    # about to have its table dropped and recreated, so nothing here may hold a live identity-mapped
    # instance. The table is absent on a fresh or half-migrated database, which must not block a reset -
    # that is exactly the state a reset exists to clear.
    relay_rows: list[dict] = []
    with engine.connect() as conn:
        if sa_inspect(conn).has_table("relay_installs"):
            relay_rows = [
                dict(r)
                for r in conn.execute(
                    text(
                        "SELECT id, label, company, hostname, secret_hash, secret_encrypted, "
                        "enrollment_token_hash, enrollment_token_expires_at, enrolled_at, last_seen_at, "
                        "created_at, adopted_at, adopted_by FROM relay_installs"
                    )
                ).mappings()
            ]

    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    # Rebuild via alembic
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    with engine.connect() as conn:
        for row in relay_rows:
            conn.execute(
                text(
                    "INSERT INTO relay_installs (id, label, company, hostname, secret_hash, "
                    "secret_encrypted, enrollment_token_hash, enrollment_token_expires_at, enrolled_at, "
                    "last_seen_at, created_at, adopted_at, adopted_by) VALUES (:id, :label, :company, "
                    ":hostname, :secret_hash, :secret_encrypted, :enrollment_token_hash, "
                    ":enrollment_token_expires_at, :enrolled_at, :last_seen_at, :created_at, "
                    ":adopted_at, :adopted_by)"
                ),
                row,
            )
        conn.commit()

    return {
        "status": "ok",
        "message": "Schema dropped and rebuilt",
        "relay_installs_preserved": len(relay_rows),
    }


@app.get("/testing/clerk-sign-in")
def get_clerk_sign_in_token(email: str = "jayp@ucsh.com"):
    """Create a Clerk sign-in token for E2E testing. Only available when TESTING_ENABLED=true."""
    import httpx

    from app.config import CLERK_SECRET_KEY, TESTING_ENABLED

    if not TESTING_ENABLED:
        return JSONResponse(status_code=403, content={"error": "Testing is not enabled"})

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
