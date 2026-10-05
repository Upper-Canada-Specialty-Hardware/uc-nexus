"""Shipping cost on a registered PO is GP's (#1572).

The PO sync writes GP's freight onto every registered PO on each pass, so a Nexus edit to it was saved,
shown, and then silently undone within minutes. A change is refused once the PO is registered; a draft
keeps it, and resending the unchanged value (an older tab) still saves."""

import uuid
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository


def _po(session, status, shipping_cost=None) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        status=status,
        company="TUBC",
        shipping_cost=shipping_cost,
    )
    session.add(po)
    session.flush()
    return po


@pytest.mark.parametrize("status", [POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED])
def test_a_shipping_cost_change_on_a_registered_po_is_refused(db_session, status):
    po = _po(db_session, status, shipping_cost=Decimal("0.00"))

    with pytest.raises(ValidationError) as excinfo:
        po_repository.update_po(db_session, po.id, shipping_cost=85)

    assert excinfo.value.field == "shipping_cost"
    assert "held in GP" in excinfo.value.message
    assert po.shipping_cost == Decimal("0.00")


def test_a_draft_takes_a_shipping_cost(db_session):
    po = _po(db_session, POStatus.DRAFT)
    po_repository.update_po(db_session, po.id, shipping_cost=85)
    assert po.shipping_cost == Decimal("85")


def test_resending_the_unchanged_shipping_cost_on_a_registered_po_still_saves(db_session):
    po = _po(db_session, POStatus.GP_REGISTERED, shipping_cost=Decimal("12.50"))
    po_repository.update_po(db_session, po.id, shipping_cost=12.5, notes="unrelated")
    assert po.notes == "unrelated"


def test_tariffs_stay_editable_on_a_registered_po(db_session):
    po = _po(db_session, POStatus.GP_REGISTERED)
    po_repository.update_po(db_session, po.id, tariff_amount=40)
    assert po.tariff_amount == Decimal("40")
