"""Channel op dispatch: {op, company, payload} -> {ok, result|error}. Fakes db.get_read_connection /
db.get_connection and the econnect calls they wrap - no real SQL, matching the rest of this suite's
convention of never touching GP from a test."""

from contextlib import contextmanager

import pytest

from ucnexus_relay import channel, db, econnect, ops


class _FakeConn:
    def cursor(self):
        raise AssertionError("test should stub the econnect call directly, not hit a real cursor")

    def commit(self):
        pass

    def rollback(self):
        pass


@contextmanager
def _fake_read_connection(company):
    yield _FakeConn()


@contextmanager
def _fake_connection(company):
    yield _FakeConn()


@pytest.fixture(autouse=True)
def _no_real_sql(monkeypatch):
    monkeypatch.setattr(db, "get_read_connection", _fake_read_connection)
    monkeypatch.setattr(db, "get_connection", _fake_connection)


def test_list_vendors_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [{"vendor_id": "V1"}])
    reply = channel._dispatch("list_vendors", "TUBC", {})
    assert reply == {"ok": True, "result": {"company": "TUBC", "vendors": [{"vendor_id": "V1"}]}}


def test_list_buyers_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["mira", "donr"])
    reply = channel._dispatch("list_buyers", "TUBC", {})
    assert reply == {"ok": True, "result": {"company": "TUBC", "buyers": ["mira", "donr"]}}


def test_list_cost_codes_requires_job():
    reply = channel._dispatch("list_cost_codes", "TUBC", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_job"


def test_list_cost_codes_routes_to_econnect_and_strips_job(monkeypatch):
    seen = {}

    def _fake(conn, job):
        seen["job"] = job
        return [{"cost_code": "210-200"}]

    monkeypatch.setattr(econnect, "list_cost_codes", _fake)
    reply = channel._dispatch("list_cost_codes", "TUBC", {"job": " 80003 "})
    assert seen["job"] == "80003"
    assert reply == {
        "ok": True,
        "result": {"company": "TUBC", "job": "80003", "cost_codes": [{"cost_code": "210-200"}]},
    }


def test_list_jobs_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [{"job_number": "80003", "job_name": "Test"}])
    reply = channel._dispatch("list_jobs", "TUBC", {})
    assert reply == {
        "ok": True,
        "result": {"company": "TUBC", "jobs": [{"job_number": "80003", "job_name": "Test"}]},
    }


def test_unknown_op_returns_a_clean_error():
    reply = channel._dispatch("not_a_real_op", "TUBC", {})
    assert reply == {"ok": False, "error": {"error": "unknown_op", "message": "unknown op 'not_a_real_op'", "context": {}}}


def test_missing_company_returns_a_clean_error():
    reply = channel._dispatch("list_vendors", "", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_company"


def test_company_not_allowed_returns_a_clean_error():
    reply = channel._dispatch("list_vendors", "NOT-A-SANDBOX", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed"


_PO_PAYLOAD = {
    "header": {"vendor_id": "ING100", "confirm_with": "mira", "doc_date": "2026-01-01"},
    "lines": [{"item_number": "I1", "item_description": "d", "quantity": 1, "unit_cost": 1}],
}

_RECEIPT_PAYLOAD = {
    "po_number": "PO0000001",
    "lines": [{"po_line_ord": 16384, "quantity": 1, "rack_location": "A1"}],
}


def test_create_po_relay_op_error_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise ops.RelayOpError("buyer_unresolved", "no buyer")

    monkeypatch.setattr(ops, "create_po_op", _raise)
    reply = channel._dispatch("create_po", "TUBC", _PO_PAYLOAD)
    assert reply == {"ok": False, "error": {"error": "buyer_unresolved", "message": "no buyer", "context": {}}}


def test_create_po_success_returns_the_response_body(monkeypatch):
    from datetime import date
    from decimal import Decimal

    from ucnexus_relay.models import CreatePoResponse

    def _fake(conn, *, company, request):
        return CreatePoResponse(
            po_number="PO0000001", company=company, lines_created=1, subtotal=Decimal("1"), doc_date=date(2026, 1, 1),
            vendor_id="ING100",
        )

    monkeypatch.setattr(ops, "create_po_op", _fake)
    reply = channel._dispatch("create_po", "TUBC", _PO_PAYLOAD)
    assert reply["ok"] is True
    assert reply["result"]["po_number"] == "PO0000001"


def test_create_receipt_econnect_error_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise econnect.EConnectError("boom", proc="taPopRcptHdrInsert", error_state=0)

    monkeypatch.setattr(ops, "create_receipt_op", _raise)
    reply = channel._dispatch("create_receipt", "TUBC", _RECEIPT_PAYLOAD)
    assert reply["ok"] is False
    assert reply["error"]["error"] == "econnect_error"


def test_create_receipt_invalid_payload_translates_cleanly():
    reply = channel._dispatch("create_receipt", "TUBC", {"po_number": "PO1"})  # missing required lines
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"
