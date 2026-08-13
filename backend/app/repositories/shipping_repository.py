"""Repository for shipping and packing slip data access."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    NotificationType,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ReturnDisposition,
    ShipmentStatus,
    ShippingOutRequestStatus,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.pull_request import (
    PullRequest as PullRequestModel,
)
from app.models.pull_request import (
    PullRequestItem as PullRequestItemModel,
)
from app.models.shipment_container import ShipmentContainer
from app.models.shipping import (
    PackingSlip,
    PackingSlipItem,
    ShipmentReturn,
    ShipmentReturnItem,
)
from app.models.shipping_out_request import (
    ShippingOutRequest,
)
from app.models.warehouse import Warehouse
from app.repositories import project_repository, request_return_notes
from app.repositories.stock import _find_or_create_stock_row, _log_audit_event
from app.services import notification_service
from app.services.locking import lock_rows


def get_ship_ready_items(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> dict:
    """What a completed shipping-out pull has fulfilled but no slip has consumed yet.

    The staging pool: hardware that is off the shelf, on a cart, and waiting for a truck. Fulfilled
    minus shipped, per (opening, category, product).
    """
    # 1. Sum requested_quantity from completed Shipping_Out pulls
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

    # 2. Subtract what packing slips have already carried out
    shipped_stmt = (
        select(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
            func.sum(PackingSlipItem.quantity).label("total_shipped"),
        )
        .join(PackingSlip, PackingSlipItem.packing_slip_id == PackingSlip.id)
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

    # 3. What is left staged and shippable
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

    # Sort by opening, with the unattributed lines (#451) last: they belong to the project rather
    # than to any door, so they read as a trailing "everything else" group rather than jumping the
    # queue ahead of opening 0101. `or ""` alone would sort them first, which is the wrong end.
    loose_items.sort(key=lambda x: (x["opening_number"] is None, x["opening_number"] or ""))

    return {"loose_items": loose_items}


# Every column of the Delivery Request header (#447), in the order the paper form asks for them.
# Named once because two paths write it - `confirm_shipment` fills it in and `update_shipment_details`
# rewrites it - and a field that reached one but not the other would silently stop being editable.
DELIVERY_REQUEST_FIELDS = (
    "pickup_date",
    "delivery_date",
    "shipper_email",
    "shipper_phone",
    "pickup_location",
    "shipment_method",
    "carrier_tag_bol",
    "weight_lbs",
    "delivery_address",
    "special_instructions",
    "gate_number",
    "forklift_onsite",
    "material_coming_back",
    "site_material_included",
    "construction_temp_keys",
    "extra_frame_anchors",
    "contractor_contact_name",
    "contractor_contact_phone",
    "ucsh_contact_name",
    "ucsh_contact_phone",
    "sales_order_number",
)

# packing_slips.weight_lbs is Numeric(10, 2): eight digits ahead of the decimal point and no more.
# Anything at or above this is refused here rather than at flush time, where Postgres raises a raw
# numeric overflow that aborts the entire transaction - on the confirm path that would take the whole
# shipment down over a typo in one box of the form.
_MAX_WEIGHT_LBS = 100000000


def _apply_delivery_details(packing_slip: PackingSlip, details: dict | None) -> None:
    """Write the whole Delivery Request header onto a slip, blanks included.

    Full replace, every field, every time: a key the caller left out is written as null, not skipped.
    That is what makes clearing a field possible at all - the alternative reading ("absent means
    unchanged") leaves a Delivery Request that can be corrected but never emptied, so a phone number
    typed against the wrong shipment could not be taken back off it.

    Whitespace-only text is stored as null rather than as a string of spaces, so "blank" has one
    representation and the printed form does not render an invisible answer.

    The one value that is range-checked is the weight, because it is the one the column can refuse.
    Left to the database it fails as an overflow at commit and rolls back the confirm that was
    carrying it, so a mistyped weight would look like shipping being broken rather than like a bad
    number in a box.
    """
    values = details or {}
    weight = values.get("weight_lbs")
    if weight is not None and (weight < 0 or weight >= _MAX_WEIGHT_LBS):
        raise ValidationError(
            f"weight_lbs must be between 0 and {_MAX_WEIGHT_LBS - 1}.99 pounds",
            field="weight_lbs",
        )
    for field in DELIVERY_REQUEST_FIELDS:
        value = values.get(field)
        if isinstance(value, str):
            value = value.strip() or None
        setattr(packing_slip, field, value)


def confirm_shipment(
    session: Session,
    project_id: uuid.UUID,
    packing_slip_number: str,
    shipped_by: str,
    items: list[dict],
    details: dict | None = None,
) -> PackingSlip:
    """Cut a packing slip against what a completed shipping-out pull staged.

    The slip is born SCHEDULED (#447) and carries the Delivery Request header the shipping
    department filled in. The status is documentation of the truck's journey and nothing else - this
    call is still the moment the hardware is claimed.

    Args:
        session: SQLAlchemy session
        project_id: UUID of the project
        packing_slip_number: Unique slip number (1-50 chars)
        shipped_by: Name of shipper
        items: list of dicts with keys opening_number, hardware_category, product_code, quantity,
            and optional building / floor / location placement.
        details: the Delivery Request header (DELIVERY_REQUEST_FIELDS). Every field is optional -
            the form is filled in against whatever the site has said, and a blank is a real answer.
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

    # 2. Validate availability against the staged pool
    ship_ready = get_ship_ready_items(session, project_id)
    available_loose: dict[tuple, int] = {}
    for li in ship_ready["loose_items"]:
        key = (li["opening_number"], li["hardware_category"], li["product_code"])
        available_loose[key] = li["available_quantity"]

    cart_agg: dict[tuple, int] = defaultdict(int)
    for item in items:
        key = (item["opening_number"], item["hardware_category"], item["product_code"])
        cart_agg[key] += item["quantity"]

    for key, requested in cart_agg.items():
        available = available_loose.get(key, 0)
        if requested > available:
            raise ValidationError(
                f"Insufficient staged hardware: {key[2]} ({key[1]}) for opening {key[0]} - "
                f"requested {requested}, available {available}",
                field="items",
            )

    # 3. Create PackingSlip
    now = datetime.utcnow()
    packing_slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=packing_slip_number,
        project_id=project_id,
        shipped_by=shipped_by,
        shipped_at=now,
        status=ShipmentStatus.SCHEDULED,
    )
    _apply_delivery_details(packing_slip, details)
    session.add(packing_slip)
    session.flush()

    # 4. Create PackingSlipItems
    for item in items:
        session.add(
            PackingSlipItem(
                id=uuid.uuid4(),
                packing_slip_id=packing_slip.id,
                opening_number=item["opening_number"],
                # Where it was going, as the cart named it (#452). The Delivery Request prints these
                # after the opening number, so a reprint says what the driver's copy said.
                building=item.get("building"),
                floor=item.get("floor"),
                location=item.get("location"),
                product_code=item["product_code"],
                hardware_category=item["hardware_category"],
                quantity=item["quantity"],
            )
        )

    # 5. Create notification
    item_count = sum(i["quantity"] for i in items)
    notification_service.create_notification(
        session,
        project_id=project_id,
        recipient_role="Warehouse Staff",
        notification_type=NotificationType.SHIPMENT_COMPLETED,
        message=f"Shipment {packing_slip_number} confirmed. {item_count} items shipped.",
    )

    return packing_slip


# ---------------------------------------------------------------------------
# The Delivery Request lifecycle (#447): SCHEDULED -> PICKED_UP -> DELIVERED.
#
# Documentation of the truck's journey, not of the hardware's. Nothing here moves inventory: the
# claim was made when the shipment was confirmed, and these three states only record where the load
# got to and who said so. The ladder is strict and one-way in both directions - a shipment cannot be
# delivered before it has been collected, and neither leg can be walked back, because both are
# statements about something that has already physically happened.
# ---------------------------------------------------------------------------


def _locked_packing_slip(session: Session, packing_slip_id: uuid.UUID) -> PackingSlip:
    """The slip, row-locked for a header rewrite or a lifecycle stamp.

    Locked for the same reason the return path locks it: two people looking at the Shipments page can
    press the same button at the same time, and the state check has to be made against a row nobody
    else is mid-transition on.
    """
    locked = lock_rows(session, PackingSlip, [packing_slip_id])
    if not locked:
        raise NotFoundError(f"Packing slip {packing_slip_id} not found")
    return locked[0]


def update_shipment_details(
    session: Session,
    packing_slip_id: uuid.UUID,
    details: dict,
) -> PackingSlip:
    """Rewrite the Delivery Request header of a shipment that has not left yet (#447).

    Refused unless the shipment is still SCHEDULED. Once it has been picked up a driver is carrying a
    printed copy, and a record that no longer matches the paper in the cab is worse than one with a
    typo in it - the site signs the paper, and any dispute is settled against what it says.

    Full replace over `DELIVERY_REQUEST_FIELDS`: a field given as None is CLEARED. What is
    deliberately not editable is everything that is not the paper form - the slip number, the
    project, the items, and who shipped it and when. Those are the record of what left the building,
    which is the one thing an edit must never be able to rewrite.
    """
    ps = _locked_packing_slip(session, packing_slip_id)
    if ps.status != ShipmentStatus.SCHEDULED:
        raise InvalidStateTransitionError(
            f"Delivery Request {ps.packing_slip_number} can only be edited while Scheduled (current: {ps.status.value})"
        )
    _apply_delivery_details(ps, details)
    return ps


def mark_shipment_picked_up(
    session: Session,
    packing_slip_id: uuid.UUID,
    actor: str,
) -> PackingSlip:
    """SCHEDULED -> PICKED_UP: the carrier has the load and the paper (#447).

    Stamps who confirmed it and when, and closes the header to further edits. Deducts nothing - the
    hardware left inventory when the shipment was confirmed.
    """
    ps = _locked_packing_slip(session, packing_slip_id)
    if ps.status != ShipmentStatus.SCHEDULED:
        raise InvalidStateTransitionError(
            f"Delivery Request {ps.packing_slip_number} must be Scheduled to mark picked up "
            f"(current: {ps.status.value})"
        )
    ps.status = ShipmentStatus.PICKED_UP
    ps.picked_up_at = datetime.utcnow()
    ps.picked_up_by = actor
    return ps


def mark_shipment_delivered(
    session: Session,
    packing_slip_id: uuid.UUID,
    actor: str,
) -> PackingSlip:
    """PICKED_UP -> DELIVERED: the load reached the site (#447).

    Only from PICKED_UP. A shipment cannot arrive somewhere it was never collected for, and letting
    SCHEDULED jump straight here would quietly lose the fact that nobody ever recorded a pickup.
    """
    ps = _locked_packing_slip(session, packing_slip_id)
    if ps.status != ShipmentStatus.PICKED_UP:
        raise InvalidStateTransitionError(
            f"Delivery Request {ps.packing_slip_number} must be Picked Up to mark delivered "
            f"(current: {ps.status.value})"
        )
    ps.status = ShipmentStatus.DELIVERED
    ps.delivered_at = datetime.utcnow()
    ps.delivered_by = actor
    return ps


# ---------------------------------------------------------------------------
# Shipment returns (issue #89): a shipment comes back from site.
# Only loose-hardware lines are returnable; opening items never re-enter.
# ---------------------------------------------------------------------------


def list_packing_slips(
    session: Session,
    project_id: uuid.UUID | None = None,
) -> list[PackingSlip]:
    """List confirmed packing slips (newest first), optionally scoped to one project.

    Containers and their items are eagerly loaded because `packing_slip_to_type` walks them to build
    the per-container sections the Delivery Request prints - lazy loading here is two extra queries
    per slip on a list view (CLAUDE.md perf rules).
    """
    stmt = (
        select(PackingSlip)
        .options(
            selectinload(PackingSlip.items),
            selectinload(PackingSlip.containers).selectinload(ShipmentContainer.items),
        )
        .order_by(PackingSlip.shipped_at.desc())
    )
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
    """For a slip, list each line with shipped / already-returned / still-returnable quantity."""
    ps = session.scalars(
        select(PackingSlip).options(selectinload(PackingSlip.items)).where(PackingSlip.id == packing_slip_id)
    ).first()
    if ps is None:
        raise NotFoundError(f"Packing slip {packing_slip_id} not found")

    already = _returned_quantities(session, packing_slip_id)
    lines = []
    for psi in ps.items:
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
    """Single packing slip with items and containers eagerly loaded (mutation response reload).

    Containers are loaded here too because every mutation that answers with a slip hands it to
    `packing_slip_to_type`, which walks them - and a lazy load after the session closes is a
    DetachedInstanceError rather than a slow query.
    """
    stmt = (
        select(PackingSlip)
        .options(
            selectinload(PackingSlip.items),
            selectinload(PackingSlip.containers).selectinload(ShipmentContainer.items),
        )
        .where(PackingSlip.id == packing_slip_id)
    )
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
# Shipping-out requests (#293): the accept gate between Start-a-Request and the warehouse pull.
# Start-a-Request mints a PENDING ShippingOutRequest; a signed-in user accepts it, which mints the
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


def get_request_stages(session: Session, requests: list[ShippingOutRequest]) -> dict[uuid.UUID, str]:
    """Where each shipping-out request sits on the ladder, in ONE query for the whole list (CLAUDE.md
    perf rules). The twin of `shop_assembly_repository.get_request_stages`: a cancelled pull reads as
    REQUESTED because cancellation returns its request to PENDING for re-acceptance (#343)."""
    if not requests:
        return {}

    pull_ids = [r.pull_request_id for r in requests if r.pull_request_id is not None]
    pull_status_by_id: dict[uuid.UUID, PullRequestStatus] = {}
    if pull_ids:
        pull_status_by_id = {
            pull_id: status
            for pull_id, status in session.execute(
                select(PullRequestModel.id, PullRequestModel.status).where(PullRequestModel.id.in_(pull_ids))
            ).all()
        }
    return {r.id: _shipping_stage_for(r, pull_status_by_id.get(r.pull_request_id)) for r in requests}


def _shipping_stage_for(request: ShippingOutRequest, pull_status: PullRequestStatus | None) -> str:
    if request.status == ShippingOutRequestStatus.REJECTED:
        return "REJECTED"
    if request.status == ShippingOutRequestStatus.PENDING:
        return "REQUESTED"
    if pull_status == PullRequestStatus.COMPLETED:
        return "DONE"
    if pull_status == PullRequestStatus.IN_PROGRESS:
        return "PULLING"
    if pull_status == PullRequestStatus.CANCELLED or pull_status is None:
        return "REQUESTED"
    return "ACCEPTED"


def get_return_notes(session: Session, requests: list[ShippingOutRequest]) -> dict[uuid.UUID, str | None]:
    """The "returned to Pending" note per request (#613), one query for the whole list. A PENDING
    request still pointing at a CANCELLED pull was put back on the accept board by that cancel. See
    `app.repositories.request_return_notes`."""
    pending = [r for r in requests if r.status == ShippingOutRequestStatus.PENDING]
    derived = request_return_notes.return_notes_for(session, pending)
    return {r.id: derived.get(r.id) for r in requests}


def accept_shipping_out_request(
    session: Session,
    request_id: uuid.UUID,
    accepted_by: str,
) -> ShippingOutRequest:
    """Accept a PENDING shipping-out request (#293): mint the warehouse PullRequest (SHIPPING_OUT,
    PENDING) copying this request's items into PullRequestItems, flip the request to APPROVED, and
    stamp pull_request_id.

    A pure human approval gate (#342), like its shop-assembly twin: the request reserved its
    hardware when it was created and still holds that claim, so there is nothing to re-check here
    and nothing to release. The claim is spent when the pick is confirmed."""
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

    for item in req.items:
        session.add(
            PullRequestItemModel(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                opening_number=item.opening_number,
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
    request's inventory reservations** (#342): it has been holding a claim on stock since creation,
    and a dead request must not keep it. There is nothing of an accepted request's
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
