"""Tests for warehouse_repository.get_project_progress_by_product."""

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.enums import HardwareItemState, POStatus, ShipmentStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem
from app.repositories import warehouse as warehouse_repository


def _make_project(session) -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=f"PROJ-{uuid.uuid4().hex[:8]}",
        description="Test",
        company="TUBC",
    )
    session.add(p)
    session.flush()
    return p


def _make_opening(session, project_id: uuid.UUID, opening_number: str = "A01") -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project_id, opening_number=opening_number)
    session.add(o)
    session.flush()
    return o


def _make_hardware_item(
    session,
    *,
    project_id: uuid.UUID,
    opening_id: uuid.UUID,
    product_code: str,
    hardware_category: str = "HINGE",
    item_quantity: int = 1,
) -> HardwareItem:
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project_id,
        opening_id=opening_id,
        hardware_category=hardware_category,
        product_code=product_code,
        item_quantity=item_quantity,
        state=HardwareItemState.AVAILABLE,
    )
    session.add(hi)
    session.flush()
    return hi


def _make_po(
    session,
    *,
    project_id: uuid.UUID,
    status: POStatus,
    deleted_at: datetime | None = None,
) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=status,
        deleted_at=deleted_at,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    return po


def _make_line_item(
    session,
    *,
    po_id: uuid.UUID,
    product_code: str,
    hardware_category: str = "HINGE",
    ordered_quantity: int = 1,
    received_quantity: int = 0,
) -> POLineItem:
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po_id,
        hardware_category=hardware_category,
        product_code=product_code,
        ordered_quantity=ordered_quantity,
        received_quantity=received_quantity,
        unit_cost=Decimal("1.00"),
    )
    session.add(li)
    session.flush()
    return li


def _make_packing_slip(session, project_id: uuid.UUID) -> PackingSlip:
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        shipped_by="tester",
        shipped_at=datetime.utcnow(),
        # Progress sums shipped quantities, so the fixture slip is already out the door (#447).
        status=ShipmentStatus.DELIVERED,
    )
    session.add(ps)
    session.flush()
    return ps


def _make_packing_slip_item(
    session,
    *,
    packing_slip_id: uuid.UUID,
    product_code: str,
    hardware_category: str = "HINGE",
    quantity: int = 1,
) -> PackingSlipItem:
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=packing_slip_id,
        product_code=product_code,
        hardware_category=hardware_category,
        quantity=quantity,
    )
    session.add(psi)
    session.flush()
    return psi


def test_returns_zero_aggregates_when_no_pos_or_shipments(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=3
    )
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-200", item_quantity=2
    )

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    by_code = {r["product_code"]: r for r in rows}

    assert set(by_code.keys()) == {"HG-100", "HG-200"}
    for code, expected_required in [("HG-100", 3), ("HG-200", 2)]:
        r = by_code[code]
        assert r["required_quantity"] == expected_required
        assert r["po_drafted"] == 0
        assert r["ordered_quantity"] == 0
        assert r["received_quantity"] == 0
        assert r["back_ordered"] == 0
        assert r["shipped_out"] == 0


def test_aggregates_required_across_openings(db_session):
    project = _make_project(db_session)
    o1 = _make_opening(db_session, project.id, "A01")
    o2 = _make_opening(db_session, project.id, "A02")
    _make_hardware_item(db_session, project_id=project.id, opening_id=o1.id, product_code="HG-100", item_quantity=4)
    _make_hardware_item(db_session, project_id=project.id, opening_id=o2.id, product_code="HG-100", item_quantity=6)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["product_code"] == "HG-100"
    assert rows[0]["required_quantity"] == 10


def test_counts_ordered_received_for_placed_pos(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )

    for status in (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED, POStatus.CLOSED):
        po = _make_po(db_session, project_id=project.id, status=status)
        _make_line_item(db_session, po_id=po.id, product_code="HG-100", ordered_quantity=2, received_quantity=1)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["ordered_quantity"] == 8  # 2 * 4 placed statuses
    assert rows[0]["received_quantity"] == 4  # 1 * 4 placed statuses


def test_excludes_draft_and_cancelled_pos_from_ordered_received(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )

    draft = _make_po(db_session, project_id=project.id, status=POStatus.DRAFT)
    _make_line_item(db_session, po_id=draft.id, product_code="HG-100", ordered_quantity=5, received_quantity=0)

    cancelled = _make_po(
        db_session,
        project_id=project.id,
        status=POStatus.CANCELLED,
        deleted_at=datetime.utcnow(),
    )
    _make_line_item(db_session, po_id=cancelled.id, product_code="HG-100", ordered_quantity=7, received_quantity=0)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["ordered_quantity"] == 0
    assert rows[0]["received_quantity"] == 0


def test_excludes_soft_deleted_pos(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )

    po = _make_po(
        db_session,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        deleted_at=datetime.utcnow(),
    )
    _make_line_item(db_session, po_id=po.id, product_code="HG-100", ordered_quantity=5, received_quantity=2)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert rows[0]["ordered_quantity"] == 0
    assert rows[0]["received_quantity"] == 0


