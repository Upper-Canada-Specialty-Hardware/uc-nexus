"""PO receiving: eligibility pre-flight, receive persistence, delivery/back-order reads."""

import uuid
from datetime import datetime

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    NotificationType,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.models.vendor import Vendor as VendorModel
from app.services import notification_service

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
                    "location": {"aisle": inv_loc.aisle, "row": inv_loc.row, "bay": inv_loc.bay},
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

    # The backfill retry loop for replacement pulls (#344). Stock arriving is the only thing that can
    # unblock one, and until now nothing was watching. Stock-pool POs are skipped: a replacement pull
    # draws on *project* inventory, and allocating from the pool is a separate deliberate act.
    if not is_stock_po:
        session.flush()
        notify_unblocked_replacement_pulls(
            session,
            po.project_id,
            {
                (poli_dict[li["po_line_item_id"]].hardware_category, poli_dict[li["po_line_item_id"]].product_code)
                for li in line_items_input
            },
        )

    return receive_record


def find_pending_replacement_pulls(
    session: Session,
    project_id: uuid.UUID,
    combos: set[tuple[str, str]] | None = None,
) -> list[PullRequestModel]:
    """PENDING replacement (PR-REPL) pulls in a project, optionally narrowed to those that want at
    least one of `combos` (#344).

    A replacement pull is identified **structurally** - a SHOP_ASSEMBLY pull at least one of whose
    lines carries `sa_opening_item_id` (#339), i.e. a line minted against a specific deficient
    checklist item - rather than by its `PR-REPL-` number prefix. The prefix is a display convention;
    the FK is the thing that makes the pull a replacement, and a structural test cannot be broken by
    renaming a request.

    Narrowing by combo is the first half of the dedupe: a receive that landed nothing this pull wants
    cannot have changed whether it is coverable, so there is no reason to look at it, let alone
    announce it. Items are eager-loaded because the caller sums their needs.
    """
    is_replacement = (
        select(PullRequestItemModel.id)
        .where(
            PullRequestItemModel.pull_request_id == PullRequestModel.id,
            PullRequestItemModel.sa_opening_item_id.is_not(None),
        )
        .exists()
    )
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(
            PullRequestModel.project_id == project_id,
            PullRequestModel.deleted_at.is_(None),
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.PENDING,
            is_replacement,
        )
    )
    if combos is not None:
        if not combos:
            return []
        wants_a_received_combo = exists().where(
            PullRequestItemModel.pull_request_id == PullRequestModel.id,
            or_(
                *[
                    and_(
                        PullRequestItemModel.hardware_category == cat,
                        PullRequestItemModel.product_code == code,
                    )
                    for cat, code in combos
                ]
            ),
        )
        stmt = stmt.where(wants_a_received_combo)
    return list(session.scalars(stmt).unique().all())


def notify_unblocked_replacement_pulls(
    session: Session,
    project_id: uuid.UUID | None,
    received_combos: set[tuple[str, str]],
) -> list:
    """Tell the warehouse that a blocked replacement pull can now be approved (#344).

    A PR-REPL pull is the one kind of pull that holds **no reservation** - nobody can claim stock for
    a deficiency that has not happened yet (#342) - so it is also the only one whose demand nothing
    was tracking. It sits PENDING, the approver sees INSUFFICIENT, the PO is told to backfill, and
    when the backfill finally lands there is no signal that the pull is now approvable. Somebody has
    to remember to go and retry it. This is that signal.

    **Dedupe, in three parts, and each part is doing different work:**

    1. *Relevance.* Only pulls that wanted one of the combos this receive actually landed are
       considered. A receive of door closers cannot change whether a hinge replacement is coverable.
    2. *Transition.* The pull must now be **fully** coverable, under the same reservation-aware
       availability the approver will apply (`on-hand - deficient - everyone's reservations`, with no
       self-exclusion, because a replacement pull holds nothing of its own to exclude). A receive that
       narrows the gap without closing it changes nothing the warehouse can act on, so it says
       nothing. This is the "insufficient -> sufficient" edge.
    3. *Open signal.* One **unread** notification per pull. If the last one has not been read yet,
       the warehouse already knows; raising a second is noise. Once it has been read the signal has
       done its job, so a pull that goes short again and is later covered again gets a fresh one.

    Returns the notifications raised, so callers and tests can assert on them.
    """
    if project_id is None or not received_combos:
        return []
    from .pull_requests import check_inventory_sufficiency

    raised = []
    for pr in find_pending_replacement_pulls(session, project_id, received_combos):
        needs = [
            (item.hardware_category, item.product_code, item.requested_quantity)
            for item in pr.items
            if item.item_type == PullRequestItemType.LOOSE and item.hardware_category and item.product_code
        ]
        if not needs:
            continue
        if not check_inventory_sufficiency(session, project_id, needs, reservation_aware=True).sufficient:
            continue
        if notification_service.has_unread_notification_for_pull(session, pr.id, NotificationType.PULL_UNBLOCKED):
            continue
        raised.append(
            notification_service.create_notification(
                session,
                project_id=project_id,
                recipient_role=notification_service.WAREHOUSE_RECIPIENT_ROLE,
                notification_type=NotificationType.PULL_UNBLOCKED,
                message=(
                    f"Replacement Pull Request {pr.request_number} can now be fulfilled - the hardware "
                    "it was waiting on has been received. Approve it to release the replacement."
                ),
                pull_request_id=pr.id,
            )
        )
    if raised:
        session.flush()
    return raised


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
