from fastapi.testclient import TestClient

import main
from app.services.relay_gateway import RelayGateway
from main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "relay_connected": False, "relay_companies": []}


def test_health_reports_the_live_relay(monkeypatch):
    """The one fact worth asking a backend for without a session: is GP reachable from here.

    Answered off the gateway's in-memory state, so it stays a constant-cost, database-free answer -
    which is the point of putting it on the probe endpoint rather than behind GraphQL."""
    gateway = RelayGateway()
    gateway.try_register(["TUBC", "TUCSH"], object())
    monkeypatch.setattr(main, "relay_gateway", gateway)

    body = client.get("/health").json()
    assert body == {"status": "ok", "relay_connected": True, "relay_companies": ["TUBC", "TUCSH"]}
