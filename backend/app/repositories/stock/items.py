"""Stock item reads + in-pool corrections (adjust, move, locate, reclassify)."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType
from app.models.stock_item import StockItem
from app.repositories.warehouse import location_detail, normalize_location_value

from .common import _find_or_create_stock_row, _log_audit_event, _validate_location_fields


def get_stock_items(
    session: Session,
    product_code_contains: str | None = None,
    hardware_category: str | None = None,
    aisle: str | None = None,
    only_deficient: bool = False,
    warehouse_id: uuid.UUID | None = None,
) -> list[StockItem]:
    """List stock_items optionally filtered by product code, category, aisle, or deficient-only.

    Hides fully-emptied rows (quantity = 0 AND deficient_quantity = 0). These rows are kept in the
    DB so they can remain the origin of any inventory_locations row that was allocated out of them
    (the FK SET NULL would otherwise blank out the only origin link).
    """
    stmt = (
        select(StockItem)
        .where(StockItem.quantity + StockItem.deficient_quantity > 0)
        .order_by(
            StockItem.hardware_category.asc(),
            StockItem.product_code.asc(),
            StockItem.received_at.asc(),
        )
    )
    if product_code_contains:
        stmt = stmt.where(StockItem.product_code.ilike(f"%{product_code_contains}%"))
    if hardware_category:
        stmt = stmt.where(StockItem.hardware_category == hardware_category)
    if aisle:
        stmt = stmt.where(StockItem.aisle == aisle)
    if only_deficient:
        stmt = stmt.where(StockItem.deficient_quantity > 0)
    if warehouse_id is not None:
        stmt = stmt.where(StockItem.warehouse_id == warehouse_id)
    return list(session.scalars(stmt).all())


def get_stock_item(session: Session, stock_item_id: uuid.UUID) -> StockItem:
    si = session.get(StockItem, stock_item_id)
    if si is None:
        raise NotFoundError(f"Stock item {stock_item_id} not found")
    return si


def adjust_stock_quantity(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_quantity: int,
    reason_text: str,
    performed_by: str,
) -> StockItem:
    """Set stock_item.quantity to an absolute value (recount / write-off). reason required."""
    if not reason_text or len(reason_text) > 500:
        raise ValidationError("reason_text must be 1-500 characters", field="reason_text")
    if new_quantity < 0:
        raise ValidationError("new_quantity must be >= 0", field="new_quantity")

    si = get_stock_item(session, stock_item_id)

    # Honor the deficient_quantity <= quantity invariant by clamping if needed
    if new_quantity < si.deficient_quantity:
        raise ValidationError(
            "Cannot set quantity below current deficient_quantity",
            field="new_quantity",
        )

    old_quantity = si.quantity
    si.quantity = new_quantity

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail={
            "oldQuantity": old_quantity,
            "newQuantity": new_quantity,
            "adjustment": new_quantity - old_quantity,
            "reasonText": reason_text,
        },
    )
    return si


def move_stock_location(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_aisle: str,
    new_row: str,
    new_bay: str,
    performed_by: str,
) -> StockItem:
    if new_aisle is None or new_row is None or new_bay is None:
        raise ValidationError("new aisle/row/bay are required", field="location")
    new_aisle = normalize_location_value(new_aisle) or ""
    new_row = normalize_location_value(new_row) or ""
    new_bay = normalize_location_value(new_bay) or ""
    _validate_location_fields(new_aisle, new_row, new_bay)

    si = get_stock_item(session, stock_item_id)
    old = location_detail(si.aisle, si.row, si.bay, si.warehouse_id)
    si.aisle = new_aisle
    si.row = new_row
    si.bay = new_bay

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.MOVE,
        performed_by=performed_by,
        detail={"fromLocation": old, "toLocation": location_detail(new_aisle, new_row, new_bay, si.warehouse_id)},
    )
    return si


def mark_stock_item_unlocated(session: Session, *, stock_item_id: uuid.UUID, performed_by: str) -> StockItem:
    """Clear the aisle/row/bay on a StockItem."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    si = get_stock_item(session, stock_item_id)
    old = location_detail(si.aisle, si.row, si.bay, si.warehouse_id)
    si.aisle = None
    si.row = None
    si.bay = None
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.UNLOCATE,
        performed_by=performed_by,
        detail={"fromLocation": old},
    )
    return si


def assign_stock_item_location(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    aisle: str,
    row: str,
    bay: str,
    performed_by: str,
) -> StockItem:
    """Assign aisle/row/bay to a StockItem (initial put-away or re-locate after unlocate)."""
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")
    aisle = normalize_location_value(aisle) or ""
    row = normalize_location_value(row) or ""
    bay = normalize_location_value(bay) or ""
    _validate_location_fields(aisle, row, bay)
    si = get_stock_item(session, stock_item_id)
    si.aisle = aisle
    si.row = row
    si.bay = bay
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"toLocation": location_detail(aisle, row, bay, si.warehouse_id)},
    )
    return si


def reclassify_stock_item(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    new_hardware_category: str,
    new_product_code: str,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> tuple[StockItem, StockItem | None]:
    """Change (category, code) on `quantity` units. If quantity < total, original keeps remainder.

    Returns (reclassified_row, original_row_or_none).
    """
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not new_hardware_category:
        raise ValidationError("new_hardware_category is required", field="new_hardware_category")
    if not new_product_code:
        raise ValidationError("new_product_code is required", field="new_product_code")

    si = get_stock_item(session, stock_item_id)
    if quantity > si.quantity:
        raise ValidationError("Reclassify quantity exceeds stock quantity", field="quantity")

    # Disallow reclassifying deficient units — those must be resolved first
    available = si.quantity - (si.deficient_quantity or 0)
    if quantity > available:
        raise ValidationError(
            "Cannot reclassify deficient units; resolve deficiency first",
            field="quantity",
        )

    now = datetime.utcnow()

    if quantity == si.quantity:
        # Full reclassify in place
        old_cat = si.hardware_category
        old_code = si.product_code
        si.hardware_category = new_hardware_category
        si.product_code = new_product_code
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.RECLASSIFY,
            performed_by=performed_by,
            detail={
                "from": {"hardwareCategory": old_cat, "productCode": old_code},
                "to": {
                    "hardwareCategory": new_hardware_category,
                    "productCode": new_product_code,
                },
                "quantity": quantity,
                "reasonText": reason_text,
            },
        )
        return (si, None)

    # Split: original keeps (qty - split), new row gets `quantity` at the new (cat, code)
    si.quantity -= quantity
    new_row = _find_or_create_stock_row(
        session,
        warehouse_id=si.warehouse_id,
        hardware_category=new_hardware_category,
        product_code=new_product_code,
        aisle=si.aisle,
        row=si.row,
        bay=si.bay,
        received_at=now,
    )
    new_row.quantity += quantity

    session.flush()

    detail = {
        "originalStockItemId": str(si.id),
        "newStockItemId": str(new_row.id),
        "from": {"hardwareCategory": si.hardware_category, "productCode": si.product_code},
        "to": {"hardwareCategory": new_hardware_category, "productCode": new_product_code},
        "quantity": quantity,
        "reasonText": reason_text,
    }
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.RECLASSIFY,
        performed_by=performed_by,
        detail=detail,
    )
    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=new_row.id,
        action=AuditAction.RECLASSIFY,
        performed_by=performed_by,
        detail=detail,
    )
    return (new_row, si)
