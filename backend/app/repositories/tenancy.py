"""Row-level tenant scoping (#637): whose company owns a row, and may this caller touch it.

Five tables carry a `company` column - projects, warehouses, purchase_orders, inventory_item_types,
shipment_methods. Everything else in the schema inherits its tenant from one of those two roots:
openings, hardware, inventory locations, reservations, pull requests, shipping and assembly requests,
packing slips, containers and buyer assignments through their PROJECT; warehouse locations, stock
items and receive drafts through their WAREHOUSE. That is deliberate - duplicating the column onto
every child table would create two answers to "whose row is this" and no way to keep them agreeing -
and it is what this module encapsulates, so no resolver has to know which join answers the question.

Two shapes, and they are used in different places.

  - `*_ids_for(company)` is a subquery for LIST reads: `Model.project_id.in_(project_ids_for(scope))`
    filters a whole result set in the same statement, with no extra round trip.
  - `require_*_in_scope(...)` is the BY-ID check every mutation and detail read makes before acting.

Both refuse with **NotFoundError, never ForbiddenError**. A forbidden answer confirms the row exists,
which turns any id-taking field into an oracle: ask for a UUID, and "forbidden" versus "not found"
tells you whether another company holds it. There is nothing a caller can do with that answer except
enumerate, so out-of-scope reads the same as absent.

`scope` is None for an Admin/Manager (see app/auth.tenant_scope), and None means "no restriction" -
every function here is a no-op for it rather than a filter that happens to match everything.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import CustomInventoryItem, InventoryItemAttribute, InventoryItemType
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.purchase_order import PODocument, POLineItem, PurchaseOrder
from app.models.receive_draft import ReceiveDraft
from app.models.shipment_container import ShipmentContainer
from app.models.shipment_method import ShipmentMethod
from app.models.shipping import PackingSlip, ShipmentReturn
from app.models.shipping_out_request import ShippingOutRequest
from app.models.shop_assembly import ShopAssemblyRequest
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation


def project_ids_for(company: str) -> Select:
    """Subquery of every project id in one company, for filtering a project-linked list read."""
    return select(Project.id).where(Project.company == company)


def warehouse_ids_for(company: str) -> Select:
    """Subquery of every warehouse id in one company, for filtering a warehouse-linked list read."""
    return select(Warehouse.id).where(Warehouse.company == company)


def _require(session: Session, company_stmt: Select, scope: str | None, label: str, entity_id) -> None:
    """The one refusal path. A row that does not exist and a row belonging to another company are the
    same answer on purpose - see the module docstring."""
    if scope is None:
        return
    owner = session.scalar(company_stmt)
    if owner != scope:
        raise NotFoundError(f"{label} {entity_id} not found")


def require_project_in_scope(session: Session, project_id: uuid.UUID | None, scope: str | None) -> None:
    """A None project_id is a no-op: a stock PO, a jobless receive and an unscoped location read all
    legitimately have no project, and refusing them here would break the stock pipeline for every
    non-admin rather than scoping it."""
    if project_id is None:
        return
    _require(
        session,
        select(Project.company).where(Project.id == project_id),
        scope,
        "Project",
        project_id,
    )


def require_warehouse_in_scope(session: Session, warehouse_id: uuid.UUID | None, scope: str | None) -> None:
    if warehouse_id is None:
        return
    _require(
        session,
        select(Warehouse.company).where(Warehouse.id == warehouse_id),
        scope,
        "Warehouse",
        warehouse_id,
    )


def require_po_in_scope(session: Session, po_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(PurchaseOrder.company).where(PurchaseOrder.id == po_id),
        scope,
        "Purchase order",
        po_id,
    )


def require_po_line_item_in_scope(session: Session, line_item_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(PurchaseOrder.company)
        .join(POLineItem, POLineItem.po_id == PurchaseOrder.id)
        .where(POLineItem.id == line_item_id),
        scope,
        "PO line item",
        line_item_id,
    )


def require_po_document_in_scope(session: Session, document_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(PurchaseOrder.company)
        .join(PODocument, PODocument.po_id == PurchaseOrder.id)
        .where(PODocument.id == document_id),
        scope,
        "PO document",
        document_id,
    )


def require_inventory_location_in_scope(session: Session, inventory_location_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(InventoryLocation, InventoryLocation.project_id == Project.id)
        .where(InventoryLocation.id == inventory_location_id),
        scope,
        "Inventory row",
        inventory_location_id,
    )


def require_stock_item_in_scope(session: Session, stock_item_id: uuid.UUID, scope: str | None) -> None:
    """Stock is jobless by definition, so it scopes through its WAREHOUSE rather than a project."""
    _require(
        session,
        select(Warehouse.company)
        .join(StockItem, StockItem.warehouse_id == Warehouse.id)
        .where(StockItem.id == stock_item_id),
        scope,
        "Stock item",
        stock_item_id,
    )


def require_pull_request_in_scope(session: Session, pull_request_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(PullRequest, PullRequest.project_id == Project.id)
        .where(PullRequest.id == pull_request_id),
        scope,
        "Pull request",
        pull_request_id,
    )


def require_receive_draft_in_scope(session: Session, draft_id: uuid.UUID, scope: str | None) -> None:
    """A draft is scoped through the PO it counts against, not its warehouse: warehouse_id is nullable
    on a draft, while the PO is what the receive is FOR and always carries a company."""
    _require(
        session,
        select(PurchaseOrder.company)
        .join(ReceiveDraft, ReceiveDraft.po_id == PurchaseOrder.id)
        .where(ReceiveDraft.id == draft_id),
        scope,
        "Receive draft",
        draft_id,
    )


def require_shipping_out_request_in_scope(session: Session, request_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(ShippingOutRequest, ShippingOutRequest.project_id == Project.id)
        .where(ShippingOutRequest.id == request_id),
        scope,
        "Shipping request",
        request_id,
    )


def require_shop_assembly_request_in_scope(session: Session, request_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(ShopAssemblyRequest, ShopAssemblyRequest.project_id == Project.id)
        .where(ShopAssemblyRequest.id == request_id),
        scope,
        "Shop assembly request",
        request_id,
    )


def require_packing_slip_in_scope(session: Session, packing_slip_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(PackingSlip, PackingSlip.project_id == Project.id)
        .where(PackingSlip.id == packing_slip_id),
        scope,
        "Packing slip",
        packing_slip_id,
    )


def require_shipment_return_in_scope(session: Session, return_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Warehouse.company)
        .join(ShipmentReturn, ShipmentReturn.warehouse_id == Warehouse.id)
        .where(ShipmentReturn.id == return_id),
        scope,
        "Shipment return",
        return_id,
    )


def require_container_in_scope(session: Session, container_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Project.company)
        .join(ShipmentContainer, ShipmentContainer.project_id == Project.id)
        .where(ShipmentContainer.id == container_id),
        scope,
        "Container",
        container_id,
    )


def require_warehouse_location_in_scope(session: Session, location_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(Warehouse.company)
        .join(WarehouseLocation, WarehouseLocation.warehouse_id == Warehouse.id)
        .where(WarehouseLocation.id == location_id),
        scope,
        "Warehouse location",
        location_id,
    )


def require_item_type_in_scope(session: Session, type_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(InventoryItemType.company).where(InventoryItemType.id == type_id),
        scope,
        "Inventory item type",
        type_id,
    )


def require_item_attribute_in_scope(session: Session, attribute_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(InventoryItemType.company)
        .join(InventoryItemAttribute, InventoryItemAttribute.type_id == InventoryItemType.id)
        .where(InventoryItemAttribute.id == attribute_id),
        scope,
        "Inventory item attribute",
        attribute_id,
    )


def require_custom_item_in_scope(session: Session, item_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(InventoryItemType.company)
        .join(CustomInventoryItem, CustomInventoryItem.type_id == InventoryItemType.id)
        .where(CustomInventoryItem.id == item_id),
        scope,
        "Custom inventory item",
        item_id,
    )


def require_shipment_method_in_scope(session: Session, method_id: uuid.UUID, scope: str | None) -> None:
    _require(
        session,
        select(ShipmentMethod.company).where(ShipmentMethod.id == method_id),
        scope,
        "Shipment method",
        method_id,
    )
