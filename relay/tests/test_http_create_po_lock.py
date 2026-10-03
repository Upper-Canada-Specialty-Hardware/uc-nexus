"""The local HTTP /po create holds the same per-company lock as the channel create (#1214).

The create_po idempotency lookup only sees a committed PO, so the lock is what stops two attempts with one
key from both missing it and each reserving a number. The channel path always held it; the HTTP handler
called create_po_op bare. These tests stub GP out entirely: no SQL connection is ever opened."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from ucnexus_relay import auth, channel, db, models, ops
from ucnexus_relay.main import create_app


class _FakeConn:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _body() -> dict:
    return {
        "company": "TUBC",
        "header": {
            "vendor_id": "ING100",
            "buyer_id": "mira",
            "confirm_with": "mira",
            "doc_date": "2026-09-16",
            "site": "VANCOUVER",
        },
        "lines": [{"item_number": "ML2010", "item_description": "ML2010 LOCK", "quantity": "2", "unit_cost": "12.50"}],
    }


def _client(monkeypatch, create_po_op) -> TestClient:
    monkeypatch.setattr(ops, "check_company_served", lambda company: None)
    monkeypatch.setattr(db, "get_connection", lambda company: _FakeConn())
    monkeypatch.setattr(ops, "create_po_op", create_po_op)
    app = create_app()
    app.dependency_overrides[auth.verify_token] = lambda: None
    return TestClient(app)


def test_http_po_create_runs_under_the_company_create_lock(monkeypatch):
    seen = {}

    def _fake(conn, *, company, request):
        seen["locked"] = channel._create_po_lock(company).locked()
        return models.CreatePoResponse(
            po_number="PO-1",
            company=company,
            lines_created=1,
            subtotal=Decimal("25.00"),
            doc_date=date(2026, 9, 16),
            vendor_id="ING100",
        )

    r = _client(monkeypatch, _fake).post("/po", json=_body())

    assert r.status_code == 201
    assert seen["locked"] is True
    assert channel._create_po_lock("TUBC").locked() is False  # released once the create is done


def test_http_po_create_releases_the_lock_when_the_create_fails(monkeypatch):
    def _boom(conn, *, company, request):
        raise ops.RelayOpError("bad_po", "refused")

    r = _client(monkeypatch, _boom).post("/po", json=_body())

    assert r.status_code == 400
    assert channel._create_po_lock("TUBC").locked() is False
