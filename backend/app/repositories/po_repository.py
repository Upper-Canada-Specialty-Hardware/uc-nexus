"""Repository for purchase order data access."""

import base64
import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import Classification, HardwareItemState, PODocumentType, POStatus
from app.models.purchase_order import PODocument, PODocumentData, POLineItem, PurchaseOrder
from app.models.receiving import ReceiveRecord

logger = logging.getLogger(__name__)

_UNSET = object()


def _learn_manufacturer_vendor_mappings(
    session: Session,
    *,
    project_id: uuid.UUID | None,
    gp_company: str | None,
    gp_vendor_id: str | None,
    gp_vendor_name: str | None,
    line_items: list[dict],
) -> None:
    """Learn-on-confirm (issue #232): after a PO is persisted GP-registered, upsert every distinct
    manufacturer on its hardware lines -> the vendor it was confirmed against, so the next PO for the
    same manufacturer auto-picks that vendor.

    The manufacturer isn't on the PO line - it's on the HardwareItem, matched by project_id +
    hardware_category + product_code. A stock PO (no project) or a not-yet-registered draft (no GP
    company/vendor) has nothing to learn and is skipped.

    The whole batch runs in a SAVEPOINT wrapped in try/except: a mapping-write failure rolls back only
    the mapping and is swallowed, so it can never fail the PO the caller is about to commit."""
    if project_id is None or not gp_company or not gp_vendor_id or not gp_vendor_name or not line_items:
        return

    try:
        with session.begin_nested():
            from app.models.hardware import HardwareItem
            from app.repositories import manufacturer_vendor_map_repository
            from app.services import manufacturer_match

            pairs = {(li["hardware_category"], li["product_code"]) for li in line_items}
            product_codes = {code for _cat, code in pairs}
            rows = session.execute(
                select(
                    HardwareItem.hardware_category,
                    HardwareItem.product_code,
                    HardwareItem.manufacturer,
                )
                .where(
                    HardwareItem.project_id == project_id,
                    HardwareItem.product_code.in_(product_codes),
                    HardwareItem.manufacturer.isnot(None),
                )
                # Deterministic label per key: first-seen wins below, so fix the row order.
                .order_by(HardwareItem.created_at, HardwareItem.id)
            ).all()

            # Collapse to one label per normalized key (variants of the same manufacturer share a row).
            labels_by_key: dict[str, str] = {}
            for cat, code, manufacturer in rows:
                if (cat, code) not in pairs:
                    continue
                label = (manufacturer or "").strip()
                key = manufacturer_match.normalize(label)
                if not key:
                    continue
                labels_by_key.setdefault(key, label)

            for key, label in labels_by_key.items():
                manufacturer_vendor_map_repository.upsert(
                    session,
                    gp_company=gp_company,
                    manufacturer_key=key,
                    label=label,
                    gp_vendor_id=gp_vendor_id,
                    gp_vendor_name=gp_vendor_name,
                    source="confirmed",
                )
    except Exception:
        # Best-effort: never let a mapping-write failure fail the PO (the savepoint has already rolled
        # back the partial mapping writes; the PO rows stay pending for the caller's commit).
        logger.warning("Failed to learn manufacturer -> vendor mappings for project %s", project_id, exc_info=True)


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


def _assert_po_number_available(
    session: Session,
    po_number: str,
    *,
    project_id: uuid.UUID | None,
    exclude_po_id: uuid.UUID | None = None,
) -> None:
    """Raise a clean ValidationError if po_number is already used by another non-deleted PO in the
    same scope (project-scoped, or global for project-less POs), matching the partial-unique indexes
    ix_purchase_orders_(project|no_project)_po_number. Without this a collision surfaces as a raw
    psycopg IntegrityError at commit instead of a field error."""
    stmt = select(PurchaseOrder).where(
        PurchaseOrder.po_number == po_number,
        PurchaseOrder.deleted_at.is_(None),
    )
    if exclude_po_id is not None:
        stmt = stmt.where(PurchaseOrder.id != exclude_po_id)
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
    else:
        stmt = stmt.where(PurchaseOrder.project_id.is_(None))
    if session.scalars(stmt).first() is not None:
        raise ValidationError(f"PO number '{po_number}' already exists", field="po_number")


