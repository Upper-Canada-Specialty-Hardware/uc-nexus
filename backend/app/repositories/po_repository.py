"""Repository for purchase order data access."""

import base64
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import Classification, PODocumentType, POStatus
from app.models.purchase_order import PODocument, POLineItem, PurchaseOrder
from app.models.receiving import ReceiveRecord

_UNSET = object()


def generate_next_request_number(session: Session) -> str:
    """Generate the next PO-REQ-XXX request number."""
    max_req_stmt = select(func.max(PurchaseOrder.request_number)).where(PurchaseOrder.request_number.like("PO-REQ-%"))
    max_req = session.scalar(max_req_stmt)
    next_seq = 1
    if max_req:
        try:
            next_seq = int(max_req.replace("PO-REQ-", "")) + 1
        except ValueError:
            pass
    return f"PO-REQ-{next_seq:03d}"


def create_po(
    session: Session,
    line_items: list[dict],
    project_id: uuid.UUID | None = None,
    vendor_name: str | None = None,
    vendor_contact: str | None = None,
) -> PurchaseOrder:
    """Create a manual PO with line items. No hardware items are created."""
    if not line_items:
        raise ValidationError("At least one line item is required", field="line_items")

    # Validate project exists if provided
    if project_id is not None:
        from app.models.project import Project as ProjectModel

        project = session.get(ProjectModel, project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")

    request_number = generate_next_request_number(session)

    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=request_number,
        project_id=project_id,
        status=POStatus.DRAFT,
        vendor_name=vendor_name,
        vendor_contact=vendor_contact,
    )
    session.add(po)
    session.flush()

    for li_data in line_items:
        classification_val = li_data.get("classification")
        if isinstance(classification_val, str):
            classification_val = Classification(classification_val)

        poli = POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=li_data["hardware_category"],
            product_code=li_data["product_code"],
            ordered_quantity=li_data["ordered_quantity"],
            received_quantity=0,
            unit_cost=Decimal(str(li_data["unit_cost"])) if li_data.get("unit_cost") else Decimal("0"),
            classification=classification_val,
            order_as=li_data.get("order_as"),
        )
        session.add(poli)

    session.flush()
    return po


def get_purchase_orders(
    session: Session, project_id: uuid.UUID | None = None, status: POStatus | None = None
) -> list[PurchaseOrder]:
    """Filter by optional project_id + optional status + deleted_at IS NULL, eagerly load line_items and documents."""
    stmt = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items), selectinload(PurchaseOrder.documents))
        .where(PurchaseOrder.deleted_at.is_(None))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
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


