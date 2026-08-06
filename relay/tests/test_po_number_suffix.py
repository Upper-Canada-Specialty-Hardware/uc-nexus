"""Project number appended to the GP PO number (#488).

GP still owns and reserves the number - Nexus never invents one. The relay appends '-<project>' to
what taGetPONextNumber hands back, so two purchasers registering at the same moment produce numbers
that are visibly distinct and say which job they belong to.
"""

from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.ops import RelayOpError


class _Conn:
    """Enough of a connection for create_po_op to reach the number step and stop there."""


def _request(**overrides) -> models.CreatePoRequest:
    kwargs = dict(
        company="TUBC",
        header=models.POHeader(
            vendor_id="ING100", buyer_id="MIRA", confirm_with="Mira", doc_date=date(2026, 8, 6)
        ),
        lines=[
            models.POLine(
                item_number="ML2010",
                item_description="ML2010 LOCK",
                quantity=Decimal("2"),
                unit_cost=Decimal("12.50"),
                product_indicator=1,
            )
        ],
    )
    kwargs.update(overrides)
    return models.CreatePoRequest(**kwargs)


@pytest.fixture
def stubbed(monkeypatch):
    """Everything before the PO-number step passes; everything after it is left unstubbed, so the op
    stops right after composing the number and the test reads it off the collision check."""
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["MIRA"])
    monkeypatch.setattr(econnect, "get_vendor_currency", lambda conn, vendor_id: "CAD")
    monkeypatch.setattr(
        econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "BUY"}
    )
    monkeypatch.setattr(econnect, "get_next_po_number", lambda conn: "PO0012345")
    seen: dict = {}

    def _in_use(conn, po_number):
        seen["po_number"] = po_number
        # Stop the op here: it has done the only thing under test.
        raise RelayOpError("stop", "checked", po_number=po_number)

    monkeypatch.setattr(econnect, "po_number_in_use", _in_use)
    return seen


def test_appends_the_project_number_to_gp_reserved_number(stubbed):
    with pytest.raises(RelayOpError):
        ops.create_po_op(_Conn(), company="TUBC", request=_request(po_number_suffix="23093"))

    assert stubbed["po_number"] == "PO0012345-23093"


def test_no_suffix_leaves_the_reserved_number_untouched(stubbed):
    with pytest.raises(RelayOpError):
        ops.create_po_op(_Conn(), company="TUBC", request=_request())

    assert stubbed["po_number"] == "PO0012345"


def test_refuses_a_suffix_that_overflows_gp_ponumber(stubbed):
    """PONUMBER is char(17). SQL Server would truncate silently, leaving a PO nobody can match back
    to the number Nexus recorded."""
    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_Conn(), company="TUBC", request=_request(po_number_suffix="12345678"))

    assert excinfo.value.code == "invalid_payload"
    assert "17" in excinfo.value.message
    # It never reached the collision check, so nothing was composed against GP.
    assert "po_number" not in stubbed


def test_an_explicit_po_number_ignores_the_suffix(stubbed):
    with pytest.raises(RelayOpError):
        ops.create_po_op(
            _Conn(),
            company="TUBC",
            request=_request(po_number="UCNEXUS-1", po_number_suffix="23093"),
        )

    assert stubbed["po_number"] == "UCNEXUS-1"
