"""Repository for shipping and packing slip data access."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    NotificationType,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ReturnDisposition,
    ShippingOutRequestStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_request import (
    PullRequest as PullRequestModel,
)
from app.models.pull_request import (
    PullRequestItem as PullRequestItemModel,
)
from app.models.shipping import (
    PackingSlip,
    PackingSlipItem,
    ShipmentReturn,
    ShipmentReturnItem,
)
from app.models.shipping_out_request import (
    ShippingOutRequest,
    ShippingOutRequestItem,
)
from app.models.warehouse import Warehouse
from app.repositories import project_repository
from app.repositories.stock import _find_or_create_stock_row, _log_audit_event
from app.services import notification_service
from app.services.locking import lock_rows


def get_ship_ready_items(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> dict:
    """Query ship-ready opening items and compute available loose hardware."""
    # 1. Opening items with state = Ship_Ready
    oi_stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.state == OpeningItemState.SHIP_READY)
        .order_by(OpeningItemModel.opening_number.asc())
    )
    if project_id is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.project_id == project_id)
    opening_items = list(session.scalars(oi_stmt).unique().all())

    # 2. Loose items: sum requested_quantity from completed Shipping_Out PRs
    fulfilled_stmt = (
        select(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            func.sum(PullRequestItemModel.requested_quantity).label("total_requested"),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
            PullRequestItemModel.item_type == PullRequestItemType.LOOSE,
        )
        .group_by(
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
        )
    )
    if project_id is not None:
        fulfilled_stmt = fulfilled_stmt.where(PullRequestModel.project_id == project_id)
    fulfilled_rows = session.execute(fulfilled_stmt).all()
    fulfilled_map: dict[tuple, int] = {}
    for row in fulfilled_rows:
        key = (row.opening_number, row.hardware_category, row.product_code)
        fulfilled_map[key] = row.total_requested

    # 3. Subtract already-shipped loose items from PackingSlipItems
    shipped_stmt = (
        select(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
            func.sum(PackingSlipItem.quantity).label("total_shipped"),
        )
        .join(PackingSlip, PackingSlipItem.packing_slip_id == PackingSlip.id)
        .where(PackingSlipItem.item_type == PullRequestItemType.LOOSE)
        .group_by(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
        )
    )
    if project_id is not None:
        shipped_stmt = shipped_stmt.where(PackingSlip.project_id == project_id)
    shipped_rows = session.execute(shipped_stmt).all()
    shipped_map: dict[tuple, int] = {}
    for row in shipped_rows:
        key = (row.opening_number, row.hardware_category, row.product_code)
        shipped_map[key] = row.total_shipped

    # 4. Compute available loose items
    loose_items = []
    for key, total_fulfilled in fulfilled_map.items():
        already_shipped = shipped_map.get(key, 0)
        available = total_fulfilled - already_shipped
        if available > 0:
            loose_items.append(
                {
                    "opening_number": key[0],
                    "hardware_category": key[1],
                    "product_code": key[2],
                    "available_quantity": available,
                }
            )

    # Sort loose items by opening_number
    loose_items.sort(key=lambda x: x["opening_number"])

    return {
        "opening_items": opening_items,
        "loose_items": loose_items,
    }


def confirm_shipment(
    session: Session,
    project_id: uuid.UUID,
    packing_slip_number: str,
    shipped_by: str,
    items: list[dict],
) -> PackingSlip:
    """
    Confirm a shipment: create PackingSlip + PackingSlipItems, transition
    OpeningItem states to Shipped_Out.

    Args:
        session: SQLAlchemy session
        project_id: UUID of the project
        packing_slip_number: Unique slip number (1-50 chars)
        shipped_by: Name of shipper
        items: list of dicts with keys:
            - item_type: PullRequestItemType ('Opening_Item' or 'Loose')
            - opening_item_id: UUID (for Opening_Item type)
            - opening_number: str (for Loose type)
            - product_code: str (for Loose type)
            - hardware_category: str (for Loose type)
            - quantity: int
    """
    # 0. #425: quarantine gate. Shipping out is the last thing a project does, and it is the point of
    # no return - hardware leaves the building against a job whose costs cannot be booked. Blocked
    # here for the same reason the earlier stages are: everything downstream of a broken GP job has to
    # stop until accounting has repaired it, or the reconciliation gets worse the longer it runs.
    project_repository.require_gp_setup_ok(session, project_id)

    # 1. Validate packing_slip_number
    if not packing_slip_number or len(packing_slip_number) < 1 or len(packing_slip_number) > 50:
        raise ValidationError("packing_slip_number must be 1-50 characters", field="packing_slip_number")

    if not shipped_by:
        raise ValidationError("shipped_by must not be empty", field="shipped_by")

    if not items:
        raise ValidationError("items must not be empty", field="items")

    # Check uniqueness
    existing_stmt = select(PackingSlip).where(PackingSlip.packing_slip_number == packing_slip_number)
    if session.scalars(existing_stmt).first() is not None:
        raise ConflictError(
            f"Packing slip {packing_slip_number} already exists",
            field="packing_slip_number",
        )

    # 2. Separate Opening_Item and Loose items
    opening_item_cart = []
    loose_cart = []
    for item in items:
        if item["item_type"] == PullRequestItemType.OPENING_ITEM:
            opening_item_cart.append(item)
        elif item["item_type"] == PullRequestItemType.LOOSE:
            loose_cart.append(item)

    # 3. Lock and validate Opening_Item rows
    oi_ids = [item["opening_item_id"] for item in opening_item_cart]
    if oi_ids:
        locked_ois = lock_rows(session, OpeningItemModel, oi_ids)
        if len(locked_ois) != len(oi_ids):
            found_ids = {o.id for o in locked_ois}
            missing = [str(oid) for oid in oi_ids if oid not in found_ids]
            raise NotFoundError(f"Opening items not found: {missing}")
        for oi in locked_ois:
            if oi.state != OpeningItemState.SHIP_READY:
                raise InvalidStateTransitionError(f"Opening item {oi.id} is not Ship_Ready (current: {oi.state.value})")

    # 4. Validate loose items availability
    if loose_cart:
        # Get current ship-ready data for loose items to verify availability
        ship_ready = get_ship_ready_items(session, project_id)
        available_loose: dict[tuple, int] = {}
        for li in ship_ready["loose_items"]:
            key = (li["opening_number"], li["hardware_category"], li["product_code"])
            available_loose[key] = li["available_quantity"]

        # Aggregate cart loose items by key
        cart_loose_agg: dict[tuple, int] = defaultdict(int)
        for item in loose_cart:
            key = (item["opening_number"], item["hardware_category"], item["product_code"])
            cart_loose_agg[key] += item["quantity"]

        for key, requested in cart_loose_agg.items():
            available = available_loose.get(key, 0)
            if requested > available:
                raise ValidationError(
                    f"Insufficient loose hardware: {key[2]} ({key[1]}) for opening {key[0]} - "
                    f"requested {requested}, available {available}",
                    field="items",
                )

    # 5. Create PackingSlip
    now = datetime.utcnow()
    packing_slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=packing_slip_number,
        project_id=project_id,
        shipped_by=shipped_by,
        shipped_at=now,
    )
    session.add(packing_slip)
    session.flush()

    # 6. Create PackingSlipItems
    for item in opening_item_cart:
        oi = session.get(OpeningItemModel, item["opening_item_id"])
        psi = PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=packing_slip.id,
            item_type=PullRequestItemType.OPENING_ITEM,
            opening_item_id=item["opening_item_id"],
            opening_number=oi.opening_number if oi else None,
            # Snapshot the door leaf (#311): the slip is an immutable record of which leaf shipped.
            leaf=oi.leaf if oi else None,
            product_code=oi.installed_hardware[0].product_code if oi and oi.installed_hardware else "",
            hardware_category=oi.installed_hardware[0].hardware_category if oi and oi.installed_hardware else "",
            quantity=1,
        )
        session.add(psi)

    for item in loose_cart:
        psi = PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=packing_slip.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=item["opening_number"],
            product_code=item["product_code"],
            hardware_category=item["hardware_category"],
            quantity=item["quantity"],
        )
        session.add(psi)

    # 7. Update OpeningItem states to Shipped_Out
    if oi_ids:
        for oi in locked_ois:
            oi.state = OpeningItemState.SHIPPED_OUT

    # 8. Create notification
    item_count = len(opening_item_cart) + sum(i["quantity"] for i in loose_cart)
    notification_service.create_notification(
        session,
        project_id=project_id,
        recipient_role="Warehouse Staff",
        notification_type=NotificationType.SHIPMENT_COMPLETED,
        message=f"Shipment {packing_slip_number} confirmed. {item_count} items shipped.",
    )

    return packing_slip


# ---------------------------------------------------------------------------
# Shipment returns (issue #89): a shipment comes back from site.
# Only loose-hardware lines are returnable; opening items never re-enter.
# ---------------------------------------------------------------------------


def list_packing_slips(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> list[PackingSlip]:
    """List confirmed packing slips (newest first), optionally scoped to one project."""
    stmt = select(PackingSlip).options(selectinload(PackingSlip.items)).order_by(PackingSlip.shipped_at.desc())
    if project_id is not None:
        stmt = stmt.where(PackingSlip.project_id == project_id)
    return list(session.scalars(stmt).unique().all())


def _returned_quantities(session: Session, packing_slip_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Sum of already-returned quantity per packing_slip_item_id for a slip."""
    rows = session.execute(
        select(
            ShipmentReturnItem.packing_slip_item_id,
            func.sum(ShipmentReturnItem.quantity).label("total_returned"),
        )
        .join(ShipmentReturn, ShipmentReturnItem.shipment_return_id == ShipmentReturn.id)
        .where(ShipmentReturn.packing_slip_id == packing_slip_id)
        .group_by(ShipmentReturnItem.packing_slip_item_id)
    ).all()
    return {row.packing_slip_item_id: row.total_returned for row in rows}