def _coerce_order_cost(value, field: str) -> Decimal | None:
    """Issue #156: coerce an optional order-time dollar cost (shipping_cost / tariff_amount) to
    Decimal. Null passes through ("not entered"); a negative value is a clean field error."""
    if value is None:
        return None
    amount = Decimal(str(value))
    if amount < 0:
        raise ValidationError(f"{field.replace('_', ' ').capitalize()} must be zero or greater", field=field)
    return amount


def create_po(
    session: Session,
    line_items: list[dict],
    project_id: uuid.UUID | None = None,
    notes: str | None = None,
    cost_code: str | None = None,
    po_number: str | None = None,
    gp_company: str | None = None,
    gp_vendor_id: str | None = None,
    vendor_name_snapshot: str | None = None,
    buyer_id: str | None = None,
    shipping_cost: float | None = None,
    tariff_amount: float | None = None,
    preferred_delivery_date=None,
    created_by_user_id: str | None = None,
) -> PurchaseOrder:
    """Create a manual PO with line items. No hardware items are created.

    Issue #256: the manual path creates a plain DRAFT (no po_number/gp_company) - registering it
    into GP is a separate, conscious user action (register_po_in_gp). The GP-first stamping branch
    below (po_number + gp_company present, advancing DRAFT -> GP_REGISTERED in the same commit)
    remains for callers that already hold a GP result.

    gp_vendor_id/vendor_name_snapshot are the GP vendor picked live from gpVendors at push time,
    frozen onto the PO for display. They are the only vendor a PO carries - GP owns vendors, and
    Nexus keeps no vendor records of its own (#200 dropped the sync'd mirror, #509 the local contact
    table)."""
    if not line_items:
        raise ValidationError("At least one line item is required", field="line_items")

    # Validate project exists if provided
    if project_id is not None:
        from app.models.project import Project as ProjectModel

        project = session.get(ProjectModel, project_id)
        if project is None:
            raise NotFoundError(f"Project {project_id} not found")

    request_number = generate_next_request_number(session)

    cleaned_cost_code = cost_code.strip() if cost_code and cost_code.strip() else None

    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=request_number,
        project_id=project_id,
        status=POStatus.DRAFT,
        notes=notes,
        cost_code=cleaned_cost_code,
        gp_vendor_id=gp_vendor_id.strip() if gp_vendor_id and gp_vendor_id.strip() else None,
        vendor_name_snapshot=(
            vendor_name_snapshot.strip() if vendor_name_snapshot and vendor_name_snapshot.strip() else None
        ),
        buyer_id=buyer_id.strip() if buyer_id and buyer_id.strip() else None,
        # Who raised the request, from the caller's Clerk token. It is what a receive against this PO
        # later asks "inventory or ship out?" of.
        created_by_user_id=created_by_user_id,
        shipping_cost=_coerce_order_cost(shipping_cost, "shipping_cost"),
        tariff_amount=_coerce_order_cost(tariff_amount, "tariff_amount"),
        # Issue #216/#256: the PM's requested date, captured at request creation.
        preferred_delivery_date=preferred_delivery_date,
    )
    session.add(po)
    session.flush()

    for idx, li_data in enumerate(line_items, start=1):
        classification_val = li_data.get("classification")
        if isinstance(classification_val, str):
            classification_val = Classification(classification_val)

        order_as_raw = li_data.get("order_as")
        if not order_as_raw or not order_as_raw.strip():
            raise ValidationError("Order as is required for every line item", field="order_as")

        poli = POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=li_data["hardware_category"],
            product_code=li_data["product_code"],
            ordered_quantity=li_data["ordered_quantity"],
            received_quantity=0,
            unit_cost=Decimal(str(li_data["unit_cost"])) if li_data.get("unit_cost") else Decimal("0"),
            classification=classification_val,
            order_as=order_as_raw.strip(),
            # GP assigns ORD = line index * 16384 (1-based) in this same order when the PO is pushed
            # via the relay, so record the mapping now - it's what a relay /receipt targets per line.
            gp_line_ord=idx * 16384,
        )
        session.add(poli)

    session.flush()

    # GP-first: when the relay returned a number, stamp it + the company and advance this DRAFT to
    # GP_REGISTERED in the same commit, so a created PO is never left numberless and re-registerable.
    if po_number is not None and po_number.strip():
        cleaned_number = po_number.strip()
        _assert_po_number_available(session, cleaned_number, project_id=project_id, exclude_po_id=po.id)
        po.po_number = cleaned_number
        po.gp_company = gp_company.strip() if gp_company and gp_company.strip() else None
        # gp_vendor_id is what proves this PO is backed by a real GP vendor, so GP-registration gates
        # on it.
        if po.gp_vendor_id is not None:
            po.status = POStatus.GP_REGISTERED
            po.ordered_at = datetime.utcnow()
        session.flush()

    # Learn manufacturer -> vendor from this PO once it is GP-registered (issue #232). The helper
    # guards on project_id + GP company/vendor, so a plain DRAFT or a stock PO is a no-op.
    _learn_manufacturer_vendor_mappings(
        session,
        project_id=project_id,
        gp_company=po.gp_company,
        gp_vendor_id=po.gp_vendor_id,
        gp_vendor_name=po.vendor_name_snapshot,
        line_items=line_items,
    )

    return po


