"""A create re-sent after a lost reply hands back what it wrote, and writes nothing new (#1552).

The Shipping module's new shipping-out request and the shipment return dialog mint one key when they
open and send it with every attempt. A resend carrying the key of a create that already committed is
answered with that create's row: one request reserving the stock once, one return booking it back once.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.errors import ValidationError
from app.models.enums import ReturnDisposition, ShipmentStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.shipping import PackingSlip, PackingSlipItem, ShipmentReturn
from app.models.shipping_out_request import ShippingOutRequest
from app.models.stock_item import StockItem
from app.repositories import shipping_repository, shipping_requests, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _wh(session) -> uuid.UUID:
    return warehouse_admin_repository.get_primary_warehouse_id(session)


def _stock(session, project, *, qty=10):
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=_wh(session),
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=qty,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=si.id,
            warehouse_id=_wh(session),
            hardware_category="HINGE",
            product_code="HG-100",
            quantity=qty,
            deficient_quantity=0,
            received_at=datetime.utcnow(),
        )
    )
    session.flush()


def _request(session, project, key):
    item = {"opening_number": None, "hardware_category": "HINGE", "product_code": "HG-100", "requested_quantity": 4}
    return shipping_requests.create_shipping_out_requests(
        session, project.id, [{"items": [item]}], created_by="Shipper", idempotency_key=key
    )[0]


def _requests_on(session, project) -> int:
    return session.scalar(
        select(func.count()).select_from(ShippingOutRequest).where(ShippingOutRequest.project_id == project.id)
    )


def test_a_resent_shipping_out_request_returns_the_first_and_reserves_once(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)

    first = _request(db_session, project, "key-1")
    again = _request(db_session, project, "key-1")

    assert again.id == first.id
    assert _requests_on(db_session, project) == 1
    reserved = warehouse_repository.get_reserved_quantities(db_session, project.id, [("HINGE", "HG-100")])
    assert reserved[("HINGE", "HG-100")] == 4


def test_a_new_key_is_a_new_request(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)

    _request(db_session, project, "key-1")
    _request(db_session, project, "key-2")

    assert _requests_on(db_session, project) == 2


def test_a_request_key_from_another_project_is_refused(db_session):
    one, other = _project(db_session), _project(db_session)
    _stock(db_session, one)
    _stock(db_session, other)
    _request(db_session, one, "key-1")

    with pytest.raises(ValidationError) as exc:
        _request(db_session, other, "key-1")

    assert exc.value.field == "idempotency_key"


def _slip_with_line(session, project, qty=5):
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.DELIVERED,
    )
    session.add(ps)
    session.flush()
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=ps.id,
        opening_number="101",
        product_code="HG-100",
        hardware_category="HINGE",
        quantity=qty,
    )
    session.add(psi)
    session.flush()
    return ps, psi


def _return(session, slip, line, key):
    return shipping_repository.create_shipment_return(
        session,
        packing_slip_id=slip.id,
        warehouse_id=_wh(session),
        returned_by="tester",
        reference=None,
        items=[{"packing_slip_item_id": line.id, "quantity": 2, "disposition": ReturnDisposition.RETURN_TO_PROJECT}],
        idempotency_key=key,
    )


def test_a_resent_shipment_return_returns_the_first_and_books_once(db_session):
    """The issue's partial return: 2 of 5 back, reply lost, confirm again."""
    project = _project(db_session)
    slip, line = _slip_with_line(db_session, project, qty=5)

    first = _return(db_session, slip, line, "ret-1")
    again = _return(db_session, slip, line, "ret-1")

    assert again.id == first.id
    returns = db_session.scalar(
        select(func.count()).select_from(ShipmentReturn).where(ShipmentReturn.packing_slip_id == slip.id)
    )
    assert returns == 1
    booked_back = db_session.scalar(
        select(func.coalesce(func.sum(InventoryLocation.quantity), 0)).where(InventoryLocation.project_id == project.id)
    )
    assert booked_back == 2


def test_a_return_key_from_another_shipment_is_refused(db_session):
    project = _project(db_session)
    slip, line = _slip_with_line(db_session, project)
    other_slip, other_line = _slip_with_line(db_session, project)
    _return(db_session, slip, line, "ret-1")

    with pytest.raises(ValidationError) as exc:
        _return(db_session, other_slip, other_line, "ret-1")

    assert exc.value.field == "idempotency_key"


def test_a_return_without_a_key_is_unchecked(db_session):
    """A tab on the previous build sends none; each send books its own return, as before."""
    project = _project(db_session)
    slip, line = _slip_with_line(db_session, project)

    _return(db_session, slip, line, None)
    _return(db_session, slip, line, None)

    returns = db_session.scalar(
        select(func.count()).select_from(ShipmentReturn).where(ShipmentReturn.packing_slip_id == slip.id)
    )
    assert returns == 2