def get_returnable_lines(session: Session, packing_slip_id: uuid.UUID) -> list[dict]:
    """For a slip, list each LOOSE line with shipped / already-returned / still-returnable quantity."""
    ps = session.scalars(
        select(PackingSlip).options(selectinload(PackingSlip.items)).where(PackingSlip.id == packing_slip_id)
    ).first()
    if ps is None:
        raise NotFoundError(f"Packing slip {packing_slip_id} not found")

    already = _returned_quantities(session, packing_slip_id)
    lines = []
    for psi in ps.items:
        if psi.item_type != PullRequestItemType.LOOSE:
            continue
        returned = already.get(psi.id, 0)
        lines.append(
            {
                "packing_slip_item_id": psi.id,
                "opening_number": psi.opening_number,
                "product_code": psi.product_code,
                "hardware_category": psi.hardware_category,
                "shipped_quantity": psi.quantity,
                "returned_quantity": returned,
                "returnable_quantity": psi.quantity - returned,
            }
        )
    return lines


def create_shipment_return(
    session: Session,
    *,
    packing_slip_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    returned_by: str,
    reference: str | None,
    items: list[dict],
) -> ShipmentReturn:
    """Record a shipment return and route each loose line to its disposition.

    Each item dict carries: packing_slip_item_id, quantity, disposition (ReturnDisposition),
    and optional rma_reference / reason_text.

    RETURN_TO_PROJECT re-creates a fresh, unlocated InventoryLocation for the slip's project
    (drops into Put-Away). NON_STOCK / RMA_DEFECTIVE merge into the stock pool at the chosen
    warehouse; RMA also flags the merged units deficient so they surface in Deficient Items review.
    """
    if not returned_by:
        raise ValidationError("returned_by is required", field="returned_by")
    if not items:
        raise ValidationError("items must not be empty", field="items")
    reference = (reference or "").strip() or None

    # 1. Lock the slip, then load it with items
    locked = lock_rows(session, PackingSlip, [packing_slip_id])
    if not locked:
        raise NotFoundError(f"Packing slip {packing_slip_id} not found")
    ps = session.scalars(
        select(PackingSlip).options(selectinload(PackingSlip.items)).where(PackingSlip.id == packing_slip_id)
    ).first()

    # 2. Validate destination warehouse
    warehouse = session.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    if not warehouse.is_active:
        raise ValidationError("Destination warehouse is not active", field="warehouse_id")

    psi_by_id = {psi.id: psi for psi in ps.items}
    already = _returned_quantities(session, packing_slip_id)

    # 3. Validate every line up front (cumulative within this call too)
    requested_per_psi: dict[uuid.UUID, int] = defaultdict(int)
    for item in items:
        qty = item["quantity"]
        if qty < 1:
            raise ValidationError("quantity must be >= 1", field="quantity")
        psi = psi_by_id.get(item["packing_slip_item_id"])
        if psi is None:
            raise ValidationError("Line is not part of this packing slip", field="packing_slip_item_id")
        if psi.item_type != PullRequestItemType.LOOSE:
            raise ValidationError("Only loose-hardware lines can be returned", field="packing_slip_item_id")
        rma_ref = item.get("rma_reference")
        if rma_ref is not None and len(rma_ref) > 100:
            raise ValidationError("rma_reference must be 100 characters or fewer", field="rma_reference")
        requested_per_psi[psi.id] += qty

    for psi_id, requested in requested_per_psi.items():
        psi = psi_by_id[psi_id]
        returnable = psi.quantity - already.get(psi_id, 0)
        if requested > returnable:
            raise ValidationError(
                f"Return quantity {requested} exceeds returnable {returnable} for {psi.product_code}",
                field="quantity",
            )

    # 4. Create the return header
    now = datetime.utcnow()
    shipment_return = ShipmentReturn(
        id=uuid.uuid4(),
        packing_slip_id=ps.id,
        warehouse_id=warehouse_id,
        returned_by=returned_by,
        returned_at=now,
        reference=reference,
    )
    session.add(shipment_return)
    session.flush()

    # 5. Process each returned line
    for item in items:
        psi = psi_by_id[item["packing_slip_item_id"]]
        qty = item["quantity"]
        disposition = item["disposition"]
        rma_reference = item.get("rma_reference")
        reason_text = item.get("reason_text")

        return_item = ShipmentReturnItem(
            id=uuid.uuid4(),
            shipment_return_id=shipment_return.id,
            packing_slip_item_id=psi.id,
            disposition=disposition,
            quantity=qty,
            hardware_category=psi.hardware_category,
            product_code=psi.product_code,
            opening_number=psi.opening_number,
            rma_reference=rma_reference,
            reason_text=reason_text,
        )
        session.add(return_item)
        session.flush()

        detail = {
            "shipmentReturnId": str(shipment_return.id),
            "packingSlipId": str(ps.id),
            "packingSlipNumber": ps.packing_slip_number,
            "disposition": disposition.value,
            "quantity": qty,
            "hardwareCategory": psi.hardware_category,
            "productCode": psi.product_code,
            "rmaReference": rma_reference,
        }

        if disposition == ReturnDisposition.RETURN_TO_PROJECT:
            # Fresh, unlocated inventory for the origin project — re-enters Put-Away.
            inv_loc = InventoryLocationModel(
                id=uuid.uuid4(),
                project_id=ps.project_id,
                warehouse_id=warehouse_id,
                hardware_category=psi.hardware_category,
                product_code=psi.product_code,
                quantity=qty,
                deficient_quantity=0,
                aisle=None,
                row=None,
                bay=None,
                shipment_return_item_id=return_item.id,
                received_at=now,
            )
            session.add(inv_loc)
            session.flush()
            return_item.resulting_inventory_location_id = inv_loc.id
            _log_audit_event(
                session,
                project_id=ps.project_id,
                entity_type=AuditEntityType.INVENTORY_LOCATION,
                entity_id=inv_loc.id,
                action=AuditAction.RETURN,
                performed_by=returned_by,
                detail=detail,
            )
        else:
            # NON_STOCK or RMA_DEFECTIVE — merge into the stock pool.
            stock_row = _find_or_create_stock_row(
                session,
                warehouse_id=warehouse_id,
                hardware_category=psi.hardware_category,
                product_code=psi.product_code,
                aisle=None,
                row=None,
                bay=None,
                received_at=now,
            )
            stock_row.quantity += qty
            if disposition == ReturnDisposition.RMA_DEFECTIVE:
                stock_row.deficient_quantity += qty
            session.flush()
            return_item.resulting_stock_item_id = stock_row.id
            _log_audit_event(
                session,
                project_id=None,
                entity_type=AuditEntityType.STOCK_ITEM,
                entity_id=stock_row.id,
                action=AuditAction.RETURN,
                performed_by=returned_by,
                detail=detail,
            )

    return shipment_return


