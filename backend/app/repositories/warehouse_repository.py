"""Repository for warehouse inventory and opening item data access."""

import json
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.purchase_order import PurchaseOrder as POModel, POLineItem as POLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel, ReceiveLineItem as ReceiveLineItemModel
from app.models.enums import POStatus
from app.errors import NotFoundError, ValidationError, InvalidStateTransitionError


def get_inventory_hierarchy(session: Session, project_id: uuid.UUID) -> list[dict]:
    """
    Query all InventoryLocation rows WHERE project_id.
    Group by hardware_category, then product_code.
    At each level, sum quantities.
    Sort categories and product codes alphabetically.

    Return structure: list of dicts, each with:
    {
        "hardware_category": str,
        "product_codes": [
            {
                "product_code": str,
                "items": [InventoryLocationModel, ...],
                "total_quantity": int
            },
            ...
        ],
        "total_quantity": int
    }
    """
    stmt = (
        select(InventoryLocationModel)
        .where(InventoryLocationModel.project_id == project_id)
        .order_by(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
    )
    rows = list(session.scalars(stmt).all())

    # Group by hardware_category -> product_code
    cat_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il in rows:
        cat_map[il.hardware_category][il.product_code].append(il)

    result = []
    for category in sorted(cat_map.keys()):
        product_codes_map = cat_map[category]
        product_code_nodes = []
        category_total = 0

        for pc in sorted(product_codes_map.keys()):
            items = product_codes_map[pc]
            pc_total = sum(item.quantity for item in items)
            category_total += pc_total
            product_code_nodes.append({
                "product_code": pc,
                "items": items,
                "total_quantity": pc_total,
            })

        result.append({
            "hardware_category": category,
            "product_codes": product_code_nodes,
            "total_quantity": category_total,
        })

    return result


def get_inventory_items(
    session: Session,
    project_id: uuid.UUID,
    category: str,
    product_code: str,
) -> list[dict]:
    """
    Query InventoryLocation rows matching (project_id, category, product_code).
    JOIN to POLineItem (via po_line_item_id) then PurchaseOrder (via po_id) to get po_number and classification.

    Return list of dicts with keys: inventory_location, po_number, classification
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number)
        .join(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.project_id == project_id,
            InventoryLocationModel.hardware_category == category,
            InventoryLocationModel.product_code == product_code,
        )
    )
    rows = session.execute(stmt).all()

    return [
        {
            "inventory_location": row[0],
            "classification": row[1],
            "po_number": row[2],
        }
        for row in rows
    ]


def get_opening_items(session: Session, project_id: uuid.UUID) -> list[OpeningItemModel]:
    """
    Query all OpeningItem rows for project_id.
    Eagerly load installed_hardware relationship (OpeningItemHardware).
    Sort by opening_number ASC.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.project_id == project_id)
        .order_by(OpeningItemModel.opening_number.asc())
    )
    return list(session.scalars(stmt).unique().all())


def get_opening_item_details(session: Session, oi_id: uuid.UUID) -> OpeningItemModel:
    """
    Single OpeningItem by id, eagerly load installed_hardware.
    Raise NotFoundError if not found.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.id == oi_id)
    )
    oi = session.scalars(stmt).unique().first()
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")
    return oi


# ---------------------------------------------------------------------------
# Admin Correction helpers and functions
# ---------------------------------------------------------------------------


def _validate_location_fields(shelf: str, column: str, row: str) -> None:
    """Validate shelf, column, row are each 1-20 characters."""
    for field_name, value in [("shelf", shelf), ("column", column), ("row", row)]:
        if not value or len(value) < 1 or len(value) > 20:
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)


def adjust_inventory_quantity(
    session: Session, inv_id: uuid.UUID, adjustment: int, reason: str
) -> InventoryLocationModel:
    """Adjust the quantity of an InventoryLocation by a positive or negative amount."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    if not reason or len(reason) > 500:
        raise ValidationError("reason must be 1-500 characters", field="reason")

    new_quantity = il.quantity + adjustment
    if new_quantity < 0:
        raise ValidationError("Adjustment would result in negative quantity", field="adjustment")

    il.quantity = new_quantity

    print(json.dumps({
        "action": "inventory_adjustment",
        "inventoryLocationId": str(inv_id),
        "adjustment": adjustment,
        "newQuantity": new_quantity,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat(),
        "performedBy": "Admin/Manager",
    }))

    return il


def move_inventory_location(
    session: Session, inv_id: uuid.UUID, new_shelf: str, new_column: str, new_row: str
) -> InventoryLocationModel:
    """Move an InventoryLocation to a new shelf/column/row."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    _validate_location_fields(new_shelf, new_column, new_row)

    il.shelf = new_shelf
    il.column = new_column
    il.row = new_row

    return il


def mark_inventory_unlocated(session: Session, inv_id: uuid.UUID) -> InventoryLocationModel:
    """Clear the shelf/column/row on an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    il.shelf = None
    il.column = None
    il.row = None

    return il


