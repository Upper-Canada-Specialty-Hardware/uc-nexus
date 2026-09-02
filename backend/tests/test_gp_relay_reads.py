"""Query.gp_jobs/gp_vendors/gp_buyers/gp_cost_codes/relay_status: relay_call wiring + dict->type mapping.

Plain `def test_...(): asyncio.run(...)` (matches test_relay_gateway.py) - resolvers are exercised
directly against a Query instance. Since #423 that needs no auth setup at all: the gate is a schema
extension in front of the resolver, not a line inside it, so calling the body directly never touches
Clerk. What each gp_* read REQUIRES is asserted against the policy table instead, below.
"""

import asyncio
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.auth import ADMIN_ROLE
from app.auth_policy import ROOT_FIELD_POLICY, SIGNED_IN
from app.errors import RelayUnavailableError, ValidationError
from app.schemas import relay as relay_module
from app.schemas.enums import RelayEventKind
from app.schemas.queries import Query
from app.services import preview_registry
from app.services.relay_gateway import RelayGateway


class FakeInfo:
    # An ADMIN caller, seeded into the per-request role memo so `tenant_scope` (#637) answers None -
    # unscoped - without trying to verify a JWT off a request that is not there.
    context = {"request": None, "_auth_roles": [ADMIN_ROLE]}


class FakeGateway:
    def __init__(self, result, companies=("TUBC",), company_names=None, companies_error=None):
        self.result = result
        self.companies = list(companies)
        self.company_names = dict(company_names or {})
        self.companies_error = companies_error
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


def test_gp_buyers_detailed_requires_an_admin():
    """The bare-id `gpBuyers` backs the Create PO dropdown and stays open to any signed-in user; the
    descriptions turn the same list into a staff roster, so that one is admin. Asserted against the
    policy table because that is what decides it now - `test_resolver_auth_gates.py` covers that the
    extension actually enforces the table."""
    assert ROOT_FIELD_POLICY["gpBuyersDetailed"] == ADMIN_ROLE
    assert ROOT_FIELD_POLICY["gpBuyers"] == SIGNED_IN


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


def test_gp_cost_code_master_scopes_the_call_to_the_division(monkeypatch):
    """The master is read per division because the division is what decides whether a code is usable:
    the GL account comes from JC40302's (division, cost element) mapping, so the same code number is
    provisionable under one division and not another."""
    fake = _install_fake_gateway(
        monkeypatch,
        {
            "company": "TUBC",
            "division": "VANCOUVER",
            "cost_codes": [
                {
                    "cost_code": "210-200",
                    "alias": "210-200-2",
                    "description": "Supply Hardware",
                    "cost_element": 2,
                    "profit_type_number": 2,
                    "type_of_transaction": 1,
                    "account_index": 96,
                    "mapped": True,
                },
                {
                    "cost_code": "310-000",
                    "alias": "310-000-3",
                    "description": None,
                    "cost_element": 3,
                    "profit_type_number": 2,
                    "type_of_transaction": 1,
                    "account_index": 0,
                    "mapped": False,
                },
            ],
        },
    )

    async def run():
        return await Query().gp_cost_code_master(FakeInfo(), company="TUBC", division="VANCOUVER")

    codes = asyncio.run(run())
    # mapped=False survives rather than being filtered out - the picker disables it, and a code that
    # simply vanished would send the user hunting for one they can see in GP (#448)
    assert [(c.cost_code, c.description, c.cost_element, c.mapped) for c in codes] == [
        ("210-200", "Supply Hardware", 2, True),
        ("310-000", None, 3, False),
    ]
    # list_cost_code_master (JC40202, the catalogue), not list_cost_codes (JC00701, one job's rows)
    assert fake.calls == [("TUBC", "list_cost_code_master", {"division": "VANCOUVER"})]


def test_gp_cost_code_master_requires_an_admin():
    """Its only consumer is the admin-only create-job dialog, so it sits at the bar the createGpJob it
    feeds already sets. `gpCostCodes` - the per-job read behind the register-PO dropdown - stays open
    to any signed-in user, because every PO screen needs it."""
    assert ROOT_FIELD_POLICY["gpCostCodeMaster"] == ADMIN_ROLE
    assert ROOT_FIELD_POLICY["gpCostCodes"] == SIGNED_IN


