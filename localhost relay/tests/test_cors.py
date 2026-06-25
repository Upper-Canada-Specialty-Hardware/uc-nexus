"""CORS preflight + the legacy PNA header echo. These exercise the browser-hop preflight path
(the genuinely-new piece for the cloud frontend -> loopback relay call). No SQL, no auth body."""

from fastapi.testclient import TestClient

from ucnexus_relay.config import get_settings
from ucnexus_relay.main import create_app

client = TestClient(create_app())
ORIGIN = get_settings().cors.allowed_origins[0]  # a configured UC Nexus origin (e.g. the Railway page)


def test_preflight_allows_configured_origin():
    r = client.options(
        "/po",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert "POST" in r.headers.get("access-control-allow-methods", "")


def test_preflight_echoes_pna_header_when_requested():
    r = client.options(
        "/po",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.headers.get("Access-Control-Allow-Private-Network") == "true"


def test_no_pna_header_when_not_requested():
    r = client.options(
        "/po",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("Access-Control-Allow-Private-Network") is None