def get_packing_slip(session: Session, packing_slip_id: uuid.UUID) -> PackingSlip | None:
    """Single packing slip with items eagerly loaded (mutation response reload)."""
    stmt = select(PackingSlip).options(selectinload(PackingSlip.items)).where(PackingSlip.id == packing_slip_id)
    return session.scalars(stmt).unique().first()


def get_shipment_return(session: Session, shipment_return_id: uuid.UUID) -> ShipmentReturn | None:
    """Single shipment return with items eagerly loaded (mutation response reload)."""
    stmt = (
        select(ShipmentReturn)
        .options(selectinload(ShipmentReturn.items))
        .where(ShipmentReturn.id == shipment_return_id)
    )
    return session.scalars(stmt).unique().first()


# ---------------------------------------------------------------------------
# Shipping-out requests (#293): the accept gate between Start-a-Task and the warehouse pull.
# Start-a-Task mints a PENDING ShippingOutRequest; a signed-in user accepts it, which mints the
# existing warehouse PullRequest (SHIPPING_OUT, PENDING) that the warehouse approves unchanged.
# ---------------------------------------------------------------------------


def get_shipping_out_request(session: Session, request_id: uuid.UUID) -> ShippingOutRequest | None:
    """Single shipping-out request with items eagerly loaded (mutation/finalize response reload)."""
    stmt = (
        select(ShippingOutRequest)
        .options(selectinload(ShippingOutRequest.items))
        .where(ShippingOutRequest.id == request_id)
    )
    return session.scalars(stmt).unique().first()