def test_relay_status_resolver_reads_gateway_connected(monkeypatch):
    gateway = RelayGateway()
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)
    status = Query().relay_status(FakeInfo())
    assert status.connected is False
    # #637: empty rather than null when nothing is connected - the dialogs read it as a list of
    # companies they may offer, and there are none.
    assert status.companies == []
    assert status.gp_companies == []
    # Null, not a reason: nothing is connected, which is its own explanation.
    assert status.companies_error is None


def test_a_read_for_a_company_the_relay_does_not_serve_is_refused(monkeypatch):
    """#637: a relay serving TUBC cannot answer for UCSH, so the request is refused here naming what
    IS available rather than after a 30-second round trip."""
    _install_fake_gateway(monkeypatch, {"jobs": []})

    async def run():
        return await Query().gp_jobs(FakeInfo(), company="UCSH")

    with pytest.raises(ValidationError) as e:
        asyncio.run(run())
    assert "TUBC" in str(e.value)


def test_a_scoped_caller_cannot_read_another_companys_gp(monkeypatch):
    """#637: the relay serving a company is not enough - a non-admin may only ask for their own."""
    fake = FakeGateway({"jobs": []}, companies=("TUBC", "UCSH"))
    monkeypatch.setattr(relay_module, "relay_gateway", fake)

    class ScopedInfo:
        context = {"request": None, "_auth_roles": ["Warehouse Manager"], "_auth_company": "TUBC"}

    async def run():
        return await Query().gp_jobs(ScopedInfo(), company="UCSH")

    with pytest.raises(ValidationError):
        asyncio.run(run())
    assert fake.calls == []


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


def test_gp_employees_requires_an_admin():
    """Every other gp_* read is open to any signed-in user; this one returns the payroll master with
    staff names, and its only consumer is the admin-only create-job dialog."""
    assert ROOT_FIELD_POLICY["gpEmployees"] == ADMIN_ROLE
    assert ROOT_FIELD_POLICY["gpDivisions"] == SIGNED_IN


def test_gp_divisions_passes_through_the_relay_list(monkeypatch):
    fake = _install_fake_gateway(monkeypatch, {"divisions": ["VANCOUVER"]})

    async def run():
        return await Query().gp_divisions(FakeInfo(), company="TUBC")

    assert asyncio.run(run()) == ["VANCOUVER"]
    assert fake.calls == [("TUBC", "list_divisions", None)]


# --- relayStatus's connection history + relayEvents (#654) ----------------------------------------


