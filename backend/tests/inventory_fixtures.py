"""Shared row builders for the warehouse-inventory remediation suites (PR 1).

The stock-movement, deficiency, item and inventory-floor tests all need the same handful of rows: a
project, a stock-pool row, a project InventoryLocation, and - for the origin-cloning coverage - a
return-origin InventoryLocation whose only origin FK is shipment_return_item_id. Building that return
chain (packing slip -> slip item -> return -> return item) by hand in every file would bury the
assertions, so it lives here. Mirrors the inline helpers the existing suites already use.
"""

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.enums import (
    ReservationSource,
    ReturnDisposition,
    ShipmentStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.shipping import PackingSlip, PackingSlipItem, ShipmentReturn, ShipmentReturnItem
from app.models.shop_assembly import ShopAssemblyRequest
from app.models.stock_item import StockItem
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository


def wh_id(session: Session) -> uuid.UUID:
    return warehouse_admin_repository.get_primary_warehouse_id(session)


def make_project(session: Session, description: str = "Test") -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description=description)
    session.add(p)
    session.flush()
    return p


def make_stock_item(
    session: Session,
    *,
    quantity: int = 10,
    deficient: int = 0,
    category: str = "HINGE",
    code: str = "HG-100",
    aisle: str | None = None,
    row: str | None = None,
    bay: str | None = None,
    warehouse_id: uuid.UUID | None = None,
    unit_cost=None,
) -> StockItem:
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id or wh_id(session),
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
        aisle=aisle,
        row=row,
        bay=bay,
        unit_cost=unit_cost,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    return si


def make_il(
    session: Session,
    project: Project,
    *,
    quantity: int = 10,
    deficient: int = 0,
    category: str = "HINGE",
    code: str = "HG-100",
    aisle: str | None = "A",
    row: str | None = "1",
    bay: str | None = "1",
    stock_item_id: uuid.UUID | None = None,
    po_line_item_id: uuid.UUID | None = None,
    receive_line_item_id: uuid.UUID | None = None,
    shipment_return_item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    unit_cost=None,
) -> InventoryLocation:
    """A project InventoryLocation. Defaults to a stock allocation origin unless an origin FK is given."""
    if stock_item_id is None and po_line_item_id is None and shipment_return_item_id is None:
        stock_item_id = make_stock_item(session, quantity=quantity, category=category, code=code).id
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        stock_item_id=stock_item_id,
        po_line_item_id=po_line_item_id,
        receive_line_item_id=receive_line_item_id,
        shipment_return_item_id=shipment_return_item_id,
        warehouse_id=warehouse_id or wh_id(session),
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
        aisle=aisle,
        row=row,
        bay=bay,
        unit_cost=unit_cost,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def make_return_item(
    session: Session,
    project: Project,
    *,
    quantity: int = 5,
    category: str = "HINGE",
    code: str = "HG-100",
) -> ShipmentReturnItem:
    """A ShipmentReturnItem - the origin a returned-from-site InventoryLocation hangs off.

    Its whole point in these tests is to be a fourth kind of origin FK: an InventoryLocation carrying
    only shipment_return_item_id has its other three origin FKs null, so any code that clones origin
    or matches on it has to handle this column or the has-origin CHECK bites.
    """
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.DELIVERED,
    )
    session.add(slip)
    session.flush()
    psi = PackingSlipItem(
        id=uuid.uuid4(),
        packing_slip_id=slip.id,
        opening_number="101",
        product_code=code,
        hardware_category=category,
        quantity=quantity,
    )
    session.add(psi)
    session.flush()
    ret = ShipmentReturn(
        id=uuid.uuid4(),
        packing_slip_id=slip.id,
        warehouse_id=wh_id(session),
        returned_by="tester",
        returned_at=datetime.utcnow(),
    )
    session.add(ret)
    session.flush()
    item = ShipmentReturnItem(
        id=uuid.uuid4(),
        shipment_return_id=ret.id,
        packing_slip_item_id=psi.id,
        disposition=ReturnDisposition.RETURN_TO_PROJECT,
        quantity=quantity,
        hardware_category=category,
        product_code=code,
    )
    session.add(item)
    session.flush()
    return item


def make_reservation(
    session: Session,
    project: Project,
    *,
    quantity: int,
    category: str = "HINGE",
    code: str = "HG-100",
) -> ShopAssemblyRequest:
    """An active shop-assembly reservation claiming `quantity` of one combo in a project.

    Mints a real PENDING ShopAssemblyRequest to hang the claim off - the reservation CHECK constraint
    requires a request FK - and writes the claim through the same repository call request creation
    uses. Returns the request so a caller can release it if it wants to.
    """
    sar = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=f"SA-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=ShopAssemblyRequestStatus.PENDING,
        created_by="tester",
    )
    session.add(sar)
    session.flush()
    warehouse_repository.create_reservations(
        session,
        project.id,
        ReservationSource.SHOP_ASSEMBLY_REQUEST,
        sar.id,
        [(category, code, quantity)],
    )
    return sar