def get_shipping_out_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    status: ShippingOutRequestStatus | None = None,
    reopenable_only: bool = False,
) -> list[ShippingOutRequest]:
    """List shipping-out requests for the accept UI (#293). Defaults to PENDING when no status is
    given. Items are eagerly loaded (shipping_out_request_to_type walks them).

    reopenable_only (#325): keep only requests still in the reopen window - their minted warehouse
    PullRequest is still PENDING (the warehouse has not started the pull). The Approved view passes this
    so it lists exactly the requests Reopen can act on, not every request ever accepted."""
    effective_status = status if status is not None else ShippingOutRequestStatus.PENDING
    stmt = (
        select(ShippingOutRequest)
        .options(selectinload(ShippingOutRequest.items))
        .where(ShippingOutRequest.status == effective_status)
        .order_by(ShippingOutRequest.created_at.asc())
    )
    if project_id is not None:
        stmt = stmt.where(ShippingOutRequest.project_id == project_id)
    if reopenable_only:
        stmt = stmt.join(PullRequestModel, ShippingOutRequest.pull_request_id == PullRequestModel.id).where(
            PullRequestModel.status == PullRequestStatus.PENDING
        )
    return list(session.scalars(stmt).unique().all())


def find_live_shipping_claims(
    session: Session,
    project_id: uuid.UUID,
    *,
    opening_item_ids: list[uuid.UUID] | None = None,
    opening_leaf_specs: list[tuple[str, int | None]] | None = None,
) -> dict:
    """Assembled leaves a still-live shipping-out request has already claimed (#342).

    Returns `{"by_opening_item": {opening_item_id: request_number},
              "by_opening_leaf": {(opening_number, leaf): request_number}}` - the first for the
    "this leaf is already on a shipping request" duplicate guard, the second for the cross-type
    conflict a shop-assembly creation has to see (the same physical leaf cannot be both on its way
    out the door and back on the assembly bench).

    Live is defined by the *pull*, not by the request status, because a shipping-out request stays
    APPROVED forever once accepted: PENDING, or APPROVED while its minted PullRequest is still
    PENDING/IN_PROGRESS. A request whose pull has completed has shipped its leaves, which is a
    different state that the OpeningItem's own `state` already refuses. One query, outer-joined to
    the pull so an APPROVED request whose PR was discarded by a reopen still reads as live (it is
    back to PENDING and still holding).
    """
    result: dict = {"by_opening_item": {}, "by_opening_leaf": {}}
    if not opening_item_ids and not opening_leaf_specs:
        return result

    live_request = or_(
        ShippingOutRequest.status == ShippingOutRequestStatus.PENDING,
        and_(
            ShippingOutRequest.status == ShippingOutRequestStatus.APPROVED,
            or_(
                PullRequestModel.id.is_(None),
                PullRequestModel.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS]),
            ),
        ),
    )
    stmt = (
        select(
            ShippingOutRequestItem.opening_item_id,
            ShippingOutRequestItem.opening_number,
            ShippingOutRequestItem.leaf,
            ShippingOutRequest.request_number,
        )
        .join(ShippingOutRequest, ShippingOutRequestItem.shipping_out_request_id == ShippingOutRequest.id)
        .outerjoin(PullRequestModel, ShippingOutRequest.pull_request_id == PullRequestModel.id)
        .where(
            ShippingOutRequest.project_id == project_id,
            ShippingOutRequestItem.item_type == PullRequestItemType.OPENING_ITEM,
            live_request,
        )
    )
    wanted_items = set(opening_item_ids or [])
    wanted_leaves = set(opening_leaf_specs or [])
    for opening_item_id, opening_number, leaf, request_number in session.execute(stmt).all():
        if opening_item_id is not None and opening_item_id in wanted_items:
            result["by_opening_item"][opening_item_id] = request_number
        if (opening_number, leaf) in wanted_leaves:
            result["by_opening_leaf"][(opening_number, leaf)] = request_number
    return result


