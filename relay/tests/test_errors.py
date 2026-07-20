"""The uniform error-response shape (errors.error_body) every relay endpoint raises:
{error, message, context}. The TestClient case proves the envelope reaches the wire on the 401
path, which short-circuits before any SQL so it never touches GP."""

from fastapi.testclient import TestClient

from ucnexus_relay.errors import error_body
from ucnexus_relay.main import create_app

client = TestClient(create_app())


def test_error_body_has_three_keys_with_empty_context_by_default():
    assert error_body("job_not_registered", "job '80003' is not a registered GP job") == {
        "error": "job_not_registered",
        "message": "job '80003' is not a registered GP job",
        "context": {},
    }


def test_error_body_carries_structured_context():
    assert error_body("econnect_error", "taPoHdr failed", proc="taPoHdr", error_state=269) == {
        "error": "econnect_error",
        "message": "taPoHdr failed",
        "context": {"proc": "taPoHdr", "error_state": 269},
    }


def test_unauthorized_uses_the_uniform_envelope_on_the_wire():
    r = client.get("/info")
    assert r.status_code == 401
    assert r.json()["detail"] == {
        "error": "unauthorized",
        "message": "missing or invalid bearer token",
        "context": {},
    }