def register_po_in_gp(
    session: Session,
    po_id: uuid.UUID,
    gp_vendor_id: str,
    vendor_name_snapshot: str,
    po_number: str,
    gp_company: str,
    line_items: list[dict],
    cost_code: str | None = None,
    buyer_id: str | None = None,
    shipping_cost: float | None = None,
    tariff_amount: float | None = None,
    project_id: uuid.UUID | None = None,
) -> PurchaseOrder:
    """Register an imported DRAFT PO into GP (the import-acceptance path, issue #175).

    The resolver calls this ONLY after the relay /po push already succeeded, so the PO is now a real GP
    purchase order and the end state must be identical to a manually created one (path 2): map it to the
    real GP vendor + cost code, replace the draft's line items with the (possibly edited) set the user
    pushed - assigning gp_line_ord positionally in that SAME order so a later relay /receipt can target
    each GP line - stamp GP's returned PONUMBER + company, and advance DRAFT -> GP_REGISTERED. All in one
    commit. A GP failure never reaches here, so on failure the PO stays Draft and untouched.

    gp_vendor_id/vendor_name_snapshot are the GP vendor picked live from gpVendors at push time, and
    are the only vendor identity involved - Nexus keeps no vendor records of its own.

    project_id (#316) attaches a project to a draft that has none - a manually created stock PO, whose
    only chance to gain one is here, since Project appears nowhere else after creation. It is IGNORED
    when the PO already has a project: those line items were imported against that project's hardware
    schedule, and re-pointing the header would leave them describing hardware for a different job. The
    check lives here rather than only in the dialog so a direct GraphQL call gets the same guarantee.
    """
    from app.models.hardware import HardwareItem

    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")
    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(f"Only a Draft PO can be registered in GP; this one is {po.status.value}")
    if not line_items:
        raise ValidationError("At least one line item is required", field="line_items")

    # #316: adopt a project only onto a draft that has none. Assigned before the duplicate-PO-number
    # check below, which scopes uniqueness by project.
    if project_id is not None and po.project_id is None:
        from app.models.project import Project as ProjectModel

        if session.get(ProjectModel, project_id) is None:
            raise NotFoundError(f"Project {project_id} not found")
        po.project_id = project_id

    cleaned_gp_vendor_id = gp_vendor_id.strip() if gp_vendor_id else ""
    if not cleaned_gp_vendor_id:
        raise ValidationError("GP vendor is required to register a PO", field="gp_vendor_id")
    cleaned_vendor_name_snapshot = vendor_name_snapshot.strip() if vendor_name_snapshot else ""
    if not cleaned_vendor_name_snapshot:
        raise ValidationError("GP vendor name is required to register a PO", field="gp_vendor_name")

    cleaned_po_number = po_number.strip() if po_number else ""
    if not cleaned_po_number:
        raise ValidationError("GP PO number is required to register a PO", field="po_number")
    cleaned_company = gp_company.strip() if gp_company else ""
    if not cleaned_company:
        raise ValidationError("GP company is required to register a PO", field="gp_company")
    # Surface a duplicate GP number as a clean field error rather than a raw IntegrityError at commit.
    _assert_po_number_available(session, cleaned_po_number, project_id=po.project_id, exclude_po_id=po.id)

    existing = {li.id: li for li in po.line_items}
    seen_ids: set[uuid.UUID] = set()

    # Reconcile the incoming lines against the draft's lines by id: update kept, create added. gp_line_ord
    # is GP POP10110.ORD = line index * 16384, assigned in the order the lines were sent to the relay
    # (== this payload order), which is what a relay /receipt targets per line.
    for idx, li_data in enumerate(line_items, start=1):
        order_as_raw = li_data.get("order_as")
        if not order_as_raw or not order_as_raw.strip():
            raise ValidationError("Order as is required for every line item", field="order_as")
        qty = li_data.get("ordered_quantity")
        if qty is None or qty < 1:
            raise ValidationError("Ordered quantity must be at least 1", field="ordered_quantity")
        unit_cost = li_data.get("unit_cost")
        if unit_cost is None or unit_cost < 0:
            raise ValidationError("Unit cost must be zero or greater", field="unit_cost")

        classification_val = li_data.get("classification")
        if isinstance(classification_val, str):
            classification_val = Classification(classification_val)

        raw_id = li_data.get("id")
        if raw_id:
            lid = uuid.UUID(str(raw_id))
            poli = existing.get(lid)
            if poli is None:
                raise ValidationError(f"Line item {lid} does not belong to this PO", field="line_items")
            seen_ids.add(lid)
            poli.hardware_category = li_data["hardware_category"]
            poli.product_code = li_data["product_code"]
            poli.ordered_quantity = qty
            poli.unit_cost = Decimal(str(unit_cost))
            poli.classification = classification_val
            poli.order_as = order_as_raw.strip()
            poli.gp_line_ord = idx * 16384
        else:
            session.add(
                POLineItem(
                    id=uuid.uuid4(),
                    po_id=po.id,
                    hardware_category=li_data["hardware_category"],
                    product_code=li_data["product_code"],
                    ordered_quantity=qty,
                    received_quantity=0,
                    unit_cost=Decimal(str(unit_cost)),
                    classification=classification_val,
                    order_as=order_as_raw.strip(),
                    gp_line_ord=idx * 16384,
                )
            )

    # Remove lines the user dropped. A DRAFT PO has no receiving/inventory yet, so the only rows that can
    # reference these lines are imported HardwareItem rows (FK is RESTRICT) - release them back to
    # AVAILABLE before deleting, which the user accepted as the cost of editing the imported line set.
    # State must come back too: an orphaned row left IN_PO counts as ordered nowhere yet blocks the
    # item from being recreated as AVAILABLE by a later import.
    removed = [poli for lid, poli in existing.items() if lid not in seen_ids]
    if removed:
        removed_ids = [poli.id for poli in removed]
        session.execute(
            update(HardwareItem)
            .where(HardwareItem.po_line_item_id.in_(removed_ids))
            .values(po_line_item_id=None, state=HardwareItemState.AVAILABLE)
        )
        for poli in removed:
            session.delete(poli)

    po.gp_vendor_id = cleaned_gp_vendor_id
    po.vendor_name_snapshot = cleaned_vendor_name_snapshot
    if buyer_id and buyer_id.strip():
        po.buyer_id = buyer_id.strip()
    po.cost_code = cost_code.strip() if cost_code and cost_code.strip() else None
    po.shipping_cost = _coerce_order_cost(shipping_cost, "shipping_cost")
    po.tariff_amount = _coerce_order_cost(tariff_amount, "tariff_amount")
    po.po_number = cleaned_po_number
    po.gp_company = cleaned_company
    po.status = POStatus.GP_REGISTERED
    po.ordered_at = datetime.utcnow()
    session.flush()

    # Learn manufacturer -> vendor from this now-registered PO (issue #232). Best-effort, savepoint-
    # isolated: a mapping failure never fails the registration the relay already committed in GP.
    _learn_manufacturer_vendor_mappings(
        session,
        project_id=po.project_id,
        gp_company=cleaned_company,
        gp_vendor_id=cleaned_gp_vendor_id,
        gp_vendor_name=cleaned_vendor_name_snapshot,
        line_items=line_items,
    )

    return po


