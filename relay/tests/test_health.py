import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import channel, companies
from ucnexus_relay.config import PRODUCTION_BACKEND_URL
from ucnexus_relay.main import create_app

client = TestClient(create_app())


@pytest.fixture
def _empty_traffic_record():
    """Both NEXUS GP TRAFFIC blocks are module-level in channel.py and run from process start, so they
    have to be emptied around a test that asserts what a fresh relay publishes."""
    saved = dict(channel._GP_SYNC_STATE)
    channel._GP_SYNC_STATE.clear()
    channel.reset_traffic()
    yield
    channel.reset_traffic()
    channel._GP_SYNC_STATE.clear()
    channel._GP_SYNC_STATE.update(saved)


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


def test_health_carries_the_relay_traffic_record(_empty_traffic_record):
    """The relay half of NEXUS GP TRAFFIC: what this relay is running now, what it has run, and the
    totals since it started. The desktop window's tab reads all of it from here."""
    body = client.get("/health").json()
    assert set(body["traffic"]) == {"since", "running", "recent", "totals"}
    assert body["traffic"]["running"] == []
    assert body["traffic"]["recent"] == []
    assert body["traffic"]["since"].endswith("Z")


def test_health_reports_no_gp_sync_state_until_the_backend_pushes_one(_empty_traffic_record):
    """Null rather than an empty object: the window tells "the backend has not sent it yet" from "the
    backend says nothing is happening", and only one of those is worth saying on the tab."""
    assert client.get("/health").json()["gp_sync_state"] is None

    channel._handle_gp_sync_state_frame(
        {"type": "gp_sync_state", "po_sync_enabled": True, "companies": [{"company": "UBC"}]},
        PRODUCTION_BACKEND_URL,
    )

    published = client.get("/health").json()["gp_sync_state"]
    assert published["url"] == PRODUCTION_BACKEND_URL
    assert published["state"]["companies"] == [{"company": "UBC"}]


def test_health_still_reports_the_jobs_in_flight_counter(_empty_traffic_record):
    """The update poller refuses to swap the exe out from under an in-flight GP write by reading this,
    and it is the one thing the new traffic record must not have displaced."""
    assert client.get("/health").json()["channel"]["jobs_in_flight"] == channel._INFLIGHT