def assign_inventory_location(
    session: Session, inv_id: uuid.UUID, shelf: str, column: str, row: str
) -> InventoryLocationModel:
    """Assign shelf/column/row to an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    _validate_location_fields(shelf, column, row)

    il.shelf = shelf
    il.column = column
    il.row = row

    return il


def move_opening_item_location(
    session: Session, oi_id: uuid.UUID, shelf: str, column: str, row: str
) -> OpeningItemModel:
    """Move an OpeningItem to a new shelf/column/row."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    _validate_location_fields(shelf, column, row)

    oi.shelf = shelf
    oi.column = column
    oi.row = row

    return oi


def mark_opening_item_unlocated(session: Session, oi_id: uuid.UUID) -> OpeningItemModel:
    """Clear the shelf/column/row on an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    oi.shelf = None
    oi.column = None
    oi.row = None

    return oi


def assign_opening_item_location(
    session: Session, oi_id: uuid.UUID, shelf: str, column: str, row: str
) -> OpeningItemModel:
    """Assign shelf/column/row to an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    _validate_location_fields(shelf, column, row)

    oi.shelf = shelf
    oi.column = column
    oi.row = row

    return oi


# ---------------------------------------------------------------------------
# Receiving helpers and functions
# ---------------------------------------------------------------------------


def create_receive(
    session: Session,
    po_id: uuid.UUID,
    received_by: str,
    line_items_input: list[dict],
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
            - locations: list[dict] each with shelf, column, row, quantity
    Returns:
        The created ReceiveRecord with line_items loaded.
    """
    # 1. Look up PO with line_items, validate exists + not soft-deleted
    stmt = (
        select(POModel)
        .options(selectinload(POModel.line_items))
        .where(POModel.id == po_id)
    )
    po = session.scalars(stmt).unique().first()
    if po is None or po.deleted_at is not None:
        raise NotFoundError(f"Purchase order {po_id} not found")

    # Validate PO status
    if po.status not in (POStatus.ORDERED, POStatus.PARTIALLY_RECEIVED):
        raise InvalidStateTransitionError(
            f"PO status must be Ordered or Partially_Received to receive, got {po.status.value}"
        )

    # 2. Validate received_by
    if not received_by or len(received_by) < 1 or len(received_by) > 100:
        raise ValidationError("received_by must be 1-100 characters", field="received_by")

    # 3. Build dict of POLineItems keyed by ID
    poli_dict: dict[uuid.UUID, POLineItemModel] = {
        li.id: li for li in po.line_items
    }

    # 4. Validate each line item input
    for li_input in line_items_input:
        poli_id = li_input["po_line_item_id"]
        if poli_id not in poli_dict:
            raise NotFoundError(f"PO line item {poli_id} not found on this PO")

        qty_received = li_input["quantity_received"]
        if qty_received < 1:
            raise ValidationError(
                "quantity_received must be >= 1", field="quantity_received"
            )

        poli = poli_dict[poli_id]
        pending = poli.ordered_quantity - poli.received_quantity
        if qty_received > pending:
            raise ValidationError(
                "Receive quantity exceeds pending quantity", field="quantity_received"
            )

        locations = li_input["locations"]
        if not locations:
            raise ValidationError("locations must be non-empty", field="locations")

        loc_sum = sum(loc["quantity"] for loc in locations)
        if loc_sum != qty_received:
            raise ValidationError(
                "Location quantities must sum to received quantity",
                field="locations",
            )

        for loc in locations:
            if loc["quantity"] < 1:
                raise ValidationError(
                    "Location quantity must be >= 1", field="quantity"
                )
            _validate_location_fields(loc["shelf"], loc["column"], loc["row"])

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

        for loc in li_input["locations"]:
            inv_loc = InventoryLocationModel(
                project_id=po.project_id,
                po_line_item_id=poli.id,
                receive_line_item_id=receive_line_item.id,
                hardware_category=poli.hardware_category,
                product_code=poli.product_code,
                quantity=loc["quantity"],
                shelf=loc["shelf"],
                column=loc["column"],
                row=loc["row"],
                received_at=receive_record.received_at,
            )
            session.add(inv_loc)

        # Update received_quantity on the POLineItem
        poli.received_quantity += li_input["quantity_received"]

    # Auto-transition PO status
    # Re-query all POLineItems for this PO to get fresh data
    all_line_items_stmt = (
        select(POLineItemModel)
        .where(POLineItemModel.po_id == po.id)
    )
    all_line_items = list(session.scalars(all_line_items_stmt).all())

    all_fully_received = all(
        li.received_quantity == li.ordered_quantity for li in all_line_items
    )
    any_received = any(li.received_quantity > 0 for li in all_line_items)

    if all_fully_received:
        po.status = POStatus.CLOSED
    elif any_received and po.status not in (POStatus.PARTIALLY_RECEIVED, POStatus.CLOSED):
        po.status = POStatus.PARTIALLY_RECEIVED

    return receive_record


def get_po_receiving_details(
    session: Session, po_id: uuid.UUID
) -> tuple[POModel, list[ReceiveRecordModel]]:
    """
    Get PO with line_items and all ReceiveRecords for that PO.

    Returns:
        Tuple of (po, receive_records)
    """
    # Look up PO with line_items
    stmt = (
        select(POModel)
        .options(selectinload(POModel.line_items))
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