def test_omits_product_codes_not_in_schedule(db_session):
    """PO line items for codes not present in the schedule should not introduce rows."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=5
    )

    po = _make_po(db_session, project_id=project.id, status=POStatus.GP_REGISTERED)
    _make_line_item(db_session, po_id=po.id, product_code="HG-100", ordered_quantity=3)
    _make_line_item(db_session, po_id=po.id, product_code="UNKNOWN", ordered_quantity=9)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["product_code"] == "HG-100"
    assert rows[0]["ordered_quantity"] == 3


def test_scoped_by_project(db_session):
    """POs, shipments, and hardware items from another project must not bleed in."""
    p1 = _make_project(db_session)
    p2 = _make_project(db_session)
    o1 = _make_opening(db_session, p1.id, "A01")
    o2 = _make_opening(db_session, p2.id, "B01")

    _make_hardware_item(db_session, project_id=p1.id, opening_id=o1.id, product_code="HG-100", item_quantity=5)
    _make_hardware_item(db_session, project_id=p2.id, opening_id=o2.id, product_code="HG-100", item_quantity=99)

    po_p2 = _make_po(db_session, project_id=p2.id, status=POStatus.GP_REGISTERED)
    _make_line_item(db_session, po_id=po_p2.id, product_code="HG-100", ordered_quantity=99, received_quantity=42)
    draft_p2 = _make_po(db_session, project_id=p2.id, status=POStatus.DRAFT)
    _make_line_item(db_session, po_id=draft_p2.id, product_code="HG-100", ordered_quantity=11)
    ps_p2 = _make_packing_slip(db_session, p2.id)
    _make_packing_slip_item(db_session, packing_slip_id=ps_p2.id, product_code="HG-100", quantity=7)

    rows = warehouse_repository.get_project_progress_by_product(db_session, p1.id)
    assert len(rows) == 1
    assert rows[0]["required_quantity"] == 5
    assert rows[0]["po_drafted"] == 0
    assert rows[0]["ordered_quantity"] == 0
    assert rows[0]["received_quantity"] == 0
    assert rows[0]["back_ordered"] == 0
    assert rows[0]["shipped_out"] == 0


def test_groups_by_category_and_product_code(db_session):
    """Same product code under different categories yields separate rows."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session,
        project_id=project.id,
        opening_id=opening.id,
        product_code="HG-100",
        hardware_category="HINGE",
        item_quantity=3,
    )
    _make_hardware_item(
        db_session,
        project_id=project.id,
        opening_id=opening.id,
        product_code="HG-100",
        hardware_category="LOCK",
        item_quantity=2,
    )

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    by_cat = {r["hardware_category"]: r for r in rows}
    assert by_cat["HINGE"]["required_quantity"] == 3
    assert by_cat["LOCK"]["required_quantity"] == 2


def test_returns_empty_for_project_without_schedule(db_session):
    project = _make_project(db_session)
    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert rows == []


def test_counts_po_drafted_only_from_draft_pos(db_session):
    """po_drafted comes from DRAFT POs and does NOT contribute to ordered/received."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )

    d1 = _make_po(db_session, project_id=project.id, status=POStatus.DRAFT)
    _make_line_item(db_session, po_id=d1.id, product_code="HG-100", ordered_quantity=4)
    d2 = _make_po(db_session, project_id=project.id, status=POStatus.DRAFT)
    _make_line_item(db_session, po_id=d2.id, product_code="HG-100", ordered_quantity=3)
    placed = _make_po(db_session, project_id=project.id, status=POStatus.GP_REGISTERED)
    _make_line_item(db_session, po_id=placed.id, product_code="HG-100", ordered_quantity=5, received_quantity=2)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    r = rows[0]
    assert r["po_drafted"] == 7  # 4 + 3
    assert r["ordered_quantity"] == 5
    assert r["received_quantity"] == 2


def test_back_ordered_excludes_closed_pos(db_session):
    """back_ordered = sum(ordered - received) for placed POs that are NOT CLOSED."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=20
    )

    # GP_REGISTERED with partial receipt → contributes 4 (10 - 6)
    p1 = _make_po(db_session, project_id=project.id, status=POStatus.GP_REGISTERED)
    _make_line_item(db_session, po_id=p1.id, product_code="HG-100", ordered_quantity=10, received_quantity=6)
    # PARTIALLY_RECEIVED → contributes 2 (5 - 3)
    p2 = _make_po(db_session, project_id=project.id, status=POStatus.PARTIALLY_RECEIVED)
    _make_line_item(db_session, po_id=p2.id, product_code="HG-100", ordered_quantity=5, received_quantity=3)
    # CLOSED → contributes 0 even though ordered - received > 0
    p3 = _make_po(db_session, project_id=project.id, status=POStatus.CLOSED)
    _make_line_item(db_session, po_id=p3.id, product_code="HG-100", ordered_quantity=7, received_quantity=4)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["back_ordered"] == 6  # 4 + 2, NOT counting CLOSED's 3


def test_shipped_out_sums_packing_slip_items(db_session):
    """shipped_out aggregates packing_slip_items.quantity scoped to the project."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )

    ps1 = _make_packing_slip(db_session, project.id)
    _make_packing_slip_item(db_session, packing_slip_id=ps1.id, product_code="HG-100", quantity=3)
    _make_packing_slip_item(db_session, packing_slip_id=ps1.id, product_code="HG-100", quantity=2)
    ps2 = _make_packing_slip(db_session, project.id)
    _make_packing_slip_item(db_session, packing_slip_id=ps2.id, product_code="HG-100", quantity=4)

    rows = warehouse_repository.get_project_progress_by_product(db_session, project.id)
    assert len(rows) == 1
    assert rows[0]["shipped_out"] == 9
