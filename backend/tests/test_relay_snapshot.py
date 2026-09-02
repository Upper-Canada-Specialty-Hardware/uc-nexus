"""Query.relaySnapshot (#666): the relay fixture snapshot, captured through the connected relay.

Run through the real schema rather than against a Query instance, because half of what matters here is
decided outside the resolver body - the admin gate (app/auth_policy.py) and the per-company tenant
check in `resolve_gp_company`. The relay is a fake gateway; there is no socket and no GP.
"""

import asyncio
import json

import pytest

from app import auth
from app.auth import ADMIN_ROLE
from app.auth_policy import ROOT_FIELD_POLICY
from app.repositories import user_repository
from app.schemas import relay as relay_module
from main import schema

QUERY = "query($c: [String!]!){ relaySnapshot(companies: $c) }"

# What a relay answers `capture_snapshot` with: the constants it holds, and one company's record.
_TUBC = {"name": "Upper Canada Building", "vendors": [{"vendor_id": "V1"}], "jobs": []}
_TUCSH = {"vendors": [], "jobs": [{"job_number": "31004"}]}


class _FakeRequest:
    def __init__(self, token="tok"):
        self.headers = {"authorization": f"Bearer {token}"}


class FakeGateway:
    """The connected relay. `records` is what each company's capture_snapshot answers with, and the
    format/version are the relay's to state - a test can move them and watch the envelope follow."""

    def __init__(self, records, companies=("TUBC", "TUCSH"), fmt="ucnexus-relay-gp-snapshot", version=1):
        self.records = records
        self.companies = list(companies)
        self.company_names = {c: c for c in companies}
        self.companies_error = None
        self.fmt = fmt
        self.version = version
        self.calls: list[tuple] = []

    async def relay_call(self, company, op, payload=None, timeout=None):
        self.calls.append((company, op, payload, timeout))
        return {"format": self.fmt, "version": self.version, "record": self.records[company]}


@pytest.fixture
def caller(monkeypatch):
    """A signed-in identity whose roles a test picks, with Clerk stubbed out entirely.

    `get_user_company` is stubbed alongside the roles per the multi-tenancy convention (#637): an
    unstubbed one reaches Clerk the moment `resolve_gp_company` asks for the caller's scope."""

    def _sign_in(roles, company="TUBC"):
        monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
        monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: list(roles))
        monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: company)

    return _sign_in


@pytest.fixture
def relay(monkeypatch):
    def _install(records, companies=("TUBC", "TUCSH"), **kwargs):
        fake = FakeGateway(records, companies, **kwargs)
        monkeypatch.setattr(relay_module, "relay_gateway", fake)
        return fake

    return _install


def _execute(companies):
    return asyncio.run(
        schema.execute(QUERY, variable_values={"c": companies}, context_value={"request": _FakeRequest()})
    )


def _codes(result) -> set:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


def test_an_admin_gets_the_whole_envelope_for_every_company_asked_for(caller, relay):
    """The assembled file, ready to write over relay/fixtures/gp-snapshot.json - which is why the
    trailing newline is asserted too, the same one `ucnexus-relay capture` writes."""
    caller([ADMIN_ROLE])
    fake = relay({"TUBC": _TUBC, "TUCSH": _TUCSH})

    result = _execute(["TUBC", "TUCSH"])

    assert result.errors is None, result.errors
    text = result.data["relaySnapshot"]
    assert text.endswith("\n")
    envelope = json.loads(text)
    assert envelope["companies"] == {"TUBC": _TUBC, "TUCSH": _TUCSH}
    assert envelope["source"] == "captured from GP by the relaySnapshot query"
    assert envelope["captured_at"]
    assert [(c, op) for c, op, _payload, _timeout in fake.calls] == [
        ("TUBC", "capture_snapshot"),
        ("TUCSH", "capture_snapshot"),
    ]


def test_the_format_and_version_are_copied_out_of_the_reply(caller, relay):
    """The relay owns the snapshot format, so the backend writes whatever the op said it was rather
    than a constant of its own that could drift from the file the relay actually produces."""
    caller([ADMIN_ROLE])
    relay({"TUBC": _TUBC}, fmt="some-later-format", version=7)

    envelope = json.loads(_execute(["TUBC"]).data["relaySnapshot"])

    assert envelope["format"] == "some-later-format"
    assert envelope["version"] == 7


def test_the_capture_gets_a_timeout_that_fits_a_real_company(caller, relay):
    """Every PO in the company, plus its header totals, is minutes of GP - the gateway's default
    would abandon the work after it had all been done."""
    caller([ADMIN_ROLE])
    fake = relay({"TUBC": _TUBC})

    _execute(["TUBC"])

    assert fake.calls[0][3] == relay_module._SNAPSHOT_TIMEOUT_SECONDS


def test_a_signed_in_non_admin_is_refused_before_the_relay_is_touched(caller, relay):
    """It hands back a GP company whole, so it sits with the other admin relay fields."""
    assert ROOT_FIELD_POLICY["relaySnapshot"] == ADMIN_ROLE
    caller([])
    fake = relay({"TUBC": _TUBC})

    result = _execute(["TUBC"])

    assert _codes(result) == {"FORBIDDEN"}
    assert fake.calls == []


def test_a_company_the_relay_does_not_serve_is_rejected(caller, relay):
    """resolve_gp_company runs for every company in the list, so one bad name refuses the whole
    capture instead of quietly writing a snapshot missing a company that was asked for."""
    caller([ADMIN_ROLE])
    fake = relay({"TUBC": _TUBC}, companies=("TUBC",))

    result = _execute(["TUBC", "UCSH"])

    assert _codes(result) == {"VALIDATION_ERROR"}
    assert any("UCSH" in e.message for e in result.errors)
    assert fake.calls == []


def test_an_empty_company_list_is_a_validation_error(caller, relay):
    """Nothing to capture is a mistake with a message, not an envelope holding no companies that
    somebody writes over the fixture."""
    caller([ADMIN_ROLE])
    fake = relay({})

    result = _execute([])

    assert _codes(result) == {"VALIDATION_ERROR"}
    assert {(e.extensions or {}).get("field") for e in result.errors} == {"companies"}
    assert fake.calls == []