def accept_shipping_out_request(
    session: Session,
    request_id: uuid.UUID,
    accepted_by: str,
) -> ShippingOutRequest:
    """Accept a PENDING shipping-out request (#293): mint the warehouse PullRequest (SHIPPING_OUT,
    PENDING) copying this request's items into PullRequestItems, flip the request to APPROVED, and
    stamp pull_request_id.

    A pure human approval gate (#342), like its shop-assembly twin: the request's LOOSE lines
    reserved their hardware when the request was created and still hold that claim, so there is
    nothing to re-check here and nothing to release. The claim is spent when the warehouse approves
    the pull."""
    stmt = (
        select(ShippingOutRequest)
        .options(selectinload(ShippingOutRequest.items))
        .where(ShippingOutRequest.id == request_id)
    )
    req = session.scalars(stmt).unique().first()
    if req is None:
        raise NotFoundError(f"Shipping-out request {request_id} not found")
    if req.status != ShippingOutRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shipping-out request must be Pending to accept, got {req.status.value}")

    now = datetime.utcnow()
    pr = PullRequestModel(
        id=uuid.uuid4(),
        request_number=req.request_number,
        project_id=req.project_id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.PENDING,
        requested_by=accepted_by,
    )
    session.add(pr)
    session.flush()

    # Leaf fallback (#335): requests written before shipping_out_request_items.leaf existed carry a
    # null leaf, so read it off the OpeningItem they point at. One grouped query, not one per line.
    unleafed_oi_ids = {i.opening_item_id for i in req.items if i.opening_item_id is not None and i.leaf is None}
    leaf_by_opening_item: dict[uuid.UUID, int | None] = {}
    if unleafed_oi_ids:
        leaf_by_opening_item = dict(
            session.execute(
                select(OpeningItemModel.id, OpeningItemModel.leaf).where(OpeningItemModel.id.in_(unleafed_oi_ids))
            ).all()
        )

    for item in req.items:
        session.add(
            PullRequestItemModel(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                item_type=item.item_type,
                opening_number=item.opening_number,
                opening_item_id=item.opening_item_id,
                # Snapshot the door leaf (#311/#335) so a leaf-1 pull reads distinct from a leaf-2 pull,
                # mirroring what the shop-assembly accept does with ShopAssemblyOpening.leaf.
                leaf=item.leaf if item.leaf is not None else leaf_by_opening_item.get(item.opening_item_id),
                hardware_category=item.hardware_category,
                product_code=item.product_code,
                requested_quantity=item.requested_quantity,
            )
        )

    req.status = ShippingOutRequestStatus.APPROVED
    req.approved_by = accepted_by
    req.approved_at = now
    req.pull_request_id = pr.id
    return req


