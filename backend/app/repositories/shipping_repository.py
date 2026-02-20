"""Repository for shipping and packing slip data access."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_request import (
    PullRequest as PullRequestModel,
    PullRequestItem as PullRequestItemModel,
)
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.enums import (
    OpeningItemState,
    PullRequestSource,
    PullRequestStatus,
    PullRequestItemType,
    NotificationType,
)
from app.services.locking import lock_rows
from app.services import notification_service
from app.errors import NotFoundError, ValidationError, ConflictError, InvalidStateTransitionError


def get_ship_ready_items(
    session: Session,
    project_id: uuid.UUID,
) -> dict:
    """Query ship-ready opening items and compute available loose hardware."""
    # 1. Opening items with state = Ship_Ready
    oi_stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(
            OpeningItemModel.project_id == project_id,
            OpeningItemModel.state == OpeningItemState.SHIP_READY,
        )
        .order_by(OpeningItemModel.opening_number.asc())
    )
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
            PullRequestModel.project_id == project_id,
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
        .where(
            PackingSlip.project_id == project_id,
            PackingSlipItem.item_type == PullRequestItemType.LOOSE,
        )
        .group_by(
            PackingSlipItem.opening_number,
            PackingSlipItem.hardware_category,
            PackingSlipItem.product_code,
        )
    )
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
            loose_items.append({
                "opening_number": key[0],
                "hardware_category": key[1],
                "product_code": key[2],
                "available_quantity": available,
            })

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
    # 1. Validate packing_slip_number
    if not packing_slip_number or len(packing_slip_number) < 1 or len(packing_slip_number) > 50:
        raise ValidationError("packing_slip_number must be 1-50 characters", field="packing_slip_number")

    if not shipped_by:
        raise ValidationError("shipped_by must not be empty", field="shipped_by")

    if not items:
        raise ValidationError("items must not be empty", field="items")

    # Check uniqueness
    existing_stmt = select(PackingSlip).where(
        PackingSlip.packing_slip_number == packing_slip_number
    )
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
                raise InvalidStateTransitionError(
                    f"Opening item {oi.id} is not Ship_Ready (current: {oi.state.value})"
                )

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
