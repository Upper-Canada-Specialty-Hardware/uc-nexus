"""Auth tests. These all assert 401 paths that short-circuit BEFORE any SQL is touched,
so the suite never hits GP."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import auth
from ucnexus_relay.config import PLACEHOLDER_SECRET
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


def _configured(monkeypatch, secret: str) -> None:
    monkeypatch.setattr(auth, "get_settings", lambda: SimpleNamespace(auth=SimpleNamespace(shared_secret=secret)))


@pytest.mark.parametrize("secret", ["", PLACEHOLDER_SECRET])
def test_an_unenrolled_relay_authorizes_nothing(monkeypatch, secret):
    # #1930: the placeholder is in every unenrolled relay's config and in the public example, and an
    # empty secret matched an empty bearer token - either way the local PO and receipt endpoints opened.
    _configured(monkeypatch, secret)
    for token in (secret, PLACEHOLDER_SECRET, ""):
        assert client.get("/info", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        assert client.post("/po", json={}, headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_an_enrolled_secret_still_authorizes(monkeypatch):
    _configured(monkeypatch, "an-enrolled-secret")
    assert auth.verify_token("Bearer an-enrolled-secret") is None
