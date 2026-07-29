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
    # gp_employees is admin-gated (#392): the payroll roster is not ordinary working data.
    monkeypatch.setattr(relay_module, "require_admin", lambda info: {"user_id": "test-admin", "roles": ["Admin"]})


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
        {"vendors": [{"vendor_id": "V1", "vendor_name": "Acme", "vendor_class": "HW", "status": 1, "currency": "USD"}]},
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
        {
            "tax_details": [
                {"tax_detail_id": "ON HST - P", "description": "ON HST on Purchases", "percent": 13.0},
                {"tax_detail_id": "PST 7%", "description": None, "percent": 7.0},
            ]
        },
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


def test_gp_buyers_detailed_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"buyers": [{"buyer_id": "donr", "description": "Don Roberton"}, {"buyer_id": "mira"}]},
    )

    async def run():
        return await Query().gp_buyers_detailed(FakeInfo(), company="TUBC")

    buyers = asyncio.run(run())
    assert [(b.buyer_id, b.description) for b in buyers] == [("donr", "Don Roberton"), ("mira", None)]
    # list_buyers_detailed, not list_buyers - the bare-id op still backs the Create PO dropdown
    assert fake.calls == [("TUBC", "list_buyers_detailed", None)]


def test_gp_buyers_detailed_requires_an_admin(monkeypatch):
    # gp_buyers (bare ids) stays require_user; the descriptions are a staff roster by another name.
    from app.auth import AuthError

    def _deny(info):
        raise AuthError("Admin role required")

    monkeypatch.setattr(relay_module, "require_admin", _deny)

    async def _never(*a, **k):
        raise AssertionError("the relay must not be called for a non-admin")

    monkeypatch.setattr(relay_module, "relay_gateway", type("G", (), {"relay_call": staticmethod(_never)})())

    async def run():
        return await Query().gp_buyers_detailed(FakeInfo(), company="TUBC")

    with pytest.raises(AuthError):
        asyncio.run(run())


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


# --- the create-job form's live reads (#380) ---


def test_gp_customers_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"customers": [{"customer_number": "ELL100", "customer_name": "Ellis Don"}, {"customer_number": "X1"}]},
    )

    async def run():
        return await Query().gp_customers(FakeInfo(), company="TUBC")

    customers = asyncio.run(run())
    assert [(c.customer_number, c.customer_name) for c in customers] == [("ELL100", "Ellis Don"), ("X1", None)]
    assert fake.calls == [("TUBC", "list_customers", None)]


def test_gp_customer_addresses_scopes_the_call_to_the_customer(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"addresses": [{"address_code": "MAIN", "address1": "1 Main St", "city": "Vancouver", "state": "BC"}]},
    )

    async def run():
        return await Query().gp_customer_addresses(FakeInfo(), company="TUBC", customer="ELL100")

    addresses = asyncio.run(run())
    assert addresses[0].address_code == "MAIN"
    assert addresses[0].city == "Vancouver"
    # the customer must ride on the payload - an address code is only valid under its own customer
    assert fake.calls == [("TUBC", "list_customer_addresses", {"customer": "ELL100"})]


def test_gp_tax_schedules_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"tax_schedules": [{"tax_schedule_id": "GST 5%", "description": "Federal GST 5%"}]},
    )

    async def run():
        return await Query().gp_tax_schedules(FakeInfo(), company="TUBC")

    schedules = asyncio.run(run())
    assert [(s.tax_schedule_id, s.description) for s in schedules] == [("GST 5%", "Federal GST 5%")]
    # list_tax_schedules (TX00101), not list_tax_details (TX00201) - different table, different thing
    assert fake.calls == [("TUBC", "list_tax_schedules", None)]


def test_gp_employees_maps_relay_result_to_type(monkeypatch):
    fake = _install_fake_gateway(
        monkeypatch,
        {"employees": [{"employee_id": "IANB", "first_name": "Ian", "last_name": "Brown"}]},
    )

    async def run():
        return await Query().gp_employees(FakeInfo(), company="TUBC")

    employees = asyncio.run(run())
    assert [(e.employee_id, e.first_name, e.last_name) for e in employees] == [("IANB", "Ian", "Brown")]
    assert fake.calls == [("TUBC", "list_employees", None)]


def test_gp_employees_requires_an_admin(monkeypatch):
    # Every other gp_* read is require_user; this one returns staff names, and its only consumer is
    # the admin-only create-job dialog.
    from app.auth import AuthError

    def _deny(info):
        raise AuthError("Admin role required")

    monkeypatch.setattr(relay_module, "require_admin", _deny)

    async def _never(*a, **k):
        raise AssertionError("the relay must not be called for a non-admin")

    monkeypatch.setattr(relay_module, "relay_gateway", type("G", (), {"relay_call": staticmethod(_never)})())

    async def run():
        return await Query().gp_employees(FakeInfo(), company="TUBC")

    with pytest.raises(AuthError):
        asyncio.run(run())


def test_gp_divisions_passes_through_the_relay_list(monkeypatch):
    fake = _install_fake_gateway(monkeypatch, {"divisions": ["VANCOUVER"]})

    async def run():
        return await Query().gp_divisions(FakeInfo(), company="TUBC")

    assert asyncio.run(run()) == ["VANCOUVER"]
    assert fake.calls == [("TUBC", "list_divisions", None)]
