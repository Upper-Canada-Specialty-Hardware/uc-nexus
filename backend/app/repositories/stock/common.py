"""Shared internals for the stock package: audit writes, location validation, row find-or-create."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.models.stock_item import StockItem
from app.repositories.warehouse import normalize_location_value


def _log_audit_event(
    session: Session,
    *,
    project_id: uuid.UUID | None,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID,
    action: AuditAction,
    performed_by: str,
    detail: dict | None = None,
) -> None:
    """Insert a row into inventory_audit_log. Project_id is null for pure stock-pool events."""
    session.add(
        InventoryAuditLog(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail=detail,
            performed_by=performed_by,
        )
    )


def _validate_location_fields(aisle: str | None, bay: str | None, bin: str | None) -> None:
    """Validate aisle, bay, bin lengths when provided."""
    for field_name, value in [("aisle", aisle), ("bay", bay), ("bin", bin)]:
        if value is not None and (len(value) < 1 or len(value) > 20):
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)


def _normalize_optional_location_fields(
    aisle: str | None, bay: str | None, bin: str | None
) -> tuple[str | None, str | None, str | None]:
    """Normalize each optional field then re-validate. Returns canonical triple (nullable)."""
    a = normalize_location_value(aisle)
    b = normalize_location_value(bay)
    c = normalize_location_value(bin)
    _validate_location_fields(a, b, c)
    return (a, b, c)


def _find_or_create_stock_row(
    session: Session,
    *,
    warehouse_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    aisle: str | None,
    bay: str | None,
    bin: str | None,
    received_at: datetime,
) -> StockItem:
    """Find an existing stock row matching (warehouse, category, code, aisle, bay, bin) or create one with qty=0.

    Caller is responsible for incrementing quantity and writing audit events. Location fields are
    normalized here so writes from any entry path (destock, allocate, receive) match canonical form.
    """
    aisle = normalize_location_value(aisle)
    bay = normalize_location_value(bay)
    bin = normalize_location_value(bin)

    stmt = select(StockItem).where(
        StockItem.warehouse_id == warehouse_id,
        StockItem.hardware_category == hardware_category,
        StockItem.product_code == product_code,
    )
    if aisle is None:
        stmt = stmt.where(StockItem.aisle.is_(None))
    else:
        stmt = stmt.where(StockItem.aisle == aisle)
    if bay is None:
        stmt = stmt.where(StockItem.bay.is_(None))
    else:
        stmt = stmt.where(StockItem.bay == bay)
    if bin is None:
        stmt = stmt.where(StockItem.bin.is_(None))
    else:
        stmt = stmt.where(StockItem.bin == bin)

    existing = session.scalars(stmt).first()
    if existing is not None:
        return existing

    new_row = StockItem(
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=0,
        deficient_quantity=0,
        aisle=aisle,
        bay=bay,
        bin=bin,
        received_at=received_at,
    )
    session.add(new_row)
    session.flush()
    return new_row
