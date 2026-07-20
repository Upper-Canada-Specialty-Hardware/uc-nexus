"""Pool entry/exit flows: destock, allocate-to-project, receive-to-stock, transfer."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType, DestockSource
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.stock_item import StockItem

from .common import (
    _find_or_create_stock_row,
    _log_audit_event,
    _normalize_optional_location_fields,
    _validate_location_fields,
)
from .items import get_stock_item


def destock_inventory(
    session: Session,
    *,
    inventory_location_id: uuid.UUID,
    quantity: int,
    source: DestockSource,
    reason_text: str | None,
    target_aisle: str | None,
    target_row: str | None,
    target_bay: str | None,
    performed_by: str,
) -> StockItem:
    """Move quantity units from a project's InventoryLocation row into the stock pool."""
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    _validate_location_fields(target_aisle, target_row, target_bay)

    il = session.get(InventoryLocationModel, inventory_location_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inventory_location_id} not found")
    if quantity > il.quantity:
        raise ValidationError("Destock quantity exceeds available quantity", field="quantity")

    # If DEFICIENT_SWAP, the units being destocked are the deficient ones: tighten that flag too
    is_deficient_swap = source == DestockSource.DEFICIENT_SWAP
    if is_deficient_swap:
        if quantity > (il.deficient_quantity or 0):
            raise ValidationError(
                "DEFICIENT_SWAP destock quantity exceeds deficient_quantity on source row",
                field="quantity",
            )

    # Pick target location: explicit override or fall back to source location
    final_aisle = target_aisle if target_aisle is not None else il.aisle
    final_row = target_row if target_row is not None else il.row
    final_bay = target_bay if target_bay is not None else il.bay

    now = datetime.utcnow()
    stock_row = _find_or_create_stock_row(
        session,
        warehouse_id=il.warehouse_id,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        aisle=final_aisle,
        row=final_row,
        bay=final_bay,
        received_at=now,
    )

    # Apply the move
    il.quantity -= quantity
    if is_deficient_swap:
        il.deficient_quantity = max(0, (il.deficient_quantity or 0) - quantity)
    stock_row.quantity += quantity

    session.flush()

    detail = {
        "fromInventoryLocationId": str(il.id),
        "projectId": str(il.project_id),
        "hardwareCategory": il.hardware_category,
        "productCode": il.product_code,
        "quantity": quantity,
        "source": source.value,
        "reasonText": reason_text,
        "targetLocation": {"aisle": final_aisle, "row": final_row, "bay": final_bay},
        "stockItemId": str(stock_row.id),
    }
    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.DESTOCK,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=stock_row.id,
        action=AuditAction.DESTOCK,
        performed_by=performed_by,
        detail=detail,
    )
    return stock_row


def allocate_stock_to_project(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    project_id: uuid.UUID,
    target_hardware_category: str,
    target_product_code: str,
    quantity: int,
    target_aisle: str | None,
    target_row: str | None,
    target_bay: str | None,
    performed_by: str,
) -> InventoryLocationModel:
    """Transfer `quantity` units from a stock row into a project's inventory.

    Creates an InventoryLocation whose origin is the stock_items row (stock_item_id set,
    po_line_item_id / receive_line_item_id NULL). The CHECK constraint ck_inventory_locations_has_origin
    enforces that every row has either a PO origin or a stock origin.
    """
    from app.models.project import Project as ProjectModel

    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not target_hardware_category:
        raise ValidationError("target_hardware_category is required", field="target_hardware_category")
    if not target_product_code:
        raise ValidationError("target_product_code is required", field="target_product_code")
    _validate_location_fields(target_aisle, target_row, target_bay)

    si = get_stock_item(session, stock_item_id)
    available = si.quantity - (si.deficient_quantity or 0)
    if quantity > available:
        raise ValidationError("Allocate quantity exceeds available stock", field="quantity")

    project = session.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    now = datetime.utcnow()

    new_il = InventoryLocationModel(
        project_id=project_id,
        po_line_item_id=None,
        receive_line_item_id=None,
        stock_item_id=stock_item_id,
        warehouse_id=si.warehouse_id,
        hardware_category=target_hardware_category,
        product_code=target_product_code,
        quantity=quantity,
        deficient_quantity=0,
        aisle=target_aisle,
        row=target_row,
        bay=target_bay,
        received_at=now,
    )
    session.add(new_il)

    si.quantity -= quantity
    session.flush()

    detail = {
        "sourceStockItemId": str(stock_item_id),
        "projectId": str(project_id),
        "targetHardwareCategory": target_hardware_category,
        "targetProductCode": target_product_code,
        "quantity": quantity,
        "targetLocation": {"aisle": target_aisle, "row": target_row, "bay": target_bay},
        "newInventoryLocationId": str(new_il.id),
    }
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.ALLOCATE_FROM_STOCK,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=new_il.id,
        action=AuditAction.ALLOCATE_FROM_STOCK,
        performed_by=performed_by,
        detail=detail,
    )

    # Keep empty stock rows so they can remain the origin of inventory_locations rows that were
    # allocated out of them (the ON DELETE SET NULL on stock_item_id would otherwise blank out the
    # only origin link and violate ck_inventory_locations_has_origin). get_stock_items filters
    # rows where quantity + deficient_quantity == 0 so they don't clutter the browse view.

    return new_il


