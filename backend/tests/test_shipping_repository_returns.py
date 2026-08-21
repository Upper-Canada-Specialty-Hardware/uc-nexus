"""Tests for shipping_repository shipment-return flow (issue #89)."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import ReturnDisposition, ShipmentStatus
from app.models.inventory import InventoryLocation
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
        # Returns come back from site, so the fixture slip is already through its journey (#447).
        status=ShipmentStatus.DELIVERED,
    )
    session.add(ps)
    session.flush()
    return ps


def _make_loose_item(session, slip_id, *, qty=5, code="HG-100", cat="HINGE", opening="101") -> PackingSlipItem:
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=slip_id,
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


def test_returnable_lines_tracks_what_has_already_come_back(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    loose = _make_loose_item(db_session, slip.id, qty=5)
    db_session.flush()
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": loose.id, "quantity": 2, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )

    lines = shipping_repository.get_returnable_lines(db_session, slip.id)
    assert len(lines) == 1
    line = lines[0]
    assert line["shipped_quantity"] == 5
    assert line["returned_quantity"] == 2
    assert line["returnable_quantity"] == 3


# --- returned units keep their value (unit cost re-resolved from the project / schedule) ---------


def test_return_to_project_carries_the_combo_cost(db_session):
    """The slip item has no link back to the rows the units shipped off, so the return re-resolves
    the combo's cost. Before this every returned unit valued at $0 from then on."""
    from decimal import Decimal

    from .inventory_fixtures import make_il

    project = _make_project(db_session)
    make_il(db_session, project, quantity=10, code="HG-100", category="HINGE", unit_cost=Decimal("6"))
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=5)
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 3, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )

    returned = (
        db_session.scalars(
            select(InventoryLocation).where(
                InventoryLocation.project_id == project.id,
                InventoryLocation.shipment_return_item_id.is_not(None),
            )
        )
        .unique()
        .one()
    )
    assert returned.unit_cost == Decimal("6")


def test_stock_branch_return_fills_the_pool_cost(db_session):
    from decimal import Decimal

    from .inventory_fixtures import make_il

    project = _make_project(db_session)
    make_il(db_session, project, quantity=10, code="NS-9", category="STRIKE", unit_cost=Decimal("2.5"))
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=4, code="NS-9", cat="STRIKE")
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 4, "disposition": ReturnDisposition.NON_STOCK}],
    )

    stock = db_session.scalars(select(StockItem).where(StockItem.product_code == "NS-9", StockItem.quantity > 0)).one()
    assert stock.unit_cost == Decimal("2.5")


def test_return_cost_falls_back_to_the_schedule(db_session):
    """No inventory row knows a price (all shipped out), but the schedule does."""
    from decimal import Decimal

    from app.models.enums import HardwareItemState
    from app.models.hardware import HardwareItem
    from app.models.project import Opening

    project = _make_project(db_session)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="A01")
    db_session.add(opening)
    db_session.flush()
    db_session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category="HINGE",
            product_code="HG-100",
            item_quantity=5,
            unit_cost=Decimal("3.75"),
            state=HardwareItemState.AVAILABLE,
        )
    )
    db_session.flush()
    slip = _make_slip(db_session, project.id)
    item = _make_loose_item(db_session, slip.id, qty=5)
    wh_id = _wh(db_session)

    _return(
        db_session,
        slip.id,
        wh_id,
        [{"packing_slip_item_id": item.id, "quantity": 2, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
    )

    returned = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.shipment_return_item_id.is_not(None),
        )
    ).one()
    assert returned.unit_cost == Decimal("3.75")


def _make_manual_item(session, slip_id, *, qty=2, code="MAN-1", cat="MISC") -> PackingSlipItem:
    """A manual line on the slip: on the truck, never in inventory - so there is nothing to restock."""
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=slip_id,
        opening_number=None,
        product_code=code,
        hardware_category=cat,
        quantity=qty,
        is_manual=True,
    )
    session.add(psi)
    session.flush()
    return psi


def test_a_manual_line_is_not_offered_as_returnable(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    real = _make_loose_item(db_session, slip.id, qty=5)
    _make_manual_item(db_session, slip.id, qty=2)

    lines = shipping_repository.get_returnable_lines(db_session, slip.id)
    assert [line["packing_slip_item_id"] for line in lines] == [real.id]


def test_returning_a_manual_line_is_refused(db_session):
    project = _make_project(db_session)
    slip = _make_slip(db_session, project.id)
    manual = _make_manual_item(db_session, slip.id, qty=2)
    wh_id = _wh(db_session)

    with pytest.raises(ValidationError, match="manual line cannot be returned"):
        _return(
            db_session,
            slip.id,
            wh_id,
            [{"packing_slip_item_id": manual.id, "quantity": 1, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
        )