def get_po_statistics(session: Session, project_id: uuid.UUID | None = None) -> dict:
    """COUNT grouped by status WHERE optional project_id AND deleted_at IS NULL.
    Return dict with keys: total, draft, ordered, partially_received, closed, cancelled."""
    stmt = (
        select(PurchaseOrder.status, func.count())
        .where(PurchaseOrder.deleted_at.is_(None))
        .group_by(PurchaseOrder.status)
    )
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
    rows = session.execute(stmt).all()

    counts = {
        "total": 0,
        "draft": 0,
        "ordered": 0,
        "vendor_confirmed": 0,
        "partially_received": 0,
        "closed": 0,
        "cancelled": 0,
    }
    status_key_map = {
        POStatus.DRAFT: "draft",
        POStatus.ORDERED: "ordered",
        POStatus.VENDOR_CONFIRMED: "vendor_confirmed",
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
    project_id=_UNSET,
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

    if po.status not in (POStatus.DRAFT, POStatus.ORDERED, POStatus.VENDOR_CONFIRMED):
        raise InvalidStateTransitionError(f"Cannot edit PO in {po.status.value} status")

    # Check for existing receive records
    receive_count_stmt = select(func.count()).select_from(ReceiveRecord).where(ReceiveRecord.po_id == po_id)
    receive_count = session.scalar(receive_count_stmt)
    if receive_count and receive_count > 0:
        raise InvalidStateTransitionError("Cannot edit PO after receiving has started")

    # Update project_id if provided (sentinel _UNSET means "not provided")
    if project_id is not _UNSET and project_id is not None:
        from app.models.project import Project as ProjectModel

        project = session.get(ProjectModel, project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")
        po.project_id = project_id

    if po_number is not None:
        # Validate uniqueness scoped to project (or globally for project-less POs)
        if po_number.strip():
            uniqueness_stmt = select(PurchaseOrder).where(
                PurchaseOrder.po_number == po_number,
                PurchaseOrder.id != po.id,
                PurchaseOrder.deleted_at.is_(None),
            )
            if po.project_id is not None:
                uniqueness_stmt = uniqueness_stmt.where(PurchaseOrder.project_id == po.project_id)
            else:
                uniqueness_stmt = uniqueness_stmt.where(PurchaseOrder.project_id.is_(None))
            existing = session.scalars(uniqueness_stmt).first()
            if existing is not None:
                raise ValidationError(f"PO number '{po_number}' already exists", field="po_number")
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

    # Auto-transition: ORDERED → VENDOR_CONFIRMED when both vendor_quote_number and vendor_ack doc exist
    if po.status == POStatus.ORDERED:
        has_vendor_ack = any(doc.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT for doc in (po.documents or []))
        if po.vendor_quote_number is not None and has_vendor_ack:
            po.status = POStatus.VENDOR_CONFIRMED
    # Auto-revert: VENDOR_CONFIRMED → ORDERED when conditions no longer met
    elif po.status == POStatus.VENDOR_CONFIRMED:
        has_vendor_ack = any(doc.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT for doc in (po.documents or []))
        if po.vendor_quote_number is None or not has_vendor_ack:
            po.status = POStatus.ORDERED

    return po


def mark_po_as_ordered(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status == Draft (InvalidStateTransitionError)
    - Validate po_number is not None (ValidationError)
    - Validate vendor_name is not None (ValidationError)
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

    if po.status not in (POStatus.DRAFT, POStatus.ORDERED, POStatus.VENDOR_CONFIRMED):
        raise InvalidStateTransitionError(f"Cannot cancel PO in {po.status.value} status")

    po.status = POStatus.CANCELLED
    po.deleted_at = datetime.utcnow()

    return po


def update_line_item_order_as(
    session: Session,
    line_item_id: uuid.UUID,
    order_as: str | None,
) -> POLineItem:
    """Update order_as on a POLineItem. Parent PO must not be cancelled or closed."""
    stmt = select(POLineItem).where(POLineItem.id == line_item_id)
    poli = session.scalars(stmt).first()
    if poli is None:
        raise NotFoundError(f"PO line item {line_item_id} not found")

    po = get_purchase_order(session, poli.po_id)
    if po is None:
        raise NotFoundError("Parent purchase order not found")

    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(f"Cannot update Order As on PO in {po.status.value} status")

    poli.order_as = order_as
    return poli


def update_line_item_unit_cost(
    session: Session,
    line_item_id: uuid.UUID,
    unit_cost: float,
) -> POLineItem:
    """Update unit_cost on a POLineItem. Parent PO must be DRAFT."""
    if unit_cost <= 0:
        raise ValidationError("Unit cost must be greater than zero", field="unit_cost")

    stmt = select(POLineItem).where(POLineItem.id == line_item_id)
    poli = session.scalars(stmt).first()
    if poli is None:
        raise NotFoundError(f"PO line item {line_item_id} not found")

    po = get_purchase_order(session, poli.po_id)
    if po is None:
        raise NotFoundError("Parent purchase order not found")

    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(f"Cannot update unit cost on PO in {po.status.value} status")

    poli.unit_cost = unit_cost
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

    # Auto-transition: ORDERED → VENDOR_CONFIRMED when uploading vendor ack and quote number exists
    if (
        document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT
        and po.status == POStatus.ORDERED
        and po.vendor_quote_number is not None
    ):
        po.status = POStatus.VENDOR_CONFIRMED

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

    deleted_doc_id = doc.id
    deleted_doc_po_id = doc.po_id
    deleted_doc_type = doc.document_type

    storage.delete_file(doc.s3_key)
    session.delete(doc)

    # Auto-revert: VENDOR_CONFIRMED → ORDERED when last vendor ack doc is deleted
    if deleted_doc_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT and po.status == POStatus.VENDOR_CONFIRMED:
        remaining_ack = session.scalars(
            select(PODocument).where(
                PODocument.po_id == deleted_doc_po_id,
                PODocument.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT,
                PODocument.id != deleted_doc_id,
            )
        ).first()
        if remaining_ack is None:
            po.status = POStatus.ORDERED


def get_po_document(session: Session, document_id: uuid.UUID) -> PODocument:
    """Get a single PO document."""
    stmt = select(PODocument).where(PODocument.id == document_id)
    doc = session.scalars(stmt).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    return doc
