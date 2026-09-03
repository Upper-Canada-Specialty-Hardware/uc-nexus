from fastapi.testclient import TestClient

from ucnexus_relay import companies
from ucnexus_relay.main import create_app

client = TestClient(create_app())


def test_health_ok():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert "uptime_seconds" in body


def test_health_says_which_companies_this_login_could_not_read(monkeypatch):
    """A company missing from the list would otherwise look like a company GP does not hold, and
    nobody would go looking for the missing grant."""
    found = companies.Discovery(
        ["TUBC"], {"TUBC": "Test Upper Canada"}, None, {"KEYMA": "login denied (28000)"}
    )
    monkeypatch.setattr(companies, "current", lambda: found)
    body = client.get("/health").json()
    assert body["companies"] == [{"id": "TUBC", "name": "Test Upper Canada"}]
    assert body["companies_inaccessible"] == {"KEYMA": "login denied (28000)"}
    assert body["companies_error"] is None  # the reading worked; the login is what is short