def reject_shipping_out_request(
    session: Session,
    request_id: uuid.UUID,
    rejected_by: str,
    reason: str | None,
) -> ShippingOutRequest:
    """Reject a PENDING shipping-out request (#293). Mints no PullRequest, and **releases the
    request's inventory reservations** (#342): its LOOSE lines have been holding a claim on loose
    stock since creation, and a dead request must not keep it. OPENING_ITEM lines never reserved
    anything (an assembled leaf left fungible inventory at assembly), so there is nothing of theirs
    to release. Also the recovery path after a reopen - a reopened request is PENDING and still
    holding, and this is what finally lets go."""
    from app.repositories import warehouse as warehouse_repository

    stmt = (
        select(ShippingOutRequest)
        .options(selectinload(ShippingOutRequest.items))
        .where(ShippingOutRequest.id == request_id)
    )
    req = session.scalars(stmt).unique().first()
    if req is None:
        raise NotFoundError(f"Shipping-out request {request_id} not found")
    if req.status != ShippingOutRequestStatus.PENDING:
        raise InvalidStateTransitionError(f"Shipping-out request must be Pending to reject, got {req.status.value}")

    req.status = ShippingOutRequestStatus.REJECTED
    req.rejected_by = rejected_by
    req.rejection_reason = (reason or "").strip() or None
    req.rejected_at = datetime.utcnow()
    warehouse_repository.release_reservations(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)
    return req


