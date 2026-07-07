"""FastAPI app for the UC Nexus relay.

Endpoints:
  GET /health — liveness, no auth, local diagnostics only

There is no other inbound HTTP surface: GP work (vendors, buyers, cost codes, jobs, PO create,
receiving) is serviced entirely off the outbound WebSocket channel to the backend (see channel.py).
No browser ever hits this relay.
"""

import time

import pyodbc
from fastapi import FastAPI

from . import db
from .config import get_settings
from .logging_setup import configure_logging, get_logger

VERSION = "0.1.0"
_START = time.monotonic()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.logging.level, settings.logging.file)
    logger = get_logger()

    app = FastAPI(title="UC Nexus Relay", version=VERSION)

    if not db.driver_available():
        logger.warning(
            "configured ODBC driver not found", extra={"driver": settings.sql.driver, "available": pyodbc.drivers()}
        )

    @app.middleware("http")
    async def log_requests(request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        dur = (time.perf_counter() - start) * 1000
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(dur, 1),
            },
        )
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "version": VERSION, "uptime_seconds": round(time.monotonic() - _START, 1)}

    return app


app = create_app()
