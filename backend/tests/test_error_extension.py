"""ResolverGuardExtension error mapping: a RelayCallError's detail (the relay's eConnect proc / error_state /
description) must survive into the GraphQL error extensions so the frontend can show the full GP
failure to the end user (issue #187), not just the generic RELAY_CALL_FAILED code."""

from app.errors import RelayCallError, ValidationError
from main import ResolverGuardExtension


def test_relay_call_error_detail_surfaces_under_relay_error():
    detail = {
        "error": "econnect_error",
        "message": "Duplicate Order",
        "context": {"proc": "taPoLine", "error_state": 9127, "error_description": "Duplicate Order"},
    }
    err = ResolverGuardExtension._to_graphql_error(RelayCallError("Duplicate Order", detail=detail))
    assert err.message == "Duplicate Order"
    assert err.extensions["code"] == "RELAY_CALL_FAILED"
    assert err.extensions["relayError"] == detail
    assert err.extensions["relayError"]["context"]["error_state"] == 9127


def test_relay_call_error_with_empty_detail_omits_relay_error():
    err = ResolverGuardExtension._to_graphql_error(RelayCallError("something failed"))
    assert err.extensions["code"] == "RELAY_CALL_FAILED"
    assert "relayError" not in err.extensions


def test_plain_app_error_is_unchanged():
    err = ResolverGuardExtension._to_graphql_error(ValidationError("bad thing", field="vendor"))
    assert err.message == "bad thing"
    assert err.extensions["code"] == "VALIDATION_ERROR"
    assert err.extensions["field"] == "vendor"
    assert "relayError" not in err.extensions
