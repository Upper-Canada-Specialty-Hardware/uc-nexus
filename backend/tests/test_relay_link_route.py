"""Regression coverage for the /relay-link WebSocket handshake - the relay's outbound channel connect
path, which the PR that introduced it did not exercise in CI ("channel connect path not exercised").

The route authenticated the relay's secret inside a `with SessionLocal()` block that ran
session.commit() and then closed, which expired + detached the RelayInstall. Reading install.company
afterwards (right after websocket.accept()) raised DetachedInstanceError, tearing down every accepted
relay socket, so no relay ever registered and relayStatus stayed false. These tests drive the real
route so that failure mode can't come back unnoticed.
"""

import os
import time

from cryptography.fernet import Fernet

# The crypto layer reads RELAY_SECRET_ENC_KEY at call time; provide one before enroll/authenticate.
os.environ.setdefault("RELAY_SECRET_ENC_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.relay_install import RelayInstall  # noqa: E402
from app.repositories import relay_repository  # noqa: E402
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
            with client.websocket_connect("/relay-link", headers={"Authorization": f"Bearer {secret}"}):
                _wait_until(lambda: gateway.connected)
                assert gateway.connected is True
                assert gateway.company == "TUBC"
            # Leaving the context closes the socket; the route's finally unregisters it.
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