def receive_into_stock(
    session: Session,
    *,
    warehouse_id: uuid.UUID | None = None,
    hardware_category: str,
    product_code: str,
    quantity: int,
    deficient_quantity: int,
    aisle: str | None,
    row: str | None,
    bay: str | None,
    received_at: datetime,
    received_by: str,
    po_number: str | None,
) -> StockItem:
    """Receive vendor PO directly into the stock pool. Used when PO has no project_id."""
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if deficient_quantity < 0 or deficient_quantity > quantity:
        raise ValidationError(
            "deficient_quantity must be 0 <= deficient_quantity <= quantity",
            field="deficient_quantity",
        )

    if warehouse_id is None:
        from app.repositories import warehouse_admin_repository

        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)

    stock_row = _find_or_create_stock_row(
        session,
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        aisle=aisle,
        row=row,
        bay=bay,
        received_at=received_at,
    )
    stock_row.quantity += quantity
    stock_row.deficient_quantity += deficient_quantity

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=stock_row.id,
        action=AuditAction.RECEIVE,
        performed_by=received_by,
        detail={
            "quantity": quantity,
            "deficientQuantity": deficient_quantity,
            "hardwareCategory": hardware_category,
            "productCode": product_code,
            "poNumber": po_number,
            "location": {"aisle": aisle, "row": row, "bay": bay},
        },
    )
    return stock_row


def _find_matching_inventory_location(
    session: Session,
    src: InventoryLocationModel,
    warehouse_id: uuid.UUID,
    aisle: str | None,
    row: str | None,
    bay: str | None,
) -> InventoryLocationModel | None:
    """An existing IL row sharing src's origin identity at the destination (warehouse, location)."""
    stmt = select(InventoryLocationModel).where(
        InventoryLocationModel.id != src.id,
        InventoryLocationModel.warehouse_id == warehouse_id,
        InventoryLocationModel.project_id == src.project_id,
        InventoryLocationModel.hardware_category == src.hardware_category,
        InventoryLocationModel.product_code == src.product_code,
        InventoryLocationModel.aisle == aisle,
        InventoryLocationModel.row == row,
        InventoryLocationModel.bay == bay,
    )
    for col, val in (
        (InventoryLocationModel.po_line_item_id, src.po_line_item_id),
        (InventoryLocationModel.receive_line_item_id, src.receive_line_item_id),
        (InventoryLocationModel.stock_item_id, src.stock_item_id),
    ):
        stmt = stmt.where(col.is_(None)) if val is None else stmt.where(col == val)
    return session.scalars(stmt).first()


