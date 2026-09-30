"""Shared internals for the stock package: audit writes, location validation, row find-or-create."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, func, literal, select
from sqlalchemy.orm import Session

from app.errors import ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType, DestockCost, PoolKind
from app.models.inventory import InventoryLocation as InventoryLocationModel
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


def _validate_location_fields(aisle: str | None, row: str | None, bay: str | None) -> None:
    """Validate aisle, row, bay lengths when provided."""
    for field_name, value in [("aisle", aisle), ("row", row), ("bay", bay)]:
        if value is not None and (len(value) < 1 or len(value) > 20):
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)


def _normalize_optional_location_fields(
    aisle: str | None, row: str | None, bay: str | None
) -> tuple[str | None, str | None, str | None]:
    """Normalize each optional field then re-validate. Returns canonical triple (nullable)."""
    a = normalize_location_value(aisle)
    b = normalize_location_value(row)
    c = normalize_location_value(bay)
    _validate_location_fields(a, b, c)
    return (a, b, c)


def pool_unit_cost(unit_cost: Decimal | float | int | None) -> Decimal:
    """A price as the pool keys on it: null is $0, and every value is a Decimal at the
    column's own scale (Numeric(19, 5)), so a price compares equal to the one the row stored."""
    if unit_cost is None:
        return Decimal("0")
    return Decimal(str(unit_cost)).quantize(Decimal("0.00001"))


def destock_unit_cost(session: Session, il: InventoryLocationModel, destock_cost: DestockCost | None) -> Decimal | None:
    """The price project units carry into the pool, as the person moving them chose (#942).

    The choice is required and has no default: ZERO is hardware left behind on a job, worth $0 to the
    pool; KEEP is the units' own effective price - their PO line's unit cost, else the row's own
    unit_cost, else $0 (None).
    """
    if destock_cost is None:
        raise ValidationError(
            "Choose what the units cost in the pool: left behind ($0) or keeps its cost",
            field="destock_cost",
        )
    if destock_cost == DestockCost.ZERO:
        return None
    if il.po_line_item_id is not None:
        from app.models.purchase_order import POLineItem

        line = session.get(POLineItem, il.po_line_item_id)
        if line is not None and line.unit_cost is not None:
            return line.unit_cost
    return il.unit_cost


def _find_stock_row(
    session: Session,
    *,
    warehouse_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    aisle: str | None,
    row: str | None,
    bay: str | None,
    kind: PoolKind = PoolKind.STOCK,
    unit_cost: Decimal | None = None,
) -> StockItem | None:
    """The pool row matching (warehouse, category, code, aisle, row, bay, kind, unit cost), or None.

    The kind is part of the key (#832): a stock row and an overhead row of the same product on the
    same shelf are two rows and never merge. So is the price (#942): a pool row holds one unit cost,
    so units at different prices - priced and $0 above all - never stack into one row. Null and zero
    both mean $0 and match each other. Location fields are normalized here so writes from any entry
    path (destock, allocate, receive) match canonical form.
    """
    aisle = normalize_location_value(aisle)
    row = normalize_location_value(row)
    bay = normalize_location_value(bay)

    stmt = select(StockItem).where(
        StockItem.warehouse_id == warehouse_id,
        StockItem.hardware_category == hardware_category,
        StockItem.product_code == product_code,
        StockItem.kind == kind,
        func.coalesce(StockItem.unit_cost, 0) == literal(pool_unit_cost(unit_cost), Numeric(19, 5)),
    )
    if aisle is None:
        stmt = stmt.where(StockItem.aisle.is_(None))
    else:
        stmt = stmt.where(StockItem.aisle == aisle)
    if row is None:
        stmt = stmt.where(StockItem.row.is_(None))
    else:
        stmt = stmt.where(StockItem.row == row)
    if bay is None:
        stmt = stmt.where(StockItem.bay.is_(None))
    else:
        stmt = stmt.where(StockItem.bay == bay)
    return session.scalars(stmt).first()


def _find_or_create_stock_row(
    session: Session,
    *,
    warehouse_id: uuid.UUID,
    hardware_category: str,
    product_code: str,
    aisle: str | None,
    row: str | None,
    bay: str | None,
    received_at: datetime,
    kind: PoolKind = PoolKind.STOCK,
    unit_cost: Decimal | None = None,
) -> StockItem:
    """Find an existing pool row matching (warehouse, category, code, aisle, row, bay, kind, unit cost)
    or create one with qty=0 at that cost.

    `kind` defaults to STOCK because every route into the pool lands as stock except a receive off an
    overhead PO (#832); moves of an existing row (transfer, reclassify split) pass the row's own kind so
    the units keep it. `unit_cost` is the moved units' own price (#942), so the row found already
    carries it and no caller ever has to reconcile two prices. Caller is responsible for incrementing
    quantity and writing audit events.
    """
    existing = _find_stock_row(
        session,
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        aisle=aisle,
        row=row,
        bay=bay,
        kind=kind,
        unit_cost=unit_cost,
    )
    if existing is not None:
        return existing

    new_row = StockItem(
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=0,
        deficient_quantity=0,
        aisle=normalize_location_value(aisle),
        row=normalize_location_value(row),
        bay=normalize_location_value(bay),
        kind=kind,
        unit_cost=unit_cost,
        received_at=received_at,
    )
    session.add(new_row)
    session.flush()
    return new_row