def reopen_shipping_out_request(
    session: Session,
    request_id: uuid.UUID,
) -> ShippingOutRequest:
    """Reopen an APPROVED shipping-out request back to PENDING (#325): undo an erroneous accept by
    hard-deleting the warehouse PullRequest the accept minted (and its items), unlinking it, and
    flipping the request back to PENDING so it can be re-accepted or rejected. Only allowed while the
    minted PR is still PENDING - if the warehouse has already approved/completed it, inventory has
    moved and the reopen is refused (see discard_pending_pull_request)."""
    from app.repositories import warehouse as warehouse_repository

    req = session.scalars(select(ShippingOutRequest).where(ShippingOutRequest.id == request_id)).first()
    if req is None:
        raise NotFoundError(f"Shipping-out request {request_id} not found")
    if req.status != ShippingOutRequestStatus.APPROVED:
        raise InvalidStateTransitionError(f"Shipping-out request must be Approved to reopen, got {req.status.value}")

    # Unlink the request and flush BEFORE discarding the PR, so deleting it does not trip the
    # shipping_out_requests.pull_request_id foreign key. discard_pending_pull_request still guards that
    # the PR is unworked (PENDING) and rolls the whole transaction back (nothing commits) if not.
    pr_id = req.pull_request_id
    req.status = ShippingOutRequestStatus.PENDING
    req.approved_by = None
    req.approved_at = None
    req.pull_request_id = None
    session.flush()

    warehouse_repository.discard_pending_pull_request(session, pr_id)
    return req