def transfer_inventory(
    session: Session,
    *,
    source_type: str,
    source_id: uuid.UUID,
    quantity: int,
    dest_warehouse_id: uuid.UUID,
    dest_aisle: str,
    dest_row: str,
    dest_bay: str,
    performed_by: str,
) -> dict:
    """Move `quantity` available units from a source row to a destination location/warehouse.

    Partial + immediate. Source keeps the remainder (an InventoryLocation may sit at 0, a fully
    drained stock row is hidden by the qty>0 list filter). The destination merges into a matching
    row (same origin + location) or a new row is created. Same- and cross-warehouse use one path.
    """
    from app.models.warehouse import Warehouse

    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    if (
        not (dest_aisle and dest_aisle.strip())
        or not (dest_row and dest_row.strip())
        or not (dest_bay and dest_bay.strip())
    ):
        raise ValidationError("destination aisle, row, and bay are all required", field="destination")

    dest_aisle, dest_row, dest_bay = _normalize_optional_location_fields(dest_aisle, dest_row, dest_bay)

    dest_wh = session.get(Warehouse, dest_warehouse_id)
    if dest_wh is None:
        raise NotFoundError(f"Warehouse {dest_warehouse_id} not found")

    now = datetime.utcnow()

    if source_type == "INVENTORY_LOCATION":
        il = session.get(InventoryLocationModel, source_id)
        if il is None:
            raise NotFoundError(f"Inventory location {source_id} not found")
        available = il.quantity - (il.deficient_quantity or 0)
        if quantity > available:
            raise ValidationError("Transfer quantity exceeds available (non-deficient) quantity", field="quantity")
        if il.warehouse_id == dest_warehouse_id and (il.aisle, il.row, il.bay) == (dest_aisle, dest_row, dest_bay):
            raise ValidationError("Destination is the same as the source location", field="destination")

        from_wh, from_loc = il.warehouse_id, {"aisle": il.aisle, "row": il.row, "bay": il.bay}
        il.quantity -= quantity
        target = _find_matching_inventory_location(session, il, dest_warehouse_id, dest_aisle, dest_row, dest_bay)
        if target is not None:
            target.quantity += quantity
        else:
            target = InventoryLocationModel(
                project_id=il.project_id,
                po_line_item_id=il.po_line_item_id,
                receive_line_item_id=il.receive_line_item_id,
                stock_item_id=il.stock_item_id,
                warehouse_id=dest_warehouse_id,
                hardware_category=il.hardware_category,
                product_code=il.product_code,
                quantity=quantity,
                deficient_quantity=0,
                aisle=dest_aisle,
                row=dest_row,
                bay=dest_bay,
                received_at=now,
            )
            session.add(target)
        session.flush()
        _log_audit_event(
            session,
            project_id=il.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=il.id,
            action=AuditAction.TRANSFER,
            performed_by=performed_by,
            detail={
                "fromWarehouseId": str(from_wh),
                "fromLocation": from_loc,
                "toWarehouseId": str(dest_warehouse_id),
                "toLocation": {"aisle": dest_aisle, "row": dest_row, "bay": dest_bay},
                "quantity": quantity,
                "targetInventoryLocationId": str(target.id),
            },
        )
        return {"success": True, "quantity": quantity, "dest_warehouse_id": dest_warehouse_id}

    if source_type == "STOCK_ITEM":
        si = session.get(StockItem, source_id)
        if si is None:
            raise NotFoundError(f"Stock item {source_id} not found")
        available = si.quantity - (si.deficient_quantity or 0)
        if quantity > available:
            raise ValidationError("Transfer quantity exceeds available (non-deficient) quantity", field="quantity")
        if si.warehouse_id == dest_warehouse_id and (si.aisle, si.row, si.bay) == (dest_aisle, dest_row, dest_bay):
            raise ValidationError("Destination is the same as the source location", field="destination")

        from_wh, from_loc = si.warehouse_id, {"aisle": si.aisle, "row": si.row, "bay": si.bay}
        si.quantity -= quantity
        target = _find_or_create_stock_row(
            session,
            warehouse_id=dest_warehouse_id,
            hardware_category=si.hardware_category,
            product_code=si.product_code,
            aisle=dest_aisle,
            row=dest_row,
            bay=dest_bay,
            received_at=now,
        )
        target.quantity += quantity
        session.flush()
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.TRANSFER,
            performed_by=performed_by,
            detail={
                "fromWarehouseId": str(from_wh),
                "fromLocation": from_loc,
                "toWarehouseId": str(dest_warehouse_id),
                "toLocation": {"aisle": dest_aisle, "row": dest_row, "bay": dest_bay},
                "quantity": quantity,
                "targetStockItemId": str(target.id),
            },
        )
        return {"success": True, "quantity": quantity, "dest_warehouse_id": dest_warehouse_id}

    raise ValidationError("source_type must be INVENTORY_LOCATION or STOCK_ITEM", field="source_type")
