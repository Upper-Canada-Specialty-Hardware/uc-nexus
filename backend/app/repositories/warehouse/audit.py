"""Inventory audit log: shared write helper + query."""

import uuid

from sqlalchemy import select
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

    A scoped caller (#637) sees only rows carrying one of their own projects. Project-less rows - a
    stock movement, which belongs to a warehouse rather than a job - are dropped rather than shown to
    everybody: the row records no warehouse either, so there is nothing to attribute it with."""
    stmt = select(InventoryAuditLog).order_by(InventoryAuditLog.created_at.desc())
    if entity_id is not None:
        stmt = stmt.where(InventoryAuditLog.entity_id == entity_id)
    if entity_type is not None:
        stmt = stmt.where(InventoryAuditLog.entity_type == entity_type)
    if project_id is not None:
        stmt = stmt.where(InventoryAuditLog.project_id == project_id)
    if company is not None:
        from app.repositories import tenancy

        stmt = stmt.where(InventoryAuditLog.project_id.in_(tenancy.project_ids_for(company)))
    stmt = stmt.limit(limit).offset(offset)
    return list(session.scalars(stmt).all())
