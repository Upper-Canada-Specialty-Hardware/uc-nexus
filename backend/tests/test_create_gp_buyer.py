"""createGpBuyer: admin gate, relay gating, input bounds, and GP error surfacing (#409).

The mutation writes to GP's buyer master and persists nothing locally, so what these pin is the
guard order: a non-admin and a missing relay must both stop the call before GP is touched, an
over-length id must be rejected against GP's own char widths rather than after a round-trip, and a
refusal (an id already registered) must reach the dialog in the relay's words with its detail body
intact - that body is what the error alert renders.
"""

import asyncio

import pytest

from app.auth import ADMIN_ROLE
from app.auth_policy import ROOT_FIELD_POLICY
from app.errors import RelayCallError, RelayUnavailableError, ValidationError
from app.schemas import relay as relay_module
from app.schemas.relay import RelayMutations


class _FakeInfo:
    # An ADMIN caller, seeded straight into the per-request role memo. `tenant_scope` reads it (#637)
    # and answers None for an admin, so these tests exercise the relay gating rather than tenancy -
    # without the seed the lookup would try to verify a JWT off a request that is not there.
    context = {"request": None, "_auth_roles": [ADMIN_ROLE]}


def _relay(monkeypatch, *, company="TUBC", result=None, raises=None):
    calls: list[tuple] = []

    async def _call(_company, op, payload=None, timeout=None):
        calls.append((_company, op, payload))
        if raises is not None:
            raise raises
        return result if result is not None else {"buyer_id": "newbuyer", "description": "New Buyer"}

    monkeypatch.setattr(
        type(relay_module.relay_gateway),
        "companies",
        property(lambda self: [company] if company else []),
    )
    monkeypatch.setattr(relay_module.relay_gateway, "relay_call", _call)
    return calls


def _create(**kwargs):
    fields = {"buyer_id": "newbuyer", "description": "New Buyer"}
    fields.update(kwargs)
    return asyncio.run(RelayMutations().create_gp_buyer(_FakeInfo(), **fields))


def test_requires_an_admin():
    """Registering a buyer writes to the accounting system of record.

    Since #423 the gate is the policy table, applied by the schema extension before the resolver, so
    the requirement is asserted where it is now decided; `test_resolver_auth_gates.py` covers that the
    extension enforces the table and refuses before the body runs. The tests below therefore call the
    resolver directly with no auth setup at all - what they are about is the guard order INSIDE the
    body, which is unchanged."""
    assert ROOT_FIELD_POLICY["createGpBuyer"] == ADMIN_ROLE


def test_no_relay_stops_before_gp(monkeypatch):
    async def _never(*a, **k):
        raise AssertionError("the relay must not be called when none is connected")

    monkeypatch.setattr(type(relay_module.relay_gateway), "companies", property(lambda self: []))
    monkeypatch.setattr(relay_module.relay_gateway, "relay_call", _never)

    with pytest.raises(RelayUnavailableError):
        _create()


def test_sends_the_trimmed_buyer_to_the_relay(monkeypatch):
    calls = _relay(monkeypatch)

    _create(buyer_id="  newbuyer  ", description="  New Buyer  ")

    assert calls == [("TUBC", "create_buyer", {"buyer_id": "newbuyer", "description": "New Buyer"})]


def test_company_defaults_to_the_connected_relays(monkeypatch):
    # The connected relay is enrolled for exactly one company, which is the only one it could write to.
    calls = _relay(monkeypatch, company="TUCSH")

    _create(company=None)

    assert calls[0][0] == "TUCSH"


def test_answers_with_gps_stored_row_not_the_request(monkeypatch):
    # The relay reads POP00101 back after the write, and that row is what the dropdown will show on
    # its next refetch - so answering with the request echoed back could hand the dialog a buyer that
    # differs from the one everything else is about to see.
    _relay(monkeypatch, result={"buyer_id": "newbuyer", "description": "What GP Actually Kept"})

    buyer = _create(description="What Was Asked For")

    assert buyer.buyer_id == "newbuyer"
    assert buyer.description == "What GP Actually Kept"


def test_blank_buyer_id_is_rejected_before_the_relay(monkeypatch):
    calls = _relay(monkeypatch)

    with pytest.raises(ValidationError) as exc:
        _create(buyer_id="   ")

    assert exc.value.field == "buyer_id"
    assert calls == []


def test_over_length_buyer_id_is_rejected_against_gps_own_width(monkeypatch):
    # BUYERID is char(15). Caught here rather than after a full round-trip returning invalid_payload.
    calls = _relay(monkeypatch)

    with pytest.raises(ValidationError) as exc:
        _create(buyer_id="x" * 16)

    assert exc.value.field == "buyer_id"
    assert calls == []


def test_over_length_description_is_rejected(monkeypatch):
    calls = _relay(monkeypatch)

    with pytest.raises(ValidationError) as exc:
        _create(description="x" * 31)

    assert exc.value.field == "description"
    assert calls == []


def test_an_already_registered_buyer_surfaces_the_relays_own_message(monkeypatch):
    # Shaped as relay/errors.py error_body() builds it: {error, message, context}, always all three.
    detail = {
        "error": "buyer_already_exists",
        "message": "buyer 'donr' is already registered in GP company TUBC (POP00101)",
        "context": {},
    }
    _relay(monkeypatch, raises=RelayCallError(detail["message"], detail=detail))

    with pytest.raises(ValidationError) as exc:
        _create(buyer_id="donr")

    assert "already registered" in str(exc.value)
    # The detail body rides along: ErrorHandlerExtension publishes it as extensions.relayError, which
    # is what the dialog's error alert renders.
    assert exc.value.detail == detail


def test_a_gp_refusal_surfaces_with_its_detail_intact(monkeypatch):
    # relay/errors.py econnect_error_body() nests the proc, the numeric state and its taErrorCode
    # description under `context` - that is the shape GpErrorAlert reads (error.relay.context.proc),
    # so asserting against a flattened one would prove nothing about what the alert renders.
    detail = {
        "error": "econnect_error",
        "message": "Unable to insert into the Buyer Master Table - POP00101",
        "context": {
            "proc": "taCreateBuyer",
            "error_state": 2683,
            "error_description": "Unable to insert into the Buyer Master Table - POP00101",
        },
    }
    _relay(monkeypatch, raises=RelayCallError(detail["message"], detail=detail))

    with pytest.raises(ValidationError) as exc:
        _create()

    assert exc.value.detail["context"]["proc"] == "taCreateBuyer"
    assert exc.value.detail["context"]["error_state"] == 2683
