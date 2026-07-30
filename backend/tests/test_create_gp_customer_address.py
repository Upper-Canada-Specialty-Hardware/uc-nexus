"""createGpCustomerAddress: admin gate, relay gating, payload shape and GP error surfacing (#444).

The mutation writes to GP's customer address master and persists nothing locally, so what these pin is
the guard order and the wire contract: a missing relay must stop the call before GP is touched, a blank
or over-length value must be refused here against GP's own char widths rather than after a round-trip,
the op name and every address key must reach the relay intact (a dropped key is a silently blank address
in GP), and a refusal must reach the dialog in the relay's words with its detail body intact - that body
is what the error alert renders.

The field named on a rejection is the GraphQL one, in camelCase. That is the string the dialog has to
match to highlight the input the user typed the value into; the resolver's own snake_case argument names
mean nothing on the client.
"""

import asyncio

import pytest

from app.auth import ADMIN_ROLE
from app.auth_policy import ROOT_FIELD_POLICY
from app.errors import RelayCallError, RelayUnavailableError, ValidationError
from app.schemas import relay as relay_module
from app.schemas.inputs import CreateGpCustomerAddressInput
from app.schemas.relay import RelayMutations


class _FakeInfo:
    context = {"request": None}


_STORED = {
    "address_code": "TOWER5",
    "address1": "1055 Dunsmuir St",
    "city": "Vancouver",
    "state": "BC",
}


def _relay(monkeypatch, *, company="TUBC", result=None, raises=None):
    calls: list[tuple] = []

    async def _call(_company, op, payload=None, timeout=None):
        calls.append((_company, op, payload))
        if raises is not None:
            raise raises
        return result if result is not None else {"company": _company, "customer": "ELL100", "address": _STORED}

    monkeypatch.setattr(type(relay_module.relay_gateway), "company", property(lambda self: company))
    monkeypatch.setattr(relay_module.relay_gateway, "relay_call", _call)
    return calls


def _input(**overrides):
    fields = {
        "customer_number": "ELL100",
        "address_code": "TOWER5",
        "address1": "1055 Dunsmuir St",
        "city": "Vancouver",
    }
    fields.update(overrides)
    return CreateGpCustomerAddressInput(**fields)


def _create(**overrides):
    return asyncio.run(RelayMutations().create_gp_customer_address(_FakeInfo(), _input(**overrides)))


def test_requires_an_admin():
    """Adding an address writes to the accounting system of record, and the only consumer is the
    create-job dialog, which is already admin-only - the same bar createGpJob and createGpBuyer set.

    Since #423 the gate is the policy table, applied by the schema extension before the resolver runs,
    so the requirement is asserted where it is decided; `test_resolver_auth_gates.py` covers that the
    extension enforces the table. The tests below call the resolver directly with no auth setup - what
    they pin is the guard order INSIDE the body."""
    assert ROOT_FIELD_POLICY["createGpCustomerAddress"] == ADMIN_ROLE


def test_no_relay_stops_before_gp(monkeypatch):
    async def _never(*a, **k):
        raise AssertionError("the relay must not be called when none is connected")

    monkeypatch.setattr(type(relay_module.relay_gateway), "company", property(lambda self: None))
    monkeypatch.setattr(relay_module.relay_gateway, "relay_call", _never)

    with pytest.raises(RelayUnavailableError):
        _create()


def test_company_comes_from_the_connected_relay(monkeypatch):
    # No company argument on this mutation: the connected relay is enrolled for exactly one company,
    # which is the only one the address could be written to. Same resolution createGpJob uses.
    calls = _relay(monkeypatch, company="TUCSH")

    _create()

    assert calls[0][0] == "TUCSH"


def test_sends_every_address_key_to_the_create_op(monkeypatch):
    # A dropped key is a silently blank column in GP, so the whole set is pinned rather than the
    # required four. `customer` is named as the read op names it (list_customer_addresses).
    calls = _relay(monkeypatch)

    _create(address2="Suite 900", state="BC", zip_code="V7X 1L2", country="Canada")

    company, op, payload = calls[0]
    assert (company, op) == ("TUBC", "create_customer_address")
    assert payload == {
        "customer": "ELL100",
        "address_code": "TOWER5",
        "address1": "1055 Dunsmuir St",
        "address2": "Suite 900",
        "city": "Vancouver",
        "state": "BC",
        "zip_code": "V7X 1L2",
        "country": "Canada",
    }


def test_unfilled_optionals_travel_as_none(monkeypatch):
    # The relay normalizes these to blanks and sends them; what matters here is that the keys are
    # present, so the relay is never guessing at what the user left empty.
    calls = _relay(monkeypatch)

    _create()

    payload = calls[0][2]
    assert payload["address2"] is None
    assert payload["state"] is None
    assert payload["zip_code"] is None
    assert payload["country"] is None


