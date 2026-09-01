"""Deficiency reporting, the review queue, and resolution flows."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    DeficiencyResolution,
    DeficientItemSource,
    DestockSource,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.stock_item import StockItem

from .common import _find_or_create_stock_row, _log_audit_event
from .items import get_stock_item


def report_inventory_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> InventoryLocationModel:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    il = session.get(InventoryLocationModel, inventory_location_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inventory_location_id} not found")

    new_deficient = (il.deficient_quantity or 0) + quantity
    if new_deficient > il.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    il.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": il.hardware_category,
            "productCode": il.product_code,
        },
    )
    return il


def report_stock_deficiency(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> StockItem:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    si = get_stock_item(session, stock_item_id)
    new_deficient = (si.deficient_quantity or 0) + quantity
    if new_deficient > si.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    si.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": si.hardware_category,
            "productCode": si.product_code,
        },
    )
    return si


def resolve_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID | None,
    stock_item_id: uuid.UUID | None,
    resolution: DeficiencyResolution,
    quantity: int,
    reason_text: str | None,
    rma_reference: str | None,
    destock_source: DestockSource | None,
    reviewed_by: str,
):
    """Resolve a deficient batch. Exactly one of inventory_location_id / stock_item_id is set."""
    from app.models.deficiency_review import DeficiencyReview

    if (inventory_location_id is None) == (stock_item_id is None):
        raise ValidationError(
            "Exactly one of inventory_location_id / stock_item_id must be provided",
            field="source",
        )
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not reviewed_by:
        raise ValidationError("reviewed_by is required", field="reviewed_by")
    if resolution == DeficiencyResolution.RETURN_TO_VENDOR and not rma_reference:
        raise ValidationError(
            "rma_reference is required when resolution is RETURN_TO_VENDOR",
            field="rma_reference",
        )
    if resolution == DeficiencyResolution.SEND_TO_STOCK and destock_source is None:
        # default to DEFICIENT_SWAP for project sources if not specified
        destock_source = DestockSource.DEFICIENT_SWAP

    resulting_stock_item_id: uuid.UUID | None = None
    project_for_audit: uuid.UUID | None = None
    hardware_category: str
    product_code: str

    if inventory_location_id is not None:
        il = session.get(InventoryLocationModel, inventory_location_id)
        if il is None:
            raise NotFoundError(f"Inventory location {inventory_location_id} not found")
        if quantity > (il.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        project_for_audit = il.project_id
        hardware_category = il.hardware_category
        product_code = il.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
            stock_row = _find_or_create_stock_row(
                session,
                warehouse_id=il.warehouse_id,
                hardware_category=il.hardware_category,
                product_code=il.product_code,
                aisle=il.aisle,
                row=il.row,
                bay=il.bay,
                received_at=datetime.utcnow(),
            )
            stock_row.quantity += quantity
            stock_row.deficient_quantity += quantity
            # Carry an off-PO cost back to the pool row, exactly as destock_inventory does - without
            # it a migrated unit resolved through here values at zero forever. Fills a null only.
            if il.unit_cost is not None and stock_row.unit_cost is None:
                stock_row.unit_cost = il.unit_cost
            resulting_stock_item_id = stock_row.id
        elif resolution == DeficiencyResolution.SCRAP:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

    else:
        si = get_stock_item(session, stock_item_id)
        if quantity > (si.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        hardware_category = si.hardware_category
        product_code = si.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            # Already on stock — for parity record a re-routing into a (possibly new) row.
            # Practically, leave on the same row but clear the deficient flag
            si.deficient_quantity -= quantity
            resulting_stock_item_id = si.id
        elif resolution == DeficiencyResolution.SCRAP:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

        # Keep empty stock rows for the same reason allocate does — see comment there.

    review = DeficiencyReview(
        inventory_location_id=inventory_location_id,
        stock_item_id=stock_item_id,
        resolution=resolution,
        quantity=quantity,
        reason_text=reason_text,
        rma_reference=rma_reference,
        reviewed_by=reviewed_by,
        resulting_stock_item_id=resulting_stock_item_id,
    )
    session.add(review)
    session.flush()

    detail = {
        "resolution": resolution.value,
        "quantity": quantity,
        "reasonText": reason_text,
        "rmaReference": rma_reference,
        "destockSource": destock_source.value if destock_source else None,
        "resultingStockItemId": str(resulting_stock_item_id) if resulting_stock_item_id else None,
        "hardwareCategory": hardware_category,
        "productCode": product_code,
    }
    if inventory_location_id is not None:
        _log_audit_event(
            session,
            project_id=project_for_audit,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=inventory_location_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )
    if stock_item_id is not None:
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=stock_item_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )

    return review


def get_deficient_items(
    session: Session,
    project_id: uuid.UUID | None = None,
    source: DeficientItemSource | None = None,
    *,
    company: str | None = None,
) -> list[dict]:
    from app.repositories import tenancy

    rows: list[dict] = []

    if source is None or source == DeficientItemSource.PROJECT_INVENTORY:
        il_stmt = select(InventoryLocationModel).where(InventoryLocationModel.deficient_quantity > 0)
        if project_id is not None:
            il_stmt = il_stmt.where(InventoryLocationModel.project_id == project_id)
        if company is not None:
            il_stmt = il_stmt.where(InventoryLocationModel.project_id.in_(tenancy.project_ids_for(company)))
        il_stmt = il_stmt.order_by(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
        for il in session.scalars(il_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.PROJECT_INVENTORY,
                    "inventory_location_id": il.id,
                    "stock_item_id": None,
                    "project_id": il.project_id,
                    "hardware_category": il.hardware_category,
                    "product_code": il.product_code,
                    "deficient_quantity": il.deficient_quantity,
                    "aisle": il.aisle,
                    "row": il.row,
                    "bay": il.bay,
                }
            )

    if (source is None or source == DeficientItemSource.STOCK_POOL) and project_id is None:
        si_stmt = (
            select(StockItem)
            .where(StockItem.deficient_quantity > 0)
            .order_by(StockItem.hardware_category, StockItem.product_code)
        )
        if company is not None:
            si_stmt = si_stmt.where(StockItem.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
        for si in session.scalars(si_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.STOCK_POOL,
                    "inventory_location_id": None,
                    "stock_item_id": si.id,
                    "project_id": None,
                    "hardware_category": si.hardware_category,
                    "product_code": si.product_code,
                    "deficient_quantity": si.deficient_quantity,
                    "aisle": si.aisle,
                    "row": si.row,
                    "bay": si.bay,
                }
            )
    return rows


def get_deficiency_reviews(
    session: Session,
    inventory_location_id: uuid.UUID | None = None,
    stock_item_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    *,
    company: str | None = None,
) -> list:
    from app.models.deficiency_review import DeficiencyReview
    from app.repositories import tenancy

    stmt = select(DeficiencyReview).order_by(DeficiencyReview.reviewed_at.desc())
    if inventory_location_id is not None:
        stmt = stmt.where(DeficiencyReview.inventory_location_id == inventory_location_id)
    if stock_item_id is not None:
        stmt = stmt.where(DeficiencyReview.stock_item_id == stock_item_id)
    if project_id is not None:
        # Project-scoped reviews join through inventory_locations
        il_ids = select(InventoryLocationModel.id).where(InventoryLocationModel.project_id == project_id)
        stmt = stmt.where(
            or_(
                DeficiencyReview.inventory_location_id.in_(il_ids),
                # also include any review whose resulting stock item came from a project row
                # (covered by inventory_location_id above; pure stock-side reviews don't have a project)
            )
        )
    if company is not None:
        # A review hangs off either an inventory row (project-scoped) or a stock row
        # (warehouse-scoped), so both sides are narrowed and a review that names neither drops out
        # rather than being visible to every tenant (#637).
        stmt = stmt.where(
            or_(
                DeficiencyReview.inventory_location_id.in_(
                    select(InventoryLocationModel.id).where(
                        InventoryLocationModel.project_id.in_(tenancy.project_ids_for(company))
                    )
                ),
                DeficiencyReview.stock_item_id.in_(
                    select(StockItem.id).where(StockItem.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
                ),
            )
        )
    return list(session.scalars(stmt).all())
