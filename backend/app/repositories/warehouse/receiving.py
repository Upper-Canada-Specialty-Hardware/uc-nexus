"""PO receiving: eligibility pre-flight, receive persistence, back-order reads."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    POStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.project import Project as ProjectModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.repositories import project_repository

from .audit import _log_audit_event
from .locations import _normalize_and_validate_location_fields, location_detail


def validate_receive_eligibility(
    session: Session,
    po_id: uuid.UUID,
    received_by: str,
    line_items_input: list[dict],
) -> tuple[str, str, list[dict]]:
    """Read-only pre-flight for create_receive, run BEFORE the GP receipt is posted (issue #202 #1).

    Runs the same eligibility rules create_receive enforces - PO exists + GP-registered, status
    receivable, received_by length, every line maps to a receivable PO line with a GP line ord, qty in
    range, location sums - but persists nothing, so an over-receive / receive-against-a-complete-PO
    never reaches GP. Returns (po_number, gp_company, receipt_line_items) where receipt_line_items is the
    per-line gp_line_ord/quantity/locations shape build_create_receipt_payload expects. create_receive
    re-validates authoritatively on persist."""
    stmt = select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id)
    po = session.scalars(stmt).unique().first()
    if po is None or po.deleted_at is not None:
        raise NotFoundError(f"Purchase order {po_id} not found")
    if not po.gp_company or not po.po_number:
        raise ValidationError("PO must be registered in GP before it can be received", field="po_id")
    if po.status not in (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED):
        raise InvalidStateTransitionError(
            f"PO status must be GP_Registered, Vendor_Confirmed, or Partially_Received to receive, "
            f"got {po.status.value}"
        )
    if not received_by or len(received_by) < 1 or len(received_by) > 100:
        raise ValidationError("received_by must be 1-100 characters", field="received_by")
    if not line_items_input:
        raise ValidationError("At least one line item is required", field="line_items")
    # #425: the quarantine gate for receiving, and it belongs HERE rather than in create_receive.
    # This runs before the GP receipt is posted; create_receive runs after GP has already committed
    # it, and refusing there would leave a receipt in GP that Nexus will not book - the exact
    # split-brain the GP-first ordering exists to avoid. A broken job cannot be received anyway
    # (taPopRcptLineInsert rejects the line's account index with eConnect 4612), so this turns an
    # unavoidable failure into one that names the cause.
    project_repository.require_gp_setup_ok(session, po.project_id)

    poli_dict: dict[uuid.UUID, POLineItemModel] = {li.id: li for li in po.line_items}
    receipt_line_items: list[dict] = []
    for li_input in line_items_input:
        poli_id = li_input["po_line_item_id"]
        poli = poli_dict.get(poli_id)
        if poli is None:
            raise NotFoundError(f"PO line item {poli_id} not found on this PO")
        if poli.gp_line_ord is None:
            raise ValidationError(
                f"Line {poli.product_code} has no GP line mapping; re-create the PO through GP",
                field="line_items",
            )
        qty_received = li_input["quantity_received"]
        if qty_received < 1:
            raise ValidationError("quantity_received must be >= 1", field="quantity_received")
        pending = poli.ordered_quantity - poli.received_quantity
        if qty_received > pending:
            raise ValidationError("Receive quantity exceeds pending quantity", field="quantity_received")

        locations = li_input["locations"]
        if locations:
            loc_sum = sum(loc["quantity"] for loc in locations)
            if loc_sum != qty_received:
                raise ValidationError("Location quantities must sum to received quantity", field="locations")
            for loc in locations:
                if loc["quantity"] < 1:
                    raise ValidationError("Location quantity must be >= 1", field="quantity")
                deficient_q = loc.get("deficient_quantity", 0) or 0
                if deficient_q < 0 or deficient_q > loc["quantity"]:
                    raise ValidationError(
                        "deficient_quantity must satisfy 0 <= deficient_quantity <= quantity",
                        field="deficient_quantity",
                    )
                _normalize_and_validate_location_fields(loc["aisle"], loc["row"], loc["bay"])

        receipt_line_items.append(
            {
                "gp_line_ord": poli.gp_line_ord,
                "quantity": qty_received,
                "locations": locations,
            }
        )

    return po.po_number, po.gp_company, receipt_line_items


def create_receive(
    session: Session,
    po_id: uuid.UUID,
    received_by: str,
    line_items_input: list[dict],
    warehouse_id: uuid.UUID | None = None,
    *,
    receipt_number: str | None = None,
    batch_number: str | None = None,
    receive_draft_id: uuid.UUID | None = None,
) -> ReceiveRecordModel:
    """
    Create a ReceiveRecord with ReceiveLineItems and InventoryLocations.
    Auto-transitions PO status based on received quantities.

    Args:
        session: SQLAlchemy session
        po_id: UUID of the PurchaseOrder
        received_by: Name of the person receiving (1-100 chars)
        line_items_input: list of dicts, each with:
            - po_line_item_id: uuid.UUID
            - quantity_received: int
            - locations: list[dict] each with aisle, row, bay, quantity
        receipt_number: GP's RCT###### for the receipt this receive posted (#447), taken from the
            relay's create_receipt response. Keyword-only and defaulted so the many tests and the
            reset fixtures that create receives without a GP round trip keep working; in the running
            app it is always present, because receiving is GP-first and nothing is persisted here
            until GP has already numbered the receipt.
        batch_number: the GP batch that receipt landed in, from the same response.
    Returns:
        The created ReceiveRecord with line_items loaded.
    """
    # 1. Look up PO with line_items, validate exists + not soft-deleted
    stmt = select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id)
    po = session.scalars(stmt).unique().first()
    if po is None or po.deleted_at is not None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    # Project-less PO is allowed: line items route to the stock pool instead of project inventory
    is_stock_po = po.project_id is None

    if warehouse_id is None:
        from app.repositories import warehouse_admin_repository

        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)

    # Validate PO status
    if po.status not in (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED):
        raise InvalidStateTransitionError(
            f"PO status must be GP_Registered, Vendor_Confirmed, or Partially_Received to receive, "
            f"got {po.status.value}"
        )

    # 2. Validate received_by
    if not received_by or len(received_by) < 1 or len(received_by) > 100:
        raise ValidationError("received_by must be 1-100 characters", field="received_by")

    # 3. Build dict of POLineItems keyed by ID
    poli_dict: dict[uuid.UUID, POLineItemModel] = {li.id: li for li in po.line_items}

    # 4. Validate each line item input
    for li_input in line_items_input:
        poli_id = li_input["po_line_item_id"]
        if poli_id not in poli_dict:
            raise NotFoundError(f"PO line item {poli_id} not found on this PO")

        qty_received = li_input["quantity_received"]
        if qty_received < 1:
            raise ValidationError("quantity_received must be >= 1", field="quantity_received")

        poli = poli_dict[poli_id]
        pending = poli.ordered_quantity - poli.received_quantity
        if qty_received > pending:
            raise ValidationError("Receive quantity exceeds pending quantity", field="quantity_received")

        locations = li_input["locations"]
        if locations:
            loc_sum = sum(loc["quantity"] for loc in locations)
            if loc_sum != qty_received:
                raise ValidationError(
                    "Location quantities must sum to received quantity",
                    field="locations",
                )

            for loc in locations:
                if loc["quantity"] < 1:
                    raise ValidationError("Location quantity must be >= 1", field="quantity")
                deficient_q = loc.get("deficient_quantity", 0) or 0
                if deficient_q < 0 or deficient_q > loc["quantity"]:
                    raise ValidationError(
                        "deficient_quantity must satisfy 0 <= deficient_quantity <= quantity",
                        field="deficient_quantity",
                    )
                loc["aisle"], loc["row"], loc["bay"] = _normalize_and_validate_location_fields(
                    loc["aisle"], loc["row"], loc["bay"]
                )

    # 5. Execute in single transaction
    now = datetime.utcnow()

    receive_record = ReceiveRecordModel(
        po_id=po_id,
        received_at=now,
        received_by=received_by,
        receipt_number=receipt_number,
        batch_number=batch_number,
    )
    session.add(receive_record)
    session.flush()

    for li_input in line_items_input:
        poli = poli_dict[li_input["po_line_item_id"]]

        receive_line_item = ReceiveLineItemModel(
            receive_record_id=receive_record.id,
            po_line_item_id=poli.id,
            hardware_category=poli.hardware_category,
            product_code=poli.product_code,
            quantity_received=li_input["quantity_received"],
        )
        session.add(receive_line_item)
        session.flush()

        locations = li_input["locations"]
        created_inv_locs: list[InventoryLocationModel] = []
        if is_stock_po:
            # Route into the stock pool. Each location becomes (or merges into) a stock_items row.
            from app.repositories import stock as stock_repository

            if locations:
                for loc in locations:
                    stock_repository.receive_into_stock(
                        session,
                        warehouse_id=warehouse_id,
                        hardware_category=poli.hardware_category,
                        product_code=poli.product_code,
                        quantity=loc["quantity"],
                        deficient_quantity=loc.get("deficient_quantity", 0) or 0,
                        aisle=loc["aisle"],
                        row=loc["row"],
                        bay=loc["bay"],
                        received_at=receive_record.received_at,
                        received_by=received_by,
                        po_number=po.po_number,
                    )
            else:
                stock_repository.receive_into_stock(
                    session,
                    warehouse_id=warehouse_id,
                    hardware_category=poli.hardware_category,
                    product_code=poli.product_code,
                    quantity=li_input["quantity_received"],
                    deficient_quantity=0,
                    aisle=None,
                    row=None,
                    bay=None,
                    received_at=receive_record.received_at,
                    received_by=received_by,
                    po_number=po.po_number,
                )
        elif locations:
            for loc in locations:
                inv_loc = InventoryLocationModel(
                    project_id=po.project_id,
                    po_line_item_id=poli.id,
                    receive_line_item_id=receive_line_item.id,
                    warehouse_id=warehouse_id,
                    hardware_category=poli.hardware_category,
                    product_code=poli.product_code,
                    quantity=loc["quantity"],
                    deficient_quantity=loc.get("deficient_quantity", 0) or 0,
                    aisle=loc["aisle"],
                    row=loc["row"],
                    bay=loc["bay"],
                    received_at=receive_record.received_at,
                )
                session.add(inv_loc)
                created_inv_locs.append(inv_loc)
        else:
            inv_loc = InventoryLocationModel(
                project_id=po.project_id,
                po_line_item_id=poli.id,
                receive_line_item_id=receive_line_item.id,
                warehouse_id=warehouse_id,
                hardware_category=poli.hardware_category,
                product_code=poli.product_code,
                quantity=li_input["quantity_received"],
                aisle=None,
                row=None,
                bay=None,
                received_at=receive_record.received_at,
            )
            session.add(inv_loc)
            created_inv_locs.append(inv_loc)

        session.flush()
        for inv_loc in created_inv_locs:
            _log_audit_event(
                session,
                project_id=po.project_id,
                entity_type=AuditEntityType.INVENTORY_LOCATION,
                entity_id=inv_loc.id,
                action=AuditAction.RECEIVE,
                performed_by=received_by,
                detail={
                    "quantity": inv_loc.quantity,
                    "hardwareCategory": inv_loc.hardware_category,
                    "productCode": inv_loc.product_code,
                    "poNumber": po.po_number,
                    "location": location_detail(inv_loc.aisle, inv_loc.row, inv_loc.bay, inv_loc.warehouse_id),
                },
            )

        # Update received_quantity on the POLineItem
        poli.received_quantity += li_input["quantity_received"]

    # Auto-transition PO status
    # Re-query all POLineItems for this PO to get fresh data
    all_line_items_stmt = select(POLineItemModel).where(POLineItemModel.po_id == po.id)
    all_line_items = list(session.scalars(all_line_items_stmt).all())

    all_fully_received = all(li.received_quantity == li.ordered_quantity for li in all_line_items)
    any_received = any(li.received_quantity > 0 for li in all_line_items)

    if all_fully_received:
        po.status = POStatus.CLOSED
    elif any_received and po.status not in (POStatus.PARTIALLY_RECEIVED, POStatus.CLOSED):
        po.status = POStatus.PARTIALLY_RECEIVED

    # Ask whoever raised the PO where this shipment goes - project inventory, or straight back out to
    # site. It lives HERE, at the end of the persist, rather than in the resolver, because there are
    # two ways into this function: the online approval and the outbox worker draining a receipt that
    # was queued while the relay was down. A decision raised in the resolver would exist only for the
    # first. No-ops for a stock PO.
    from .receive_decisions import create_decision_for_receive, stamp_receive_record_on_draft_decision

    stamped = (
        stamp_receive_record_on_draft_decision(session, receive_draft_id, receive_record.id)
        if receive_draft_id is not None
        else None
    )
    if stamped is None:
        create_decision_for_receive(
            session,
            po,
            receive_record.id,
            total_quantity=sum(li["quantity_received"] for li in line_items_input),
        )

    return receive_record


def get_po_receiving_details(session: Session, po_id: uuid.UUID) -> tuple[POModel, list[ReceiveRecordModel]]:
    """
    Get PO with line_items and all ReceiveRecords for that PO.

    Returns:
        Tuple of (po, receive_records)
    """
    # Look up PO with line_items and documents
    stmt = (
        select(POModel)
        .options(
            selectinload(POModel.line_items),
            selectinload(POModel.documents),
        )
        .where(POModel.id == po_id)
    )
    po = session.scalars(stmt).unique().first()
    if po is None or po.deleted_at is not None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    # Query ReceiveRecords for this PO
    rr_stmt = (
        select(ReceiveRecordModel)
        .options(selectinload(ReceiveRecordModel.line_items))
        .where(ReceiveRecordModel.po_id == po_id)
        .order_by(ReceiveRecordModel.received_at.desc())
    )
    receive_records = list(session.scalars(rr_stmt).unique().all())

    return (po, receive_records)


def get_back_ordered_items(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """PO line items where received < ordered on active POs.

    The project is outer-joined because this feeds the Receiving page's back-order section, which is
    cross-project by default and therefore has to name the project on every row. A stock PO has no
    project at all, so `project_name` comes back None and the caller labels it.
    """
    stmt = (
        select(
            POLineItemModel,
            POModel.po_number,
            # The GP vendor frozen on at push time - the only vendor a PO names (#509).
            POModel.vendor_name_snapshot,
            POModel.expected_delivery_date,
            ProjectModel.description,
            ProjectModel.project_id,
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .outerjoin(ProjectModel, POModel.project_id == ProjectModel.id)
        .where(
            POModel.status.in_([POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
            POModel.deleted_at.is_(None),
            POLineItemModel.ordered_quantity > POLineItemModel.received_quantity,
        )
        .order_by(POModel.expected_delivery_date.asc().nulls_last(), POLineItemModel.hardware_category)
    )
    if project_id is not None:
        stmt = stmt.where(POModel.project_id == project_id)
    rows = session.execute(stmt).all()
    return [
        {
            "po_line_item": row[0],
            "po_number": row[1],
            "vendor_name": row[2],
            "expected_delivery_date": row[3],
            # Same fallback the rest of the app shows a project by: the description if it has one,
            # otherwise the TITAN project number.
            "project_name": row[4] or row[5] or None,
            "outstanding_quantity": row[0].ordered_quantity - row[0].received_quantity,
        }
        for row in rows
    ]


def get_receiving_history_pos(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Every PO that has reached GP, with how much of it has landed (#447).

    The Receiving page's other lists answer "what is still owed". This answers "what did we receive,
    and against what" - the reconciliation question, which needs the fully-received POs the open
    lists deliberately drop. Scope is therefore GP-registered and beyond (GP_REGISTERED,
    VENDOR_CONFIRMED, PARTIALLY_RECEIVED, CLOSED), excluding DRAFT and CANCELLED: a PO that never
    reached GP can have no receipts, and a cancelled one is not history anybody reconciles.

    Three grouped aggregates, one row per PO, no relationship iteration. The obvious shape - load the
    POs and walk `po.line_items` / `po.receive_records` per row - is the N+1 in the perf rules, and
    this list is cross-project by default, so it is exactly the resolver that would find every PO in
    the database one SELECT at a time. Each PO's individual receives are NOT returned: the row
    expands on demand through the existing `poReceivingDetails` query, so a page of a hundred POs
    costs a hundred rows rather than every receive line ever recorded.

    When a project is named, the filter goes into the aggregates as well as the outer query. Filtering
    only the outside still makes both subqueries group the whole of po_line_items and receive_records
    first and then throw nearly all of it away, so someone reconciling one job would pay for every
    receive ever recorded against every other job. The cross-project call keeps the unfiltered shape,
    because there it genuinely wants all of it.
    """
    project_po_ids = select(POModel.id).where(POModel.project_id == project_id) if project_id is not None else None

    line_totals_stmt = select(
        POLineItemModel.po_id.label("po_id"),
        func.coalesce(func.sum(POLineItemModel.ordered_quantity), 0).label("ordered_total"),
        func.coalesce(func.sum(POLineItemModel.received_quantity), 0).label("received_total"),
    ).group_by(POLineItemModel.po_id)
    receive_totals_stmt = select(
        ReceiveRecordModel.po_id.label("po_id"),
        func.count(ReceiveRecordModel.id).label("receive_count"),
        func.max(ReceiveRecordModel.received_at).label("last_received_at"),
    ).group_by(ReceiveRecordModel.po_id)
    if project_po_ids is not None:
        line_totals_stmt = line_totals_stmt.where(POLineItemModel.po_id.in_(project_po_ids))
        receive_totals_stmt = receive_totals_stmt.where(ReceiveRecordModel.po_id.in_(project_po_ids))

    line_totals = line_totals_stmt.subquery()
    receive_totals = receive_totals_stmt.subquery()

    stmt = (
        select(
            POModel.id,
            POModel.po_number,
            POModel.request_number,
            POModel.status,
            POModel.project_id,
            # The GP vendor frozen on at push time - the only vendor a PO names (#509).
            POModel.vendor_name_snapshot.label("vendor_name"),
            func.coalesce(line_totals.c.ordered_total, 0).label("ordered_total"),
            func.coalesce(line_totals.c.received_total, 0).label("received_total"),
            func.coalesce(receive_totals.c.receive_count, 0).label("receive_count"),
            receive_totals.c.last_received_at,
        )
        .outerjoin(line_totals, line_totals.c.po_id == POModel.id)
        .outerjoin(receive_totals, receive_totals.c.po_id == POModel.id)
        .where(
            POModel.deleted_at.is_(None),
            POModel.status.in_(
                [
                    POStatus.GP_REGISTERED,
                    POStatus.VENDOR_CONFIRMED,
                    POStatus.PARTIALLY_RECEIVED,
                    POStatus.CLOSED,
                ]
            ),
        )
        # Most recently received first, with the never-received POs last. This list answers the
        # history question, so the rows with history on them are what belongs at the top; sorting the
        # nulls first buries every actual receipt under a wall of POs nothing has landed against yet.
        # Those are not lost - the Receive side's own "POs Awaiting Receipt" table is where somebody
        # about to receive goes looking, and it puts them at the top of that view.
        .order_by(receive_totals.c.last_received_at.desc().nulls_last(), POModel.po_number.desc())
    )
    if project_id is not None:
        stmt = stmt.where(POModel.project_id == project_id)

    return [
        {
            "id": row.id,
            "po_number": row.po_number,
            "request_number": row.request_number,
            "status": row.status,
            "vendor_name": row.vendor_name,
            "project_id": row.project_id,
            "ordered_total": int(row.ordered_total or 0),
            "received_total": int(row.received_total or 0),
            "receive_count": int(row.receive_count or 0),
            "last_received_at": row.last_received_at,
        }
        for row in session.execute(stmt).all()
    ]


def get_recent_receive_records(session: Session, limit: int = 10) -> list[tuple]:
    """
    Get the most recent receive records across all POs.
    Returns list of (ReceiveRecord, PurchaseOrder) tuples.
    """
    stmt = (
        select(ReceiveRecordModel, POModel)
        .join(POModel, ReceiveRecordModel.po_id == POModel.id)
        .options(selectinload(ReceiveRecordModel.line_items))
        .order_by(ReceiveRecordModel.received_at.desc())
        .limit(limit)
    )
    return list(session.execute(stmt).unique().all())


def get_all_receives(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    project_id: uuid.UUID | None = None,
    po_search: str | None = None,
) -> list[dict]:
    """Every receive entity, drafts and booked records interleaved, newest first (#505).

    Each existing view covers a slice: MyReceiveDraftsView is one user's own drafts,
    ReceiveApprovalsPage is the manager's pending queue, ReceivingHistory is recent activity. A
    rejected draft appeared in none of them, so a count somebody disputed simply vanished.

    Drafts and records are read separately and merged in Python rather than SQL-UNIONed: they carry
    different columns (a draft has a reviewer and a rejection reason, a record has an RCT number and
    a batch), and a union would have to null-pad both sides into a shape neither one is.

    Line counts and quantities come off the already-loaded line collections, which are selectinloaded
    here - the #-N+1 rule: no per-row lazy loads.
    """
    from app.models.project import Project as ProjectModel
    from app.models.receive_draft import ReceiveDraft as ReceiveDraftModel

    def _po_filters(stmt, po_alias):
        if project_id is not None:
            stmt = stmt.where(po_alias.project_id == project_id)
        if po_search:
            stmt = stmt.where(po_alias.po_number.ilike(f"%{po_search.strip()}%"))
        return stmt

    draft_stmt = (
        select(ReceiveDraftModel, POModel)
        .join(POModel, ReceiveDraftModel.po_id == POModel.id)
        .options(selectinload(ReceiveDraftModel.line_items))
    )
    draft_stmt = _po_filters(draft_stmt, POModel)

    record_stmt = (
        select(ReceiveRecordModel, POModel)
        .join(POModel, ReceiveRecordModel.po_id == POModel.id)
        .options(selectinload(ReceiveRecordModel.line_items))
    )
    record_stmt = _po_filters(record_stmt, POModel)

    # A draft that has been approved has a receive_record_id, and the record is the row worth
    # showing - it carries the RCT number and the booked quantities. Skipping those drafts is what
    # keeps one physical delivery from appearing twice.
    rows: list[dict] = []
    for draft, po in session.execute(draft_stmt).unique().all():
        if draft.receive_record_id is not None:
            continue
        rows.append(
            {
                "kind": "DRAFT",
                "id": draft.id,
                "occurred_at": draft.created_at,
                "status": draft.status.value,
                "po_id": po.id,
                "po_number": po.po_number,
                "project_id": po.project_id,
                "warehouse_id": draft.warehouse_id,
                "line_count": len(draft.line_items),
                "total_quantity": sum(li.quantity_received for li in draft.line_items),
                "counted_by": draft.created_by_name,
                "reviewed_by": draft.reviewed_by_name,
                "rejection_reason": draft.rejection_reason,
                "receipt_number": None,
                "batch_number": None,
            }
        )

    for record, po in session.execute(record_stmt).unique().all():
        rows.append(
            {
                "kind": "RECORD",
                "id": record.id,
                "occurred_at": record.received_at,
                "status": "APPROVED",
                "po_id": po.id,
                "po_number": po.po_number,
                "project_id": po.project_id,
                "warehouse_id": None,
                "line_count": len(record.line_items),
                "total_quantity": sum(li.quantity_received for li in record.line_items),
                "counted_by": record.received_by,
                "reviewed_by": None,
                "rejection_reason": None,
                "receipt_number": record.receipt_number,
                "batch_number": record.batch_number,
            }
        )

    # Project names in one grouped read rather than one per row.
    project_ids = {r["project_id"] for r in rows if r["project_id"]}
    names: dict = {}
    if project_ids:
        names = {
            pid: (desc or number)
            for pid, number, desc in session.execute(
                select(ProjectModel.id, ProjectModel.project_id, ProjectModel.description).where(
                    ProjectModel.id.in_(project_ids)
                )
            ).all()
        }
    for r in rows:
        r["project_name"] = names.get(r["project_id"])

    rows.sort(key=lambda r: r["occurred_at"], reverse=True)
    return rows[offset : offset + limit]