def test_answers_with_gps_stored_row_not_the_request(monkeypatch):
    # The relay reads RM00102 back after the write, and that row is what gpCustomerAddresses will
    # serve on its next refetch - so echoing the input could hand the dialog an address that differs
    # from the one the picker is about to show.
    _relay(
        monkeypatch,
        result={
            "company": "TUBC",
            "customer": "ELL100",
            "address": {
                "address_code": "TOWER5",
                "address1": "What GP Actually Kept",
                "city": "Burnaby",
                "state": "BC",
            },
        },
    )

    address = _create(address1="What The Caller Typed", city="Vancouver")

    assert address.address_code == "TOWER5"
    assert address.address1 == "What GP Actually Kept"
    assert address.city == "Burnaby"
    assert address.state == "BC"


def test_the_address_code_is_uppercased_on_the_way_out(monkeypatch):
    # GP's own codes are uppercase, and the relay uppercases too - doing it here as well means the
    # payload this backend logs is the row GP stores rather than whatever case it was typed in.
    calls = _relay(monkeypatch)

    _create(address_code="  tower5  ")

    assert calls[0][2]["address_code"] == "TOWER5"


@pytest.mark.parametrize(
    "attr,gql_field",
    [
        ("customer_number", "customerNumber"),
        ("address_code", "addressCode"),
        ("address1", "address1"),
        ("city", "city"),
    ],
)
def test_a_blank_required_field_is_rejected_before_the_relay(monkeypatch, attr, gql_field):
    # Without this the relay's model is the only thing checking, and its refusal arrives after a full
    # round-trip as a multi-line pydantic dump anchored to nothing the dialog can highlight.
    calls = _relay(monkeypatch)

    with pytest.raises(ValidationError) as exc:
        _create(**{attr: "   "})

    assert exc.value.field == gql_field
    assert calls == []


@pytest.mark.parametrize(
    "attr,gql_field,limit",
    [
        ("customer_number", "customerNumber", 15),
        ("address_code", "addressCode", 15),
        ("address1", "address1", 60),
        ("address2", "address2", 60),
        ("city", "city", 35),
        ("state", "state", 29),
        ("zip_code", "zipCode", 10),
        ("country", "country", 60),
    ],
)
def test_over_length_is_rejected_against_gps_own_width(monkeypatch, attr, gql_field, limit):
    # taCreateCustomerAddress's own parameter widths. Rejected, never truncated: SQL Server would
    # shorten a char column silently and put a wrong address on a job nobody would think to re-check.
    calls = _relay(monkeypatch)

    with pytest.raises(ValidationError) as exc:
        _create(**{attr: "x" * (limit + 1)})

    assert exc.value.field == gql_field
    assert str(limit) in str(exc.value)
    assert calls == []


def test_a_value_that_trims_to_a_legal_length_is_accepted(monkeypatch):
    calls = _relay(monkeypatch)

    _create(address_code="  " + "X" * 15 + "  ")

    assert calls[0][2]["address_code"] == "X" * 15


def test_a_relay_response_missing_the_address_fails_loudly(monkeypatch):
    # No fallback to the input: echoing what the caller typed would report a well-formed success for an
    # address nobody has confirmed landed in RM00102, which is the one thing this mutation must not do.
    _relay(monkeypatch, result={"company": "TUBC", "customer": "ELL100"})

    with pytest.raises(KeyError):
        _create()


def test_a_duplicate_code_surfaces_the_relays_own_message(monkeypatch):
    # Shaped as relay/errors.py error_body() builds it: {error, message, context}, always all three.
    # taCreateCustomerAddress has no validate-only pass, so the relay's pre-check is the whole guard -
    # and its sentence is what the dialog shows.
    detail = {
        "error": "address_code_already_exists",
        "message": "customer 'ELL100' already has address code 'TOWER5' in GP company TUBC (RM00102)",
        "context": {},
    }
    _relay(monkeypatch, raises=RelayCallError(detail["message"], detail=detail))

    with pytest.raises(ValidationError) as exc:
        _create()

    assert "already has address code" in str(exc.value)
    # The detail body rides along: ErrorHandlerExtension publishes it as extensions.relayError, which
    # is what the dialog's error alert renders.
    assert exc.value.detail == detail


def test_a_gp_refusal_surfaces_with_its_detail_intact(monkeypatch):
    # relay/errors.py econnect_error_body() nests the proc, the numeric state and its taErrorCode
    # description under `context` - that is the shape GpErrorAlert reads (error.relay.context.proc).
    detail = {
        "error": "econnect_error",
        "message": "Customer Number does not exist",
        "context": {
            "proc": "taCreateCustomerAddress",
            "error_state": 350,
            "error_description": "Customer Number does not exist",
        },
    }
    _relay(monkeypatch, raises=RelayCallError(detail["message"], detail=detail))

    with pytest.raises(ValidationError) as exc:
        _create()

    assert "Customer Number does not exist" in str(exc.value)
    assert exc.value.detail["context"]["proc"] == "taCreateCustomerAddress"
    assert exc.value.detail["context"]["error_state"] == 350
