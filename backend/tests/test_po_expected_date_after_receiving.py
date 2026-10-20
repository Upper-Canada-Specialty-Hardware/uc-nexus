"""Once receiving has started, the expected delivery date can still change (#1488, ruled option b).

A vendor pushing the rest of a PO out used to leave the back-order grid reading "overdue" for units on
a later truck, because every edit was refused once anything was received. Now the expected date and the
notes still change; everything else stays frozen, and a closed or cancelled PO stays frozen whole."""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.errors import InvalidStateTransitionError
from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.models.receiving import ReceiveRecord
from app.repositories import po_repository


def _po(session, status, *, received=False, **fields) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        status=status,
        company="TUBC",
        expected_delivery_date=date(2026, 10, 1),
        **fields,
    )
    session.add(po)
    session.flush()
    if received:
        session.add(ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=datetime.utcnow(), received_by="dock"))
        session.flush()
    return po


@pytest.mark.parametrize(
    ("status", "received"),
    [
        (POStatus.PARTIALLY_RECEIVED, True),
        (POStatus.GP_REGISTERED, True),
        (POStatus.VENDOR_CONFIRMED, True),
    ],
    ids=["partially-received", "registered-with-a-receive", "vendor-confirmed-with-a-receive"],
)
def test_the_expected_date_and_notes_still_change(db_session, status, received):
    po = _po(db_session, status, received=received)

    po_repository.update_po(
        db_session, po.id, expected_delivery_date=date(2026, 11, 15), notes="rest on the next truck"
    )

    assert po.expected_delivery_date == date(2026, 11, 15)
    assert po.notes == "rest on the next truck"
    assert po.status == status


def test_the_expected_date_can_be_cleared(db_session):
    po = _po(db_session, POStatus.PARTIALLY_RECEIVED)

    po_repository.update_po(db_session, po.id, expected_delivery_date=None)

    assert po.expected_delivery_date is None


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"vendor_quote_number": "Q-9"}, "the vendor quote number"),
        ({"tariff_amount": 12.5}, "the tariffs"),
        ({"po_number": "PO-OTHER"}, "the PO number"),
    ],
)
def test_anything_else_is_refused_and_nothing_changes(db_session, change, named):
    po = _po(db_session, POStatus.PARTIALLY_RECEIVED)

    with pytest.raises(InvalidStateTransitionError, match=named):
        po_repository.update_po(db_session, po.id, expected_delivery_date=date(2026, 11, 15), **change)

    assert po.expected_delivery_date == date(2026, 10, 1)


def test_an_unchanged_resend_still_saves(db_session):
    """An older tab sends every value it loaded; the ones it did not change must not refuse the date."""
    po = _po(db_session, POStatus.PARTIALLY_RECEIVED, vendor_quote_number="Q-1", tariff_amount=Decimal("5.00"))

    po_repository.update_po(
        db_session,
        po.id,
        expected_delivery_date=date(2026, 11, 15),
        vendor_quote_number="Q-1",
        tariff_amount=5.0,
        po_number=po.po_number,
    )

    assert po.expected_delivery_date == date(2026, 11, 15)


@pytest.mark.parametrize("status", [POStatus.CLOSED, POStatus.CANCELLED])
def test_a_closed_or_cancelled_po_stays_frozen(db_session, status):
    po = _po(db_session, status, received=True)

    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, expected_delivery_date=date(2026, 11, 15))