class _FakeSession:
    """Stands in for SessionLocal() so a resolver that only forwards to a repository needs no database."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _no_database(monkeypatch):
    monkeypatch.setattr(relay_module, "SessionLocal", _FakeSession)


def test_relay_status_reports_the_last_connect_disconnect_and_reason(monkeypatch):
    # The half of the answer that matters when nothing is connected: when it went, and why.
    gateway = RelayGateway()
    ws = object()
    gateway.try_register(ws)
    gateway.note_hello(
        "relay-v0.3.0",
        ["list_vendors"],
        ["TUBC", "TUCSH"],
        ["channels"],
        {"TUBC": "Test UBC"},
    )
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)

    status = Query().relay_status(FakeInfo())
    assert status.connected is True
    assert status.last_connected_at is not None
    assert status.last_disconnected_at is None
    assert status.companies == ["TUBC", "TUCSH"]

    gateway.unregister(ws)
    after = Query().relay_status(FakeInfo())
    assert after.connected is False
    assert after.last_connected_at == status.last_connected_at  # survives the disconnect
    assert after.last_disconnected_at is not None
    assert after.last_disconnect_reason


def test_relay_status_labels_the_companies_with_gps_own_names(monkeypatch):
    # The pickers show "TUBC - Test UBC"; a code GP gave no name for falls back to the bare code so a
    # partial answer is still a usable list.
    gateway = RelayGateway()
    gateway.try_register(object())
    gateway.note_hello("relay-v0.3.0", ["list_vendors"], ["TUBC", "UCSH"], ["channels"], {"TUBC": "Test UBC"})
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)

    status = Query().relay_status(FakeInfo())
    assert [(c.id, c.name) for c in status.gp_companies] == [("TUBC", "Test UBC"), ("UCSH", "UCSH")]
    assert status.companies_error is None


def test_relay_status_surfaces_why_a_connected_relay_reported_no_companies(monkeypatch):
    gateway = RelayGateway()
    gateway.try_register(object())
    gateway.note_hello("relay-v0.3.0", ["list_vendors"], [], ["channels"], {}, "GP is unreachable")
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)

    status = Query().relay_status(FakeInfo())
    assert status.connected is True
    assert status.companies == []
    assert status.gp_companies == []
    assert status.companies_error == "GP is unreachable"


def test_a_read_is_refused_with_the_relays_own_reason_when_it_serves_nothing(monkeypatch):
    # Connected but with no company master: the relay's reason is the only thing that names the fix,
    # so it rides the error instead of the generic "the relay is not connected".
    monkeypatch.setattr(
        relay_module, "relay_gateway", FakeGateway({"jobs": []}, companies=(), companies_error="GP is unreachable")
    )

    async def run():
        return await Query().gp_jobs(FakeInfo(), company="TUBC")

    with pytest.raises(RelayUnavailableError) as e:
        asyncio.run(run())
    assert "GP is unreachable" in str(e.value)


def test_relay_status_carries_the_preview_channels_it_is_pushing(monkeypatch):
    monkeypatch.setattr(relay_module, "relay_gateway", RelayGateway())
    monkeypatch.setattr(
        relay_module.preview_registry,
        "channels",
        lambda: ["wss://backend-uc-nexus-pr-9.up.railway.app/relay-link"],
    )
    assert Query().relay_status(FakeInfo()).preview_channels == [
        "wss://backend-uc-nexus-pr-9.up.railway.app/relay-link"
    ]


def test_relay_status_preview_channels_is_empty_off_production(monkeypatch):
    # The registry only ever fills on production; everywhere else this is the honest empty answer rather
    # than a null the frontend has to special-case.
    monkeypatch.setattr(relay_module, "relay_gateway", RelayGateway())
    preview_registry.reset()
    assert Query().relay_status(FakeInfo()).preview_channels == []


def test_relay_events_returns_the_newest_first(monkeypatch):
    _no_database(monkeypatch)
    rows = [
        SimpleNamespace(
            id=uuid.uuid4(),
            at=datetime(2026, 9, 1, 12, 0, 0),
            kind="DISCONNECTED",
            install_id=uuid.uuid4(),
            install_label="TAGGING3W10",
            build="relay-v0.2.0",
            companies=["TUBC"],
            reason="peer closed or socket dropped",
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            at=datetime(2026, 9, 1, 11, 0, 0),
            kind="CONNECTED",
            install_id=None,
            install_label=None,
            build=None,
            companies=None,
            reason=None,
        ),
    ]
    monkeypatch.setattr(relay_module.relay_event_repository, "list_events", lambda session, limit: rows)

    events = Query().relay_events(FakeInfo())
    assert [e.kind for e in events] == [RelayEventKind.DISCONNECTED, RelayEventKind.CONNECTED]
    assert events[0].install_label == "TAGGING3W10"
    assert events[0].reason == "peer closed or socket dropped"
    # A row written before any hello arrived carries no build and no company list; null, not empty.
    assert events[1].build is None
    assert events[1].companies is None


@pytest.mark.parametrize(("asked", "expected"), [(0, 1), (-5, 1), (10, 10), (5000, 500)])
def test_relay_events_bounds_the_limit(monkeypatch, asked, expected):
    # The argument reaches a LIMIT clause, so an unbounded one is a caller-controlled full table scan.
    _no_database(monkeypatch)
    seen: list[int] = []
    monkeypatch.setattr(
        relay_module.relay_event_repository,
        "list_events",
        lambda session, limit: seen.append(limit) or [],
    )
    Query().relay_events(FakeInfo(), limit=asked)
    assert seen == [expected]


def test_relay_events_is_gated_like_relay_installs():
    """These rows name installs, builds and refused credentials - relay-credential territory, not
    working data, so they sit at the same bar as the install list itself."""
    assert ROOT_FIELD_POLICY["relayEvents"] == ROOT_FIELD_POLICY["relayInstalls"] == ADMIN_ROLE
