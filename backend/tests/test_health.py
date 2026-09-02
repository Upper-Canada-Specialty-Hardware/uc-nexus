from fastapi.testclient import TestClient

import main
from app.services.relay_gateway import RelayGateway
from main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "relay_connected": False,
        "relay_companies": [],
        # Null rather than absent: "no relay has ever dialled this backend" is a different answer from
        # "one did and was dropped", and a preview that comes up relay-dark is the case this is read in.
        "relay_last_connected_at": None,
        "relay_last_disconnected_at": None,
        "relay_last_disconnect_reason": None,
    }


def test_health_reports_the_live_relay(monkeypatch):
    """The one fact worth asking a backend for without a session: is GP reachable from here.

    Answered off the gateway's in-memory state, so it stays a constant-cost, database-free answer -
    which is the point of putting it on the probe endpoint rather than behind GraphQL."""
    gateway = RelayGateway()
    gateway.try_register(object())
    # The hello frame is what says which companies GP gave the relay.
    gateway.note_hello("relay-v0.3.0", ["list_vendors"], ["TUBC", "TUCSH"])
    monkeypatch.setattr(main, "relay_gateway", gateway)

    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["relay_connected"] is True
    assert body["relay_companies"] == ["TUBC", "TUCSH"]
    # Stamped by the registration, and an ISO string rather than a datetime - this is plain JSON that
    # something curls.
    assert body["relay_last_connected_at"] == gateway.last_connected_at.isoformat()
    assert body["relay_last_disconnected_at"] is None
    assert body["relay_last_disconnect_reason"] is None


def test_health_still_answers_after_the_relay_goes(monkeypatch):
    """The timestamps deliberately OUTLIVE the connection they describe: with nothing connected, when
    it went and why is the whole of what somebody wants from this endpoint."""
    gateway = RelayGateway()
    socket = object()
    gateway.try_register(socket)
    gateway.unregister(socket)
    monkeypatch.setattr(main, "relay_gateway", gateway)

    body = client.get("/health").json()
    assert body["relay_connected"] is False
    assert body["relay_last_connected_at"] == gateway.last_connected_at.isoformat()
    assert body["relay_last_disconnected_at"] == gateway.last_disconnected_at.isoformat()
    assert body["relay_last_disconnect_reason"] == gateway.last_disconnect_reason
