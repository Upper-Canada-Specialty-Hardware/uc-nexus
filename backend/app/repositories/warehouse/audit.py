"""Inventory audit log: shared write helper + query."""

import uuid

from sqlalchemy import ColumnElement, and_, or_, select
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
    when the stock item's warehouse is in the company. A stock row whose item no longer exists has
    nothing left to attribute it with and drops out."""
    from app.models.stock_item import StockItem
    from app.repositories import tenancy

    return or_(
        InventoryAuditLog.project_id.in_(tenancy.project_ids_for(company)),
        and_(
            InventoryAuditLog.project_id.is_(None),
            InventoryAuditLog.entity_type == AuditEntityType.STOCK_ITEM,
            InventoryAuditLog.entity_id.in_(
                select(StockItem.id).where(StockItem.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
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
) -> list[InventoryAuditLog]:
    """Query audit log entries, optionally filtered by entity, type, or project. `offset` pages.

    A scoped caller (#637) sees only their own company's rows: job rows through the project, stock
    rows through the stock item's warehouse (see audit_scope)."""
    stmt = select(InventoryAuditLog).order_by(InventoryAuditLog.created_at.desc())
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
