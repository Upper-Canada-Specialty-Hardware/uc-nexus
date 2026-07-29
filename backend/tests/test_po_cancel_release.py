"""Cancelling a PO must release its hardware-schedule rows.

The wizard stamps HardwareItem rows IN_PO with po_line_item_id when it drafts a PO. Cancelling the
PO used to leave them that way: reconciliation (which excludes cancelled POs) told the user the
combo still needed ordering, but the re-order minted brand-new IN_PO rows next to the stranded
ones - double-counting required_quantity - and the stranded key blocked the item from ever being
recreated as AVAILABLE by a later import.
"""

import uuid
from decimal import Decimal

import pytest

from app.errors import InvalidStateTransitionError
from app.models.enums import HardwareItemState, POStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import po_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _po_with_schedule_item(session, project, *, status=POStatus.DRAFT):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=status,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=2,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
    )
    session.add(line)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"OP-{uuid.uuid4().hex[:4]}")
    session.add(opening)
    session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category="HINGE",
        product_code="HG-100",
        item_quantity=2,
        state=HardwareItemState.IN_PO,
        po_line_item_id=line.id,
    )
    session.add(hi)
    session.flush()
    return po, line, hi


def test_cancel_po_releases_schedule_items(db_session):
    project = _make_project(db_session)
    po, _line, hi = _po_with_schedule_item(db_session, project)

    cancelled = po_repository.cancel_po(db_session, po.id)
    db_session.flush()
    db_session.refresh(hi)

    assert cancelled.status == POStatus.CANCELLED
    assert hi.state == HardwareItemState.AVAILABLE
    assert hi.po_line_item_id is None


def test_cancel_po_leaves_other_pos_items_alone(db_session):
    project = _make_project(db_session)
    po_a, _line_a, hi_a = _po_with_schedule_item(db_session, project)
    _po_b, _line_b, hi_b = _po_with_schedule_item(db_session, project)

    po_repository.cancel_po(db_session, po_a.id)
    db_session.flush()
    db_session.refresh(hi_a)
    db_session.refresh(hi_b)

    assert hi_a.state == HardwareItemState.AVAILABLE
    assert hi_b.state == HardwareItemState.IN_PO
    assert hi_b.po_line_item_id is not None


def test_cancel_po_refused_after_receiving_started(db_session):
    project = _make_project(db_session)
    po, _line, hi = _po_with_schedule_item(db_session, project, status=POStatus.PARTIALLY_RECEIVED)

    with pytest.raises(InvalidStateTransitionError):
        po_repository.cancel_po(db_session, po.id)
    db_session.refresh(hi)
    assert hi.state == HardwareItemState.IN_PO
