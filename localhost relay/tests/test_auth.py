"""Auth tests. These all assert 401 paths that short-circuit BEFORE any SQL is touched,
so the suite never hits GP."""

from fastapi.testclient import TestClient

from ucnexus_relay.main import create_app

client = TestClient(create_app())


def test_info_requires_token():
    assert client.get("/info").status_code == 401


def test_info_rejects_bad_token():
    assert client.get("/info", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_next_number_requires_token():
    assert client.post("/po/next-number", json={"company": "TUBC"}).status_code == 401


def test_create_po_requires_token():
    assert client.post("/po", json={"company": "TUBC", "header": {}, "lines": []}).status_code == 401
