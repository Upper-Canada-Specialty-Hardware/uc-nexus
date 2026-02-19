"""Repository for purchase order data access."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from app.models.purchase_order import PurchaseOrder, POLineItem
from app.models.receiving import ReceiveRecord, ReceiveLineItem
from app.models.enums import POStatus
from app.errors import NotFoundError, ValidationError, InvalidStateTransitionError


def get_purchase_orders(
    session: Session, project_id: uuid.UUID, status: Optional[POStatus] = None
) -> list[PurchaseOrder]:
    """Filter by project_id + optional status + deleted_at IS NULL, eagerly load line_items, order by created_at DESC."""
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items))
        .where(
            PurchaseOrder.project_id == project_id,
            PurchaseOrder.deleted_at.is_(None),
        )
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    return list(session.scalars(stmt).unique().all())


def get_purchase_order(
    session: Session, po_id: uuid.UUID
) -> Optional[PurchaseOrder]:
    """Single PO by id + deleted_at IS NULL, eagerly load line_items."""
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items))
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    return session.scalars(stmt).unique().first()


def get_receive_records_for_po(
    session: Session, po_id: uuid.UUID
) -> list[ReceiveRecord]:
    """Get all ReceiveRecords for a PO, eagerly load their line_items.
    NOTE: PurchaseOrder model has NO receive_records relationship -- must query ReceiveRecord.po_id directly."""
    stmt = (
        select(ReceiveRecord)
        .options(selectinload(ReceiveRecord.line_items))
        .where(ReceiveRecord.po_id == po_id)
        .order_by(ReceiveRecord.received_at.desc())
    )
    return list(session.scalars(stmt).unique().all())


def get_po_statistics(session: Session, project_id: uuid.UUID) -> dict:
    """COUNT grouped by status WHERE project_id AND deleted_at IS NULL.
    Return dict with keys: total, draft, ordered, partially_received, closed, cancelled."""
    stmt = (
        select(PurchaseOrder.status, func.count())
        .where(
            PurchaseOrder.project_id == project_id,
            PurchaseOrder.deleted_at.is_(None),
        )
        .group_by(PurchaseOrder.status)
    )
    rows = session.execute(stmt).all()

    counts = {
        "total": 0,
        "draft": 0,
        "ordered": 0,
        "partially_received": 0,
        "closed": 0,
        "cancelled": 0,
    }
    status_key_map = {
        POStatus.DRAFT: "draft",
        POStatus.ORDERED: "ordered",
        POStatus.PARTIALLY_RECEIVED: "partially_received",
        POStatus.CLOSED: "closed",
        POStatus.CANCELLED: "cancelled",
    }
    for status_val, count in rows:
        key = status_key_map.get(status_val)
        if key:
            counts[key] = count
            counts["total"] += count

    return counts


def update_po(
    session: Session,
    po_id: uuid.UUID,
    vendor_name: Optional[str],
    vendor_contact: Optional[str],
    expected_delivery_date,
) -> PurchaseOrder:
    """
    - Validate PO exists + not soft-deleted (NotFoundError)
    - Validate status in (Draft, Ordered) (InvalidStateTransitionError)
    - Validate no ReceiveRecords exist (InvalidStateTransitionError)
    - Update only provided (non-None) fields
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status not in (POStatus.DRAFT, POStatus.ORDERED):
        raise InvalidStateTransitionError(
            f"Cannot edit PO in {po.status.value} status"
        )

    # Check for existing receive records
    receive_count_stmt = (
        select(func.count()).select_from(ReceiveRecord).where(ReceiveRecord.po_id == po_id)
    )
    receive_count = session.scalar(receive_count_stmt)
    if receive_count and receive_count > 0:
        raise InvalidStateTransitionError(
            "Cannot edit PO after receiving has started"
        )

    if vendor_name is not None:
        po.vendor_name = vendor_name
    if vendor_contact is not None:
        po.vendor_contact = vendor_contact
    if expected_delivery_date is not None:
        po.expected_delivery_date = expected_delivery_date

    return po


def mark_po_as_ordered(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status == Draft (InvalidStateTransitionError)
    - Validate vendor_name is not None (ValidationError)
    - Set status=Ordered, ordered_at=datetime.utcnow()
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(
            f"Cannot mark PO as ordered from {po.status.value} status; must be Draft"
        )

    if po.vendor_name is None:
        raise ValidationError(
            "Vendor name is required before marking as ordered",
            field="vendor_name",
        )

    po.status = POStatus.ORDERED
    po.ordered_at = datetime.utcnow()

    return po


def cancel_po(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status in (Draft, Ordered) (InvalidStateTransitionError)
    - Set status=Cancelled, deleted_at=datetime.utcnow()
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status not in (POStatus.DRAFT, POStatus.ORDERED):
        raise InvalidStateTransitionError(
            f"Cannot cancel PO in {po.status.value} status"
        )

    po.status = POStatus.CANCELLED
    po.deleted_at = datetime.utcnow()

    return po
