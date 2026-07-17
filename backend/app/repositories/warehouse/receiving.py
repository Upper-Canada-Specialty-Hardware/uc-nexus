"""PO receiving: eligibility pre-flight, receive persistence, delivery/back-order reads."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import AuditAction, AuditEntityType, POStatus
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.models.vendor import Vendor as VendorModel

from .audit import _log_audit_event
from .locations import _normalize_and_validate_location_fields


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
                _normalize_and_validate_location_fields(loc["aisle"], loc["bay"], loc["bin"])

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
            - locations: list[dict] each with aisle, bay, bin, quantity
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
                loc["aisle"], loc["bay"], loc["bin"] = _normalize_and_validate_location_fields(
                    loc["aisle"], loc["bay"], loc["bin"]
                )

    # 5. Execute in single transaction
    now = datetime.utcnow()

    receive_record = ReceiveRecordModel(
        po_id=po_id,
        received_at=now,
        received_by=received_by,
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
                        bay=loc["bay"],
                        bin=loc["bin"],
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
                    bay=None,
                    bin=None,
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
                    bay=loc["bay"],
                    bin=loc["bin"],
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
                bay=None,
                bin=None,
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
                    "location": {"aisle": inv_loc.aisle, "bay": inv_loc.bay, "bin": inv_loc.bin},
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

    return receive_record


def get_po_receiving_details(session: Session, po_id: uuid.UUID) -> tuple[POModel, list[ReceiveRecordModel]]:
    """
    Get PO with line_items and all ReceiveRecords for that PO.

    Returns:
        Tuple of (po, receive_records)
    """
    # Look up PO with line_items, documents, and vendor
    stmt = (
        select(POModel)
        .options(
            selectinload(POModel.line_items),
            selectinload(POModel.documents),
            selectinload(POModel.vendor),
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


def get_expected_deliveries(session: Session, project_id: uuid.UUID | None = None) -> list:
    """Active POs with outstanding line items, ordered by expected_delivery_date."""
    stmt = (
        select(POModel)
        .options(selectinload(POModel.line_items), selectinload(POModel.vendor))
        .where(
            POModel.status.in_([POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
            POModel.deleted_at.is_(None),
        )
        .order_by(POModel.expected_delivery_date.asc().nulls_last(), POModel.ordered_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(POModel.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def get_back_ordered_items(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """PO line items where received < ordered on active POs."""
    stmt = (
        select(POLineItemModel, POModel.po_number, VendorModel.name, POModel.expected_delivery_date)
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .outerjoin(VendorModel, POModel.vendor_id == VendorModel.id)
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
            "outstanding_quantity": row[0].ordered_quantity - row[0].received_quantity,
        }
        for row in rows
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
