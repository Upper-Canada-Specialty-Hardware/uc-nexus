"""Inventory audit log: shared write helper + query."""

import uuid

from sqlalchemy import ColumnElement, String, and_, cast, or_, select
from sqlalchemy.orm import Session

from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType


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
    """Insert a row into inventory_audit_log."""
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


def audit_scope(company: str) -> ColumnElement[bool]:
    """The tenant filter for an audit read (#637, #1045).

    A row with a project belongs to that project's company. A row with no project is a stock event
    (every project-less write is a STOCK_ITEM row), and stock belongs to its WAREHOUSE, so it is kept
    when the stock item's warehouse is in the company.

    #1574: a stock row folded into another on its shelf is usually deleted, and with it went the only
    way to attribute its entries - the fold itself, and the row's whole past, vanished from every
    scoped view. An entry that recorded where it happened (`location_detail` stamps the warehouse into
    fromLocation / toLocation / location) is kept by that warehouse too, so a deleted row's moves,
    put-aways and receipts stay visible to its company. Entries with no location on a deleted row (an
    adjust, a reclassify) still drop - they name no warehouse to attribute them with."""
    from app.models.stock_item import StockItem
    from app.models.warehouse import Warehouse
    from app.repositories import tenancy

    company_warehouses = select(cast(Warehouse.id, String)).where(Warehouse.company == company)
    recorded_in_company = or_(
        *(
            InventoryAuditLog.detail[key]["warehouseId"].astext.in_(company_warehouses)
            for key in ("fromLocation", "toLocation", "location")
        )
    )
    return or_(
        InventoryAuditLog.project_id.in_(tenancy.project_ids_for(company)),
        and_(
            InventoryAuditLog.project_id.is_(None),
            InventoryAuditLog.entity_type == AuditEntityType.STOCK_ITEM,
            or_(
                InventoryAuditLog.entity_id.in_(
                    select(StockItem.id).where(StockItem.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
                ),
                recorded_in_company,
            ),
        ),
    )


def get_audit_log(
    session: Session,
    entity_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    *,
    company: str | None = None,
    before_id: uuid.UUID | None = None,
) -> list[InventoryAuditLog]:
    """Query audit log entries, optionally filtered by entity, type, or project. `offset` pages.

    A scoped caller (#637) sees only their own company's rows: job rows through the project, stock
    rows through the stock item's warehouse (see audit_scope).

    Ordered newest first with the id as a tiebreak, and `before_id` pages by keyset (#1269): the next
    page is everything strictly older than the last entry shown. An offset shifted when a new entry
    landed between pages (the last row repeated), and equal timestamps from one loop's writes could
    swap across a page boundary (one repeated, one never shown)."""
    stmt = select(InventoryAuditLog).order_by(InventoryAuditLog.created_at.desc(), InventoryAuditLog.id.desc())
    if before_id is not None:
        cursor_at = select(InventoryAuditLog.created_at).where(InventoryAuditLog.id == before_id).scalar_subquery()
        stmt = stmt.where(
            or_(
                InventoryAuditLog.created_at < cursor_at,
                and_(InventoryAuditLog.created_at == cursor_at, InventoryAuditLog.id < before_id),
            )
        )
    if entity_id is not None:
        stmt = stmt.where(InventoryAuditLog.entity_id == entity_id)
    if entity_type is not None:
        stmt = stmt.where(InventoryAuditLog.entity_type == entity_type)
    if project_id is not None:
        stmt = stmt.where(InventoryAuditLog.project_id == project_id)
    if company is not None:
        stmt = stmt.where(audit_scope(company))
    stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).all())
