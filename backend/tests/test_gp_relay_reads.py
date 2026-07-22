"""Query.gp_jobs/gp_vendors/gp_buyers/gp_cost_codes/relay_status: relay_call wiring + dict->type mapping.

Plain `def test_...(): asyncio.run(...)` (matches test_relay_gateway.py) - resolvers are exercised
directly against a Query instance with require_user monkeypatched out; Clerk auth itself needs no
coverage here (no resolver-level auth test exists anywhere in this codebase yet)."""

import asyncio

import pytest

from app.schemas import relay as relay_module
from app.schemas.queries import Query
from app.services.relay_gateway import RelayGateway


class FakeInfo:
    context = {"request": None}


@pytest.fixture(autouse=True)
def _bypass_require_user(monkeypatch):
    monkeypatch.setattr(relay_module, "require_user", lambda info: {"user_id": "test-user"})


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    async def relay_call(self, company, op, payload=None, timeout=None):
        self.calls.append((company, op, payload))
        return self.result


def _install_fake_gateway(monkeypatch, result):
    fake = FakeGateway(result)
    monkeypatch.setattr(relay_module, "relay_gateway", fake)
    return fake


def test_gp_jobs_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"jobs": [{"job_number": "1001", "job_name": "Test Job"}, {"job_number": "1002", "job_name": None}]},
    )

    async def run():
        return await Query().gp_jobs(FakeInfo(), company="TUBC")

    jobs = asyncio.run(run())
    assert [(j.job_number, j.job_name) for j in jobs] == [("1001", "Test Job"), ("1002", None)]
    assert fake.calls == [("TUBC", "list_jobs", None)]


def test_gp_vendors_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"vendors": [
            {"vendor_id": "V1", "vendor_name": "Acme", "vendor_class": "HW", "status": 1, "currency": "USD"}
        ]},
    )

    async def run():
        return await Query().gp_vendors(FakeInfo(), company="TUBC")

    vendors = asyncio.run(run())
    assert len(vendors) == 1
    assert vendors[0].vendor_id == "V1"
    assert vendors[0].vendor_name == "Acme"
    assert vendors[0].vendor_class == "HW"
    assert vendors[0].status == 1
    assert vendors[0].currency == "USD"  # issue #257: vendor dictates PO currency
    assert fake.calls == [("TUBC", "list_vendors", None)]


def test_gp_vendors_currency_defaults_to_cad_for_older_relay(monkeypatch):
    # a relay predating the currency field (issue #257) omits it -> default CAD, dropdown still works
    _install_fake_gateway(
        monkeypatch,
        {"vendors": [{"vendor_id": "V1", "vendor_name": "Acme", "vendor_class": None, "status": 1}]},
    )

    async def run():
        return await Query().gp_vendors(FakeInfo(), company="TUBC")

    assert asyncio.run(run())[0].currency == "CAD"


def test_gp_tax_details_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"tax_details": [
            {"tax_detail_id": "ON HST - P", "description": "ON HST on Purchases", "percent": 13.0},
            {"tax_detail_id": "PST 7%", "description": None, "percent": 7.0},
        ]},
    )

    async def run():
        return await Query().gp_tax_details(FakeInfo(), company="TUBC")

    details = asyncio.run(run())
    assert [(d.tax_detail_id, d.description, d.percent) for d in details] == [
        ("ON HST - P", "ON HST on Purchases", 13.0),
        ("PST 7%", None, 7.0),
    ]
    assert fake.calls == [("TUBC", "list_tax_details", None)]


def test_gp_buyers_returns_relay_result_directly(monkeypatch):
    fake = _install_fake_gateway(monkeypatch, {"buyers": ["JSMITH", "TJONES"]})

    async def run():
        return await Query().gp_buyers(FakeInfo(), company="TUBC")

    buyers = asyncio.run(run())
    assert buyers == ["JSMITH", "TJONES"]
    assert fake.calls == [("TUBC", "list_buyers", None)]


def test_gp_cost_codes_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"cost_codes": [{"cost_code": "310-000", "description": "Materials", "cost_element": 3}]},
    )

    async def run():
        return await Query().gp_cost_codes(FakeInfo(), company="TUBC", job="1001")

    codes = asyncio.run(run())
    assert len(codes) == 1
    assert codes[0].cost_code == "310-000"
    assert codes[0].description == "Materials"
    assert codes[0].cost_element == 3
    assert fake.calls == [("TUBC", "list_cost_codes", {"job": "1001"})]


def test_relay_status_resolver_reads_gateway_connected(monkeypatch):
    gateway = RelayGateway()
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)
    assert Query().relay_status(FakeInfo()).connected is False
