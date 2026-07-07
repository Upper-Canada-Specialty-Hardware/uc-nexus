"""The uniform error-response shape (errors.error_body) every relay op reply uses:
{error, message, context}. No SQL, no GP."""

from ucnexus_relay.errors import error_body


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
