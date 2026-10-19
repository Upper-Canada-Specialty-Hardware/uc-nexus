"""Which POs a shipment's lines came in on (#1732).

Ruled as candidates (#1721): the picks name the exact rows they took and each row knows its PO, but
the staging floor pools picked hardware per product, so a slip line's candidates are every PO the
project's shipping picks drew that product from. Pinned: the candidates are exactly those, a draft
pick or another project's pick adds none, and a manual line has none.
"""

import uuid
from datetime import datetime

from app.models.enums import POStatus, PullPickLineState, PullRequestSource, PullRequestStatus, ShipmentStatus
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.shipping import PackingSlip, PackingSlipItem
from app.repositories.po_trace import slip_candidate_pos
from tests.inventory_fixtures import make_il, make_project


def _po_row(session, project, po_number, code="HG-100"):
    """An inventory row received on a PO numbered `po_number`."""
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        po_number=po_number,
        project_id=project.id,
        company=project.company,
        status=POStatus.CLOSED,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code=code,
        ordered_quantity=10,
        received_quantity=10,
    )
    session.add(line)
    session.flush()
    record = ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=datetime.utcnow(), received_by="receiver")
    session.add(record)
    session.flush()
    receive_line = ReceiveLineItem(
        id=uuid.uuid4(),
        receive_record_id=record.id,
        po_line_item_id=line.id,
        hardware_category="HINGE",
        product_code=code,
        quantity_received=10,
    )
    session.add(receive_line)
    session.flush()
    return make_il(session, project, code=code, po_line_item_id=line.id, receive_line_item_id=receive_line.id)


def _picked(session, project, row, *, state=PullPickLineState.APPLIED, source=PullRequestSource.SHIPPING_OUT):
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=source,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    session.add(
        PullPickLine(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            hardware_category=row.hardware_category,
            product_code=row.product_code,
            inventory_location_id=row.id,
            quantity=1,
            state=state,
            entered_by="picker",
            entered_at=datetime.utcnow(),
            applied_at=datetime.utcnow() if state == PullPickLineState.APPLIED else None,
        )
    )
    session.flush()


def _slip(session, project, lines):
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-T{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        shipped_by="tester",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
    )
    session.add(slip)
    session.flush()
    items = []
    for code, manual in lines:
        item = PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=slip.id,
            opening_number="101",
            hardware_category="HINGE",
            product_code=code,
            quantity=1,
            is_manual=manual,
        )
        session.add(item)
        items.append(item)
    session.flush()
    return slip, items


def test_a_slip_line_names_every_po_its_projects_shipping_picks_drew_from(db_session):
    project = make_project(db_session)
    other = make_project(db_session)
    _picked(db_session, project, _po_row(db_session, project, "PO-1001"))
    _picked(db_session, project, _po_row(db_session, project, "PO-1002"))
    # Not candidates: a pick still being keyed in, an assembly pick, and another project's pick.
    _picked(db_session, project, _po_row(db_session, project, "PO-2001"), state=PullPickLineState.DRAFT)
    _picked(db_session, project, _po_row(db_session, project, "PO-2002"), source=PullRequestSource.SHOP_ASSEMBLY)
    _picked(db_session, other, _po_row(db_session, other, "PO-3001"))

    slip, (hinge, manual, never_picked) = _slip(
        db_session, project, [("HG-100", False), ("HG-100", True), ("HG-999", False)]
    )
    trace = slip_candidate_pos(db_session, slip.id)
    assert trace[hinge.id] == ["PO-1001", "PO-1002"]
    assert trace[manual.id] == []
    assert trace[never_picked.id] == []
