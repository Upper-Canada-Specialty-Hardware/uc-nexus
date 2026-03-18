"""Repository for purchase order data access."""

import base64
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import PODocumentType, POStatus
from app.models.purchase_order import PODocument, POLineItem, PurchaseOrder
from app.models.receiving import ReceiveRecord


def get_purchase_orders(session: Session, project_id: uuid.UUID, status: POStatus | None = None) -> list[PurchaseOrder]:
    """Filter by project_id + optional status + deleted_at IS NULL, eagerly load line_items and documents."""
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items), selectinload(PurchaseOrder.documents))
        .where(
            PurchaseOrder.project_id == project_id,
            PurchaseOrder.deleted_at.is_(None),
        )
        .order_by(PurchaseOrder.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    return list(session.scalars(stmt).unique().all())


def get_purchase_order(session: Session, po_id: uuid.UUID) -> PurchaseOrder | None:
    """Single PO by id + deleted_at IS NULL, eagerly load line_items and documents."""
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items), selectinload(PurchaseOrder.documents))
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    return session.scalars(stmt).unique().first()


def get_receive_records_for_po(session: Session, po_id: uuid.UUID) -> list[ReceiveRecord]:
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
    vendor_name: str | None,
    vendor_contact: str | None,
    expected_delivery_date,
    po_number: str | None = None,
    vendor_quote_number: str | None = None,
) -> PurchaseOrder:
    """
    - Validate PO exists + not soft-deleted (NotFoundError)
    - Validate status in (Draft, Ordered) (InvalidStateTransitionError)
    - Validate no ReceiveRecords exist (InvalidStateTransitionError)
    - Validate po_number uniqueness within project if provided
    - Update only provided (non-None) fields
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status not in (POStatus.DRAFT, POStatus.ORDERED):
        raise InvalidStateTransitionError(f"Cannot edit PO in {po.status.value} status")

    # Check for existing receive records
    receive_count_stmt = select(func.count()).select_from(ReceiveRecord).where(ReceiveRecord.po_id == po_id)
    receive_count = session.scalar(receive_count_stmt)
    if receive_count and receive_count > 0:
        raise InvalidStateTransitionError("Cannot edit PO after receiving has started")

    if po_number is not None:
        # Validate uniqueness within project
        if po_number.strip():
            existing = session.scalars(
                select(PurchaseOrder).where(
                    PurchaseOrder.project_id == po.project_id,
                    PurchaseOrder.po_number == po_number,
                    PurchaseOrder.id != po.id,
                    PurchaseOrder.deleted_at.is_(None),
                )
            ).first()
            if existing is not None:
                raise ValidationError(f"PO number '{po_number}' already exists in this project", field="po_number")
            po.po_number = po_number
        else:
            po.po_number = None

    if vendor_name is not None:
        po.vendor_name = vendor_name
    if vendor_contact is not None:
        po.vendor_contact = vendor_contact
    if expected_delivery_date is not None:
        po.expected_delivery_date = expected_delivery_date
    if vendor_quote_number is not None:
        po.vendor_quote_number = vendor_quote_number if vendor_quote_number.strip() else None

    return po


def mark_po_as_ordered(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status == Draft (InvalidStateTransitionError)
    - Validate po_number is not None (ValidationError)
    - Validate vendor_name is not None (ValidationError)
    - Validate vendor_quote_number is not None (ValidationError)
    - Validate at least one VENDOR_ACKNOWLEDGEMENT document exists (ValidationError)
    - Set status=Ordered, ordered_at=datetime.utcnow()
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(f"Cannot mark PO as ordered from {po.status.value} status; must be Draft")

    if po.po_number is None:
        raise ValidationError("PO number is required before marking as ordered", field="po_number")

    if po.vendor_name is None:
        raise ValidationError(
            "Vendor name is required before marking as ordered",
            field="vendor_name",
        )

    if po.vendor_quote_number is None:
        raise ValidationError("Vendor quote number is required before marking as ordered", field="vendor_quote_number")

    has_vendor_ack = any(doc.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT for doc in (po.documents or []))
    if not has_vendor_ack:
        raise ValidationError(
            "Vendor acknowledgement document is required before marking as ordered", field="vendor_acknowledgement"
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
        raise InvalidStateTransitionError(f"Cannot cancel PO in {po.status.value} status")

    po.status = POStatus.CANCELLED
    po.deleted_at = datetime.utcnow()

    return po


def update_line_item_alias(
    session: Session,
    line_item_id: uuid.UUID,
    vendor_alias: str | None,
) -> POLineItem:
    """Update vendor_alias on a POLineItem. Parent PO must not be cancelled or closed."""
    stmt = select(POLineItem).where(POLineItem.id == line_item_id)
    poli = session.scalars(stmt).first()
    if poli is None:
        raise NotFoundError(f"PO line item {line_item_id} not found")

    po = get_purchase_order(session, poli.po_id)
    if po is None:
        raise NotFoundError("Parent purchase order not found")

    if po.status in (POStatus.CANCELLED, POStatus.CLOSED):
        raise InvalidStateTransitionError(f"Cannot update alias on PO in {po.status.value} status")

    poli.vendor_alias = vendor_alias
    return poli


def upload_po_document(
    session: Session,
    po_id: uuid.UUID,
    file_name: str,
    content_type: str,
    document_type: PODocumentType,
    file_data_base64: str,
) -> PODocument:
    """Upload a document for a PO. Validates PO exists and status allows edits."""
    from app.services import storage

    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status in (POStatus.CANCELLED, POStatus.CLOSED):
        raise InvalidStateTransitionError(f"Cannot upload documents to PO in {po.status.value} status")

    file_data = base64.b64decode(file_data_base64)
    file_size = len(file_data)

    doc_id = uuid.uuid4()
    s3_key = f"po-documents/{po_id}/{doc_id}_{file_name}"

    storage.upload_file(s3_key, file_data, content_type)

    doc = PODocument(
        id=doc_id,
        po_id=po_id,
        file_name=file_name,
        content_type=content_type,
        file_size=file_size,
        document_type=document_type,
        s3_key=s3_key,
    )
    session.add(doc)
    return doc


def delete_po_document(session: Session, document_id: uuid.UUID) -> None:
    """Delete a PO document. Validates PO status allows edits."""
    from app.services import storage

    stmt = select(PODocument).where(PODocument.id == document_id)
    doc = session.scalars(stmt).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    po = get_purchase_order(session, doc.po_id)
    if po is None:
        raise NotFoundError("Parent purchase order not found")

    if po.status in (POStatus.CANCELLED, POStatus.CLOSED):
        raise InvalidStateTransitionError(f"Cannot delete documents from PO in {po.status.value} status")

    storage.delete_file(doc.s3_key)
    session.delete(doc)


def get_po_document(session: Session, document_id: uuid.UUID) -> PODocument:
    """Get a single PO document."""
    stmt = select(PODocument).where(PODocument.id == document_id)
    doc = session.scalars(stmt).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    return doc
