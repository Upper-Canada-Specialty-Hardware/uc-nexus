"""The uniform error-response shape (errors.error_body) every relay endpoint raises:
{error, message, context}. The TestClient case proves the envelope reaches the wire on the 401
path, which short-circuits before any SQL so it never touches GP."""

from collections import namedtuple

import pytest
from fastapi.testclient import TestClient

from ucnexus_relay import econnect
from ucnexus_relay.errors import econnect_error_body, error_body
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


class _WennSoftRefusal:
    """A connection whose one statement is the WennSoft PO integration answering a refusal, and whose
    taErrorCode lookup answers an unrelated GP description for the same number."""

    def __init__(self):
        self._sql = ""

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self._sql = sql
        return self

    def fetchone(self):
        if "taErrorCode" in self._sql:
            return namedtuple("_Desc", "ErrorDesc")("An unrelated GP description   ")
        return namedtuple("_ExecRow", "error_state err_string")(7, "Cost code is inactive for this job   ")


def test_a_wennsoft_po_integration_refusal_says_its_own_text():
    # #1862: the proc numbers its states independently of taErrorCode, so its own text is the message.
    conn = _WennSoftRefusal()
    with pytest.raises(econnect.EConnectError) as excinfo:
        econnect.apply_wennsoft_integration(
            conn, po_number="PO1", line_ord=16384, product_indicator=2, job_number="22004", cost_code="210-200-2"
        )
    assert excinfo.value.proc_message == "Cost code is inactive for this job"

    body = econnect_error_body(conn, excinfo.value)
    assert body["message"] == "Cost code is inactive for this job"
    assert body["context"]["error_description"] == "An unrelated GP description"
    assert body["context"]["proc"] == "wsiWSCreateUpdatePurchaseOrderIntegration"


def test_unauthorized_uses_the_uniform_envelope_on_the_wire():
    r = client.get("/info")
    assert r.status_code == 401
    assert r.json()["detail"] == {
        "error": "unauthorized",
        "message": "missing or invalid bearer token",
        "context": {},
    }
