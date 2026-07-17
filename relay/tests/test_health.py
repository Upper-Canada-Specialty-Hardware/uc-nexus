from fastapi.testclient import TestClient

from ucnexus_relay.main import create_app

client = TestClient(create_app())


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert "uptime_seconds" in body
