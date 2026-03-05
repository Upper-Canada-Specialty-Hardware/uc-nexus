"""Repository for warehouse inventory and opening item data access."""

import json
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    NotificationType,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.models.shop_assembly import ShopAssemblyRequest as SARModel
from app.services import notification_service
from app.services.locking import lock_rows


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
            product_code_nodes.append(
                {
                    "product_code": pc,
                    "items": items,
                    "total_quantity": pc_total,
                }
            )

        result.append(
            {
                "hardware_category": category,
                "product_codes": product_code_nodes,
                "total_quantity": category_total,
            }
        )

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


def _validate_location_fields(aisle: str, bay: str, bin: str) -> None:
    """Validate aisle, bay, bin are each 1-20 characters."""
    for field_name, value in [("aisle", aisle), ("bay", bay), ("bin", bin)]:
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

    print(
        json.dumps(
            {
                "action": "inventory_adjustment",
                "inventoryLocationId": str(inv_id),
                "adjustment": adjustment,
                "newQuantity": new_quantity,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
                "performedBy": "Admin/Manager",
            }
        )
    )

    return il


def move_inventory_location(
    session: Session, inv_id: uuid.UUID, new_aisle: str, new_bay: str, new_bin: str
) -> InventoryLocationModel:
    """Move an InventoryLocation to a new aisle/bay/bin."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    _validate_location_fields(new_aisle, new_bay, new_bin)

    il.aisle = new_aisle
    il.bay = new_bay
    il.bin = new_bin

    return il


def mark_inventory_unlocated(session: Session, inv_id: uuid.UUID) -> InventoryLocationModel:
    """Clear the aisle/bay/bin on an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    il.aisle = None
    il.bay = None
    il.bin = None

    return il


def assign_inventory_location(
    session: Session, inv_id: uuid.UUID, aisle: str, bay: str, bin: str
) -> InventoryLocationModel:
    """Assign aisle/bay/bin to an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    _validate_location_fields(aisle, bay, bin)

    il.aisle = aisle
    il.bay = bay
    il.bin = bin

    return il


def move_opening_item_location(
    session: Session, oi_id: uuid.UUID, aisle: str, bay: str, bin: str
) -> OpeningItemModel:
    """Move an OpeningItem to a new aisle/bay/bin."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    _validate_location_fields(aisle, bay, bin)

    oi.aisle = aisle
    oi.bay = bay
    oi.bin = bin

    return oi


