"""Tests for shipping_repository shipment-return flow (issue #89)."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import OpeningItemState, PullRequestItemType, ReturnDisposition, ShipmentStatus
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItem
from app.models.project import Project
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.stock_item import StockItem
from app.repositories import shipping_repository, warehouse_admin_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_slip(session, project_id) -> PackingSlip:
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
    )
    session.add(ps)
    session.flush()
    return ps


def _make_loose_item(session, slip_id, *, qty=5, code="HG-100", cat="HINGE", opening="101") -> PackingSlipItem:
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=slip_id,
        item_type=PullRequestItemType.LOOSE,
        opening_number=opening,
        product_code=code,
        hardware_category=cat,
        quantity=qty,
    )
    session.add(psi)
    session.flush()
    return psi


def _wh(session) -> uuid.UUID:
    return warehouse_admin_repository.get_primary_warehouse_id(session)


def _return(session, slip_id, wh_id, items):
    return shipping_repository.create_shipment_return(
        session,
        packing_slip_id=slip_id,
        warehouse_id=wh_id,
        returned_by="tester",
        reference=None,
        items=items,
    )


def test_return_to_project_creates_unlocated_inventory(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=5)
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 3, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )

    rows = list(db_session.scalars(select(InventoryLocation).where(InventoryLocation.project_id == project.id)).all())
    assert len(rows) == 1
    row = rows[0]
    assert row.quantity == 3
    assert (row.aisle, row.row, row.bay) == (None, None, None)  # unlocated -> Put-Away
    assert row.shipment_return_item_id is not None
    assert row.po_line_item_id is None and row.stock_item_id is None


def test_non_stock_merges_into_stock_pool(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=4, code="NS-1", cat="STRIKE")
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 4, "disposition": ReturnDisposition.NON_STOCK}],
    )

    stock = list(
        db_session.scalars(
            select(StockItem).where(StockItem.product_code == "NS-1", StockItem.warehouse_id == wh_id)
        ).all()
    )
    assert len(stock) == 1
    assert stock[0].quantity == 4
    assert stock[0].deficient_quantity == 0


def test_rma_defective_flags_stock_deficient(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=2, code="RMA-1", cat="CLOSER")
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [
            {
                "packing_slip_item_id": item.id,
                "quantity": 2,
                "disposition": ReturnDisposition.RMA_DEFECTIVE,
                "rma_reference": "RMA-9000",
            }
        ],
    )

    stock = db_session.scalars(
        select(StockItem).where(StockItem.product_code == "RMA-1", StockItem.warehouse_id == wh_id)
    ).first()
    assert stock is not None
    assert stock.quantity == 2
    assert stock.deficient_quantity == 2


def test_over_return_rejected(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=5)
    wh_id = _wh(db_session)

    with pytest.raises(ValidationError):
        _return(
            db_session,
            slip.id,
            wh_id,
            [{"packing_slip_item_id": item.id, "quantity": 6, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
        )


def test_cumulative_over_return_across_events_rejected(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=5)
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 4, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )
    # 4 already returned; only 1 left, so returning 2 more must fail
    with pytest.raises(ValidationError):
        _return(
            db_session,
            slip.id,
            wh_id,
            [{"packing_slip_item_id": item.id, "quantity": 2, "disposition": ReturnDisposition.NON_STOCK}],
        )


def test_opening_item_line_not_returnable(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    oi_item = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=slip.id,
        item_type=PullRequestItemType.OPENING_ITEM,
        opening_number="201",
        product_code="DOOR-1",
        hardware_category="ASSEMBLY",
        quantity=1,
    )
    db_session.add(oi_item)
    db_session.flush()
    wh_id = _wh(db_session)

    with pytest.raises(ValidationError):
        _return(
            db_session,
            slip.id,
            wh_id,
            [{"packing_slip_item_id": oi_item.id, "quantity": 1, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
        )


def test_returnable_lines_tracks_returned_and_excludes_openings(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    loose = _make_loose_item(db_session, slip.id, qty=5)
    db_session.add(
        PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=slip.id,
            item_type=PullRequestItemType.OPENING_ITEM,
            opening_number="201",
            product_code="DOOR-1",
            hardware_category="ASSEMBLY",
            quantity=1,
        )
    )
    db_session.flush()
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": loose.id, "quantity": 2, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )

    lines = shipping_repository.get_returnable_lines(db_session, slip.id)
    assert len(lines) == 1  # opening item excluded
    line = lines[0]
    assert line["shipped_quantity"] == 5
    assert line["returned_quantity"] == 2
    assert line["returnable_quantity"] == 3


def test_confirm_shipment_stamps_leaf_on_opening_item_line(db_session):
    """confirm_shipment snapshots the assembled unit's door leaf onto the PackingSlipItem (#311)."""
    project = _make_project(db_session)
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=uuid.uuid4(),
        warehouse_id=_wh(db_session),
        opening_number="PR1",
        leaf=2,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=OpeningItemState.SHIP_READY,
    )
    db_session.add(oi)
    db_session.flush()

    slip = shipping_repository.confirm_shipment(
        db_session,
        project_id=project.id,
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        shipped_by="shipper",
        items=[{"item_type": PullRequestItemType.OPENING_ITEM, "opening_item_id": oi.id, "quantity": 1}],
    )
    db_session.flush()

    psi = db_session.scalar(select(PackingSlipItem).where(PackingSlipItem.packing_slip_id == slip.id))
    assert psi.item_type == PullRequestItemType.OPENING_ITEM
    assert psi.leaf == 2

    db_session.refresh(oi)
    assert oi.state == OpeningItemState.SHIPPED_OUT
    # The #447 lifecycle sits on top of this, not in front of it: the slip starts SCHEDULED and the
    # claim on the hardware is still made here, at confirm time.
    assert slip.status == ShipmentStatus.SCHEDULED
