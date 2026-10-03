"""Start the backend under uvicorn, draining GP writes before uvicorn closes connections (#1292).

uvicorn's own shutdown closes every open connection - the relay's websocket among them - BEFORE it
runs the app's lifespan shutdown. A GP write on the wire at SIGTERM then lost its socket mid-call and
was marked FAILED ambiguous while GP may still have committed it. This server runs the app's drain
(stop claiming, wait for the write in flight, close the relay socket cleanly) first, then hands over to
uvicorn's normal shutdown. Everything else is plain uvicorn, with the same settings the command line
had."""

import os

import uvicorn

# Covers the app's own wait (main.OUTBOX_DRAIN_SECONDS, 35s) plus the requests still finishing after it.
# Railway's drainingSeconds (railway.toml) sits above this, so the platform does not SIGKILL mid-wait.
GRACEFUL_SHUTDOWN_SECONDS = 45


class DrainingServer(uvicorn.Server):
    async def shutdown(self, sockets=None) -> None:
        if not self.force_exit:  # a second Ctrl+C / SIGTERM means stop now
            from main import drain_before_shutdown

            try:
                await drain_before_shutdown()
            except Exception:  # noqa: BLE001 - never let the drain stop the server from shutting down
                import logging

                logging.getLogger("uvicorn.error").exception("drain before shutdown failed")
        await super().shutdown(sockets=sockets)


def main() -> None:
    config = uvicorn.Config(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    DrainingServer(config).run()


if __name__ == "__main__":
    main()