def mark_opening_item_unlocated(session: Session, oi_id: uuid.UUID) -> OpeningItemModel:
    """Clear the aisle/bay/bin on an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    oi.aisle = None
    oi.bay = None
    oi.bin = None

    return oi


def assign_opening_item_location(
    session: Session, oi_id: uuid.UUID, aisle: str, bay: str, bin: str
) -> OpeningItemModel:
    """Assign aisle/bay/bin to an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    _validate_location_fields(aisle, bay, bin)

    oi.aisle = aisle
    oi.bay = bay
    oi.bin = bin

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
            - locations: list[dict] each with aisle, bay, bin, quantity
    Returns:
        The created ReceiveRecord with line_items loaded.
    """
    # 1. Look up PO with line_items, validate exists + not soft-deleted
    stmt = select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id)
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
                raise ValidationError("Location quantity must be >= 1", field="quantity")
            _validate_location_fields(loc["aisle"], loc["bay"], loc["bin"])

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
                aisle=loc["aisle"],
                bay=loc["bay"],
                bin=loc["bin"],
                received_at=receive_record.received_at,
            )
            session.add(inv_loc)

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
    # Look up PO with line_items
    stmt = select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id)
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


# ---------------------------------------------------------------------------
# Pull Request functions
# ---------------------------------------------------------------------------


def get_pull_requests(
    session: Session,
    project_id: uuid.UUID,
    source=None,
    status=None,
) -> list[PullRequestModel]:
    """
    Query PullRequest WHERE project_id AND deleted_at IS NULL.
    Optional source filter, optional status filter.
    Order by created_at ASC (FIFO — oldest first).
    Eagerly load items (PullRequestItem).
    """
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.deleted_at.is_(None),
        )
    )
    if source is not None:
        stmt = stmt.where(PullRequestModel.source == source)
    if status is not None:
        stmt = stmt.where(PullRequestModel.status == status)
    stmt = stmt.order_by(PullRequestModel.created_at.asc())
    return list(session.scalars(stmt).unique().all())


def get_pull_request_details(session: Session, pr_id: uuid.UUID) -> PullRequestModel:
    """
    Single PullRequest by ID, deleted_at IS NULL.
    Eagerly load items.
    Raise NotFoundError if not found.
    """
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(
            PullRequestModel.id == pr_id,
            PullRequestModel.deleted_at.is_(None),
        )
    )
    pr = session.scalars(stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Pull request {pr_id} not found")
    return pr


def approve_pull_request(session: Session, pr_id: uuid.UUID, approved_by: str) -> tuple:
    """
    Approve a pull request with pessimistic locking and FIFO inventory deduction.

    Returns tuple: (pr, outcome_string, notification_or_none)
    where outcome_string is "APPROVED" or "CANCELLED".
    """
    # 1. Lock PR
    locked_prs = lock_rows(session, PullRequestModel, [pr_id])
    if not locked_prs:
        raise NotFoundError(f"Pull request {pr_id} not found")
    pr = locked_prs[0]

    if pr.status != PullRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Pull request must be Pending to approve, got {pr.status.value}")

    # 2. Gather inventory needs from Loose items
    needed_combos: dict[tuple[str, str], int] = defaultdict(int)
    opening_item_ids: list[uuid.UUID] = []

    for item in pr.items:
        if item.item_type == PullRequestItemType.LOOSE:
            key = (item.hardware_category, item.product_code)
            needed_combos[key] += item.requested_quantity
        elif item.item_type == PullRequestItemType.OPENING_ITEM:
            if item.opening_item_id is not None:
                opening_item_ids.append(item.opening_item_id)

    # 3. Lock inventory rows
    now = datetime.utcnow()

    if needed_combos:
        conditions = [
            and_(
                InventoryLocationModel.hardware_category == cat,
                InventoryLocationModel.product_code == code,
            )
            for (cat, code) in needed_combos.keys()
        ]
        stmt = (
            select(InventoryLocationModel)
            .where(
                InventoryLocationModel.project_id == pr.project_id,
                or_(*conditions),
            )
            .with_for_update()
            .order_by(InventoryLocationModel.id)
        )
        locked_inventory = list(session.scalars(stmt).all())
    else:
        locked_inventory = []

    # 4. Check sufficiency
    insufficient = False
    if needed_combos:
        # Group locked inventory by (cat, code)
        inv_by_combo: dict[tuple[str, str], list] = defaultdict(list)
        for il in locked_inventory:
            key = (il.hardware_category, il.product_code)
            inv_by_combo[key].append(il)

        for (cat, code), requested in needed_combos.items():
            available = sum(il.quantity for il in inv_by_combo.get((cat, code), []))
            if available < requested:
                insufficient = True
                break

    # 5. If insufficient: cancel
    if insufficient:
        pr.status = PullRequestStatus.CANCELLED
        pr.cancelled_at = now

        notif = notification_service.create_notification(
            session,
            project_id=pr.project_id,
            recipient_role=pr.requested_by,
            notification_type=NotificationType.PULL_REQUEST_CANCELLED,
            message=f"Pull Request {pr.request_number} was cancelled due to insufficient inventory.",
        )
        return (pr, "CANCELLED", notif)

    # 6. If sufficient: approve and deduct FIFO
    pr.status = PullRequestStatus.IN_PROGRESS
    pr.assigned_to = approved_by
    pr.approved_at = now

    if needed_combos:
        # Group locked inventory by (cat, code)
        inv_by_combo: dict[tuple[str, str], list] = defaultdict(list)
        for il in locked_inventory:
            key = (il.hardware_category, il.product_code)
            inv_by_combo[key].append(il)

        for (cat, code), requested in needed_combos.items():
            # Sort by received_at ASC (oldest first) for FIFO
            rows = sorted(inv_by_combo.get((cat, code), []), key=lambda r: r.received_at)
            remaining = requested
            for row in rows:
                if remaining <= 0:
                    break
                deduct = min(remaining, row.quantity)
                row.quantity -= deduct
                remaining -= deduct

    # 7. Lock Opening_Item rows if any
    if opening_item_ids:
        lock_rows(session, OpeningItemModel, opening_item_ids)

    return (pr, "APPROVED", None)


def complete_pull_request(session: Session, pr_id: uuid.UUID) -> PullRequestModel:
    """
    Complete a pull request:
    1. Validate status == In_Progress
    2. Set status=Completed, completed_at=now()
    3. Create notification
    4. If Shipping_Out source: set Opening_Item states to Ship_Ready
    5. If Shop_Assembly source: update SAR openings pull_status to Pulled
    """
    stmt = select(PullRequestModel).options(selectinload(PullRequestModel.items)).where(PullRequestModel.id == pr_id)
    pr = session.scalars(stmt).unique().first()
    if pr is None:
        raise NotFoundError(f"Pull request {pr_id} not found")

    if pr.status != PullRequestStatus.IN_PROGRESS:
        raise InvalidStateTransitionError(f"Pull request must be In_Progress to complete, got {pr.status.value}")

    now = datetime.utcnow()
    pr.status = PullRequestStatus.COMPLETED
    pr.completed_at = now

    # Create notification
    notification_service.create_notification(
        session,
        project_id=pr.project_id,
        recipient_role=pr.requested_by,
        notification_type=NotificationType.PULL_REQUEST_COMPLETED,
        message=f"Pull Request {pr.request_number} has been fulfilled.",
    )

    # Source-specific side effects
    if pr.source == PullRequestSource.SHIPPING_OUT:
        # For each Opening_Item item, set the OpeningItem state to Ship_Ready
        for item in pr.items:
            if item.item_type == PullRequestItemType.OPENING_ITEM and item.opening_item_id is not None:
                oi = session.get(OpeningItemModel, item.opening_item_id)
                if oi is not None:
                    oi.state = OpeningItemState.SHIP_READY

    elif pr.source == PullRequestSource.SHOP_ASSEMBLY:
        # Extract SAR request_number from PR number (strip "PR-" prefix)
        sar_request_number = pr.request_number.replace("PR-", "", 1)
        sar_stmt = (
            select(SARModel)
            .options(selectinload(SARModel.openings))
            .where(SARModel.request_number == sar_request_number)
        )
        sar = session.scalars(sar_stmt).unique().first()
        if sar is not None:
            for opening in sar.openings:
                opening.pull_status = PullStatus.PULLED

    return pr
