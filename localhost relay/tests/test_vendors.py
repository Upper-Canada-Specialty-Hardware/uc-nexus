"""Auth gate for /vendors. The 401 short-circuits before any SQL, so this never touches GP."""

from fastapi.testclient import TestClient

from ucnexus_relay.main import create_app

client = TestClient(create_app())


def test_vendors_requires_token():
    assert client.get("/vendors").status_code == 401


def test_vendors_rejects_bad_token():
    assert client.get("/vendors", headers={"Authorization": "Bearer wrong"}).status_code == 401