def get_purchase_orders(
    session: Session, project_id: uuid.UUID | None = None, status: POStatus | None = None
) -> list[PurchaseOrder]:
    """Filter by optional project_id + status + deleted_at IS NULL; eagerly load line_items, documents."""
    stmt = (
        select(PurchaseOrder)
        .options(
            # Nested load of each line's HardwareItem rows so the derived `manufacturer` field (issue
            # #232) is one selectin query, not an N+1 lazy load per line.
            selectinload(PurchaseOrder.line_items).selectinload(POLineItem.hardware_items),
            selectinload(PurchaseOrder.documents),
            selectinload(PurchaseOrder.document_data),
        )
        .where(PurchaseOrder.deleted_at.is_(None))
        .order_by(PurchaseOrder.created_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    return list(session.scalars(stmt).unique().all())


def get_purchase_order(session: Session, po_id: uuid.UUID) -> PurchaseOrder | None:
    """Single PO by id + deleted_at IS NULL, eagerly load line_items, documents."""
    stmt = (
        select(PurchaseOrder)
        .options(
            # See get_purchase_orders: nested load keeps the derived line manufacturer (issue #232) off
            # the N+1 path.
            selectinload(PurchaseOrder.line_items).selectinload(POLineItem.hardware_items),
            selectinload(PurchaseOrder.documents),
            selectinload(PurchaseOrder.document_data),
        )
        .where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    return session.scalars(stmt).unique().first()


def get_open_pos(session: Session, project_id: uuid.UUID | None = None) -> list[PurchaseOrder]:
    """Open POs (GP-Registered / Vendor-Confirmed / Partially-Received), oldest ordered_at first, for
    the receiving picker. Lean load - line_items/documents only, no nested hardware_items and no
    document_data (the derived line manufacturer resolves to None here by design)."""
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.line_items),
            selectinload(PurchaseOrder.documents),
        )
        .where(
            PurchaseOrder.deleted_at.is_(None),
            PurchaseOrder.status.in_(
                [
                    POStatus.GP_REGISTERED,
                    POStatus.VENDOR_CONFIRMED,
                    POStatus.PARTIALLY_RECEIVED,
                ]
            ),
        )
        .order_by(PurchaseOrder.ordered_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(PurchaseOrder.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def reload_po(session: Session, po_id: uuid.UUID) -> PurchaseOrder | None:
    """Re-read a PO with the relationships every mutation response needs (line_items, documents). No
    deleted_at filter - callers hold an id they just wrote."""
    stmt = (
        select(PurchaseOrder)
        .options(
            selectinload(PurchaseOrder.line_items),
            selectinload(PurchaseOrder.documents),
        )
        .where(PurchaseOrder.id == po_id)
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
    Return dict with keys: total, draft, gp_registered, vendor_confirmed, partially_received, closed,
    cancelled."""
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
        "gp_registered": 0,
        "vendor_confirmed": 0,
        "partially_received": 0,
        "closed": 0,
        "cancelled": 0,
    }
    status_key_map = {
        POStatus.DRAFT: "draft",
        POStatus.GP_REGISTERED: "gp_registered",
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
    expected_delivery_date=None,
    preferred_delivery_date=None,
    po_number: str | None = None,
    vendor_quote_number: str | None = None,
    project_id=_UNSET,
    notes: str | None = None,
    shipping_cost=_UNSET,
    tariff_amount=_UNSET,
) -> PurchaseOrder:
    """
    - Validate PO exists + not soft-deleted (NotFoundError)
    - Validate status in (Draft, GP_Registered, Vendor_Confirmed) (InvalidStateTransitionError)
    - Validate no ReceiveRecords exist (InvalidStateTransitionError)
    - Validate po_number uniqueness within project if provided
    - Update only provided fields (project_id uses the _UNSET sentinel)
    - Return updated PO
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status not in (POStatus.DRAFT, POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED):
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
            _assert_po_number_available(session, po_number, project_id=po.project_id, exclude_po_id=po.id)
            po.po_number = po_number
        else:
            po.po_number = None

    # Issue #216: the two delivery dates are status-gated. Preferred is the PM's ask, captured on the
    # DRAFT request; expected is the vendor's answer, only enterable once the PO exists in GP (the
    # DRAFT/GP_REGISTERED/VENDOR_CONFIRMED guard above already blocks both after receiving starts).
    if preferred_delivery_date is not None:
        if po.status != POStatus.DRAFT:
            raise InvalidStateTransitionError("Preferred delivery date can only be set on a Draft PO request")
        po.preferred_delivery_date = preferred_delivery_date
    if expected_delivery_date is not None:
        if po.status == POStatus.DRAFT:
            raise InvalidStateTransitionError("Expected delivery date can only be set after the PO is GP-Registered")
        po.expected_delivery_date = expected_delivery_date
    if vendor_quote_number is not None:
        po.vendor_quote_number = vendor_quote_number if vendor_quote_number.strip() else None
    if notes is not None:
        po.notes = notes if notes.strip() else None
    # Issue #156: null clears the value, 0 is a valid entered value - so these use the _UNSET sentinel.
    if shipping_cost is not _UNSET:
        po.shipping_cost = _coerce_order_cost(shipping_cost, "shipping_cost")
    if tariff_amount is not _UNSET:
        po.tariff_amount = _coerce_order_cost(tariff_amount, "tariff_amount")

    # Auto-transition: GP_REGISTERED → VENDOR_CONFIRMED when both vendor_quote_number and vendor_ack doc exist
    if po.status == POStatus.GP_REGISTERED:
        has_vendor_ack = any(doc.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT for doc in (po.documents or []))
        if po.vendor_quote_number is not None and has_vendor_ack:
            po.status = POStatus.VENDOR_CONFIRMED
    # Auto-revert: VENDOR_CONFIRMED → GP_REGISTERED when conditions no longer met
    elif po.status == POStatus.VENDOR_CONFIRMED:
        has_vendor_ack = any(doc.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT for doc in (po.documents or []))
        if po.vendor_quote_number is None or not has_vendor_ack:
            po.status = POStatus.GP_REGISTERED

    return po


def mark_po_as_ordered(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status == Draft (InvalidStateTransitionError)
    - Validate po_number is not None (ValidationError)
    - Validate gp_vendor_id is not None (ValidationError)
    - Set status=GP_Registered, ordered_at=datetime.utcnow()
    - Return updated PO

    GP_REGISTERED means "this PO exists in GP", so it has to carry the GP vendor it was placed with -
    the same invariant `create_po` gates its GP-first branch on and `register_po_in_gp` raises for.
    This path was the only one that did not enforce it: it used to require the local vendor link
    instead, which was never a GP vendor at all, so it let a PO reach GP_REGISTERED with a blank
    vendor in every view that names one (#509). The old link is gone with the table, and there is no
    field left that could fill the vendor in afterwards - which is correct, because a GP vendor comes
    from GP, not from a Nexus edit.
    """
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status != POStatus.DRAFT:
        raise InvalidStateTransitionError(f"Cannot mark PO as ordered from {po.status.value} status; must be Draft")

    if po.po_number is None:
        raise ValidationError("PO number is required before marking as ordered", field="po_number")

    if po.gp_vendor_id is None:
        raise ValidationError(
            "The GP vendor is required before marking as ordered; register the PO in GP instead",
            field="gp_vendor_id",
        )

    po.status = POStatus.GP_REGISTERED
    po.ordered_at = datetime.utcnow()

    return po


def cancel_po(session: Session, po_id: uuid.UUID) -> PurchaseOrder:
    """
    - Validate exists + not soft-deleted (NotFoundError)
    - Validate status in (Draft, GP_Registered, Vendor_Confirmed) (InvalidStateTransitionError)
    - Set status=Cancelled, deleted_at=datetime.utcnow()
    - Release the PO's hardware-schedule rows back to AVAILABLE
    - Return updated PO
    """
    from app.models.hardware import HardwareItem

    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    if po.status not in (POStatus.DRAFT, POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED):
        raise InvalidStateTransitionError(f"Cannot cancel PO in {po.status.value} status")

    po.status = POStatus.CANCELLED
    po.deleted_at = datetime.utcnow()

    # These statuses precede receiving, so nothing from this PO is in inventory yet. Without this,
    # the schedule rows the wizard stamped stay IN_PO against a dead PO: reconciliation reads the
    # combo as needing ordering again (it excludes cancelled POs), but the re-order mints brand-new
    # IN_PO rows next to the stranded ones - required_quantity rollups double-count, and the
    # stranded key blocks the item from ever being recreated as AVAILABLE by a later import.
    line_ids = [li.id for li in po.line_items]
    if line_ids:
        session.execute(
            update(HardwareItem)
            .where(HardwareItem.po_line_item_id.in_(line_ids))
            .values(po_line_item_id=None, state=HardwareItemState.AVAILABLE)
        )

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


def get_prior_order_as_values(
    session: Session,
    project_id: uuid.UUID | None,
    product_codes: list[str],
) -> dict[str, list[str]]:
    """
    For a project + set of product codes, return distinct non-empty `order_as` values from
    po_line_items, grouped by product_code, ranked by most recent line item updated_at.

    Scoped by PROJECT (#509). What a part is "ordered as" is remembered per job: on this project we
    call this part X, so offer X again rather than making the buyer retype it. It is deliberately
    neither of the two things it looks like:

    - not global. `order_as` becomes the GP line's item number (`gp_po.build_create_po_payload`), so
      it is a supplier-facing catalogue value; offering every alias ever used for a product code
      would suggest one vendor's SKU while raising a PO for another.
    - not vendor-scoped. It used to be filtered by the local vendor link, which is gone with the
      table (GP owns vendors), and the GP vendor is not chosen until register time - long after the
      import wizard needs these.

    A project scope also bounds the query: the wizard fires it once per manufacturer card, and
    without a scope every one of those is a full scan of every PO line ever written.

    project_id=None scopes to project-less (stock) POs, which is what a stock PO should see.

    Excludes CANCELLED POs and soft-deleted POs. Caps each list at 20.
    """
    if not product_codes:
        return {}

    last_used = func.max(POLineItem.updated_at).label("last_used")
    stmt = (
        select(POLineItem.product_code, POLineItem.order_as, last_used)
        .join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(
            PurchaseOrder.project_id == project_id if project_id is not None else PurchaseOrder.project_id.is_(None),
            POLineItem.product_code.in_(product_codes),
            POLineItem.order_as.isnot(None),
            func.trim(POLineItem.order_as) != "",
            PurchaseOrder.status != POStatus.CANCELLED,
            PurchaseOrder.deleted_at.is_(None),
        )
        .group_by(POLineItem.product_code, POLineItem.order_as)
        .order_by(POLineItem.product_code, last_used.desc())
    )
    rows = session.execute(stmt).all()

    result: dict[str, list[str]] = {}
    for product_code, order_as, _last_used in rows:
        bucket = result.setdefault(product_code, [])
        if len(bucket) < 20:
            bucket.append(order_as)
    return result


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

    # Auto-transition: GP_REGISTERED → VENDOR_CONFIRMED when uploading vendor ack and quote number exists
    if (
        document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT
        and po.status == POStatus.GP_REGISTERED
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

    # Auto-revert: VENDOR_CONFIRMED → GP_REGISTERED when last vendor ack doc is deleted
    if deleted_doc_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT and po.status == POStatus.VENDOR_CONFIRMED:
        remaining_ack = session.scalars(
            select(PODocument).where(
                PODocument.po_id == deleted_doc_po_id,
                PODocument.document_type == PODocumentType.VENDOR_ACKNOWLEDGEMENT,
                PODocument.id != deleted_doc_id,
            )
        ).first()
        if remaining_ack is None:
            po.status = POStatus.GP_REGISTERED


def get_po_document(session: Session, document_id: uuid.UUID) -> PODocument:
    """Get a single PO document."""
    stmt = select(PODocument).where(PODocument.id == document_id)
    doc = session.scalars(stmt).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    return doc


def get_po_document_data(session: Session, po_id: uuid.UUID) -> PODocumentData | None:
    """The captured generate-time gap data for a PO (issue #230), or None if never saved."""
    return session.scalars(select(PODocumentData).where(PODocumentData.po_id == po_id)).first()


_DOC_DATA_TEXT_FIELDS = (
    "vendor_address",
    "buyer_name",
    "ship_to",
    "shipping_method",
    "proposal_number",
    "tax_label",
)
_DOC_DATA_MONEY_FIELDS = ("freight", "miscellaneous", "tax_amount", "tariff_amount")
_DOC_DATA_BOOL_FIELDS = ("include_fsc", "include_usa_tariff", "include_customs")


def upsert_po_document_data(session: Session, po_id: uuid.UUID, **fields) -> PODocumentData:
    """Create or update the 1:1 PODocumentData for a PO (issue #230). Only keys present in fields are
    written, so a partial save leaves the rest intact. Money fields coerce to Decimal; blank text
    coerces to None. Validates the PO exists."""
    po = get_purchase_order(session, po_id)
    if po is None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    data = get_po_document_data(session, po_id)
    created = data is None
    if created:
        data = PODocumentData(id=uuid.uuid4(), po_id=po_id)
        session.add(data)

    for key in _DOC_DATA_TEXT_FIELDS:
        if key in fields:
            value = fields[key]
            setattr(data, key, value.strip() if value and value.strip() else None)
    if "tax_label" in fields and not (fields["tax_label"] and fields["tax_label"].strip()):
        # tax_label is NOT NULL; keep the default rather than storing None from a blanked input.
        data.tax_label = "Taxes"

    for key in _DOC_DATA_MONEY_FIELDS:
        if key in fields:
            value = fields[key]
            setattr(data, key, Decimal(str(value)) if value is not None else Decimal("0"))

    for key in _DOC_DATA_BOOL_FIELDS:
        if key in fields and fields[key] is not None:
            setattr(data, key, bool(fields[key]))

    if "currency" in fields:
        currency = (fields["currency"] or "CAD").strip().upper()
        data.currency = currency if currency in ("CAD", "USD") else "CAD"

    if "required_by_override" in fields:
        data.required_by_override = fields["required_by_override"]

    session.flush()
    return data


def get_po_openings(session: Session, po_id: uuid.UUID) -> list[dict]:
    """Which door openings (and leaves) this PO's hardware was bought for (#302).

    The PO user orders off the hardware schedule but the PO itself only carries fungible
    (category, product) lines, so by the time they are registering it into GP there is nothing on
    screen saying which doors the order is FOR. The link survives on HardwareItem, which the import
    path stamps with po_line_item_id: opening_id -> Opening, plus the #311 leaf.

    ONE grouped query, joined and aggregated in the database, returning plain dicts. A relationship
    walk here would be the classic resolver N+1 (see CLAUDE.md): a PO with 40 lines would issue 40
    SELECTs against Railway's managed Postgres and read as a frozen page.

    Rows come back ordered by opening then leaf, already summed per (opening, leaf, category, code),
    so the resolver only has to group consecutive rows - no second pass over the whole set.
    """
    from app.models.hardware import HardwareItem
    from app.models.project import Opening

    rows = session.execute(
        select(
            Opening.opening_number,
            Opening.building,
            Opening.floor,
            Opening.location,
            HardwareItem.leaf,
            HardwareItem.hardware_category,
            HardwareItem.product_code,
            func.sum(HardwareItem.item_quantity).label("quantity"),
        )
        .join(Opening, Opening.id == HardwareItem.opening_id)
        .join(POLineItem, POLineItem.id == HardwareItem.po_line_item_id)
        .where(POLineItem.po_id == po_id)
        .group_by(
            Opening.opening_number,
            Opening.building,
            Opening.floor,
            Opening.location,
            HardwareItem.leaf,
            HardwareItem.hardware_category,
            HardwareItem.product_code,
        )
        # NULLS FIRST is not portable enough to rely on and a frame's leaf IS null, so sort the null
        # leaf explicitly to the front rather than letting the backend decide where frames land.
        .order_by(
            Opening.opening_number,
            HardwareItem.leaf.is_(None).desc(),
            HardwareItem.leaf,
            HardwareItem.hardware_category,
            HardwareItem.product_code,
        )
    ).all()

    grouped: list[dict] = []
    for r in rows:
        key = (r.opening_number, r.leaf)
        if not grouped or (grouped[-1]["opening_number"], grouped[-1]["leaf"]) != key:
            grouped.append(
                {
                    "opening_number": r.opening_number,
                    "leaf": r.leaf,
                    "building": r.building,
                    "floor": r.floor,
                    "location": r.location,
                    "items": [],
                }
            )
        grouped[-1]["items"].append(
            {
                "hardware_category": r.hardware_category,
                "product_code": r.product_code,
                "quantity": int(r.quantity or 0),
            }
        )
    return grouped
