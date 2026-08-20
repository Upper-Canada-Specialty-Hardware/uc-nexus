"""Warehouse dashboard stats + per-project purchasing progress rollups."""

import uuid
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.enums import HardwareItemState, POStatus, PullRequestSource, PullRequestStatus, ReturnDisposition
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.pull_request import PullRequestItem as PullRequestItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.models.shipping import PackingSlipItem as PackingSlipItemModel
from app.models.shipping import ShipmentReturn as ShipmentReturnModel
from app.models.shipping import ShipmentReturnItem as ShipmentReturnItemModel
from app.models.stock_item import StockItem as StockItemModel


def get_warehouse_dashboard(session: Session) -> dict:
    """Compute cross-project warehouse dashboard statistics."""
    from datetime import timedelta

    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    # Total inventory value and item count — LEFT JOIN since stock-allocated rows have no PO line.
    # Cost falls back to the row's own off-PO unit_cost (the SharePoint migration), so migrated stock
    # values correctly instead of at zero; a PO row still reads its line cost.
    inv_stats = session.execute(
        select(
            func.coalesce(func.sum(InventoryLocationModel.quantity), 0),
            func.coalesce(
                func.sum(
                    InventoryLocationModel.quantity
                    * func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost, 0)
                ),
                0,
            ),
        ).outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
    ).one()

    # Unlocated count
    unlocated_count = (
        session.scalar(
            select(func.count())
            .select_from(InventoryLocationModel)
            .where(
                InventoryLocationModel.aisle.is_(None),
                InventoryLocationModel.quantity > 0,
            )
        )
        or 0
    )

    # Stock-pool tiles. stock_item_count is units on hand (the same sense as total_item_count above);
    # stock_unlocated_count is the row count with no aisle, mirroring unlocated_count on the project
    # side. stock_value prices the pool off the rows' own off-PO unit_cost (the SharePoint migration
    # writes it; PO-received pool stock carries none and counts 0) - without it a migration landing
    # mostly STOCK entries changed total inventory value by nothing.
    stock_item_count = session.scalar(select(func.coalesce(func.sum(StockItemModel.quantity), 0))) or 0
    stock_value = (
        session.scalar(
            select(func.coalesce(func.sum(StockItemModel.quantity * func.coalesce(StockItemModel.unit_cost, 0)), 0))
        )
        or 0
    )
    stock_unlocated_count = (
        session.scalar(
            select(func.count())
            .select_from(StockItemModel)
            .where(
                StockItemModel.aisle.is_(None),
                StockItemModel.quantity > 0,
            )
        )
        or 0
    )

    # Pending pull requests by source
    pending_shop = (
        session.scalar(
            select(func.count())
            .select_from(PullRequestModel)
            .where(
                PullRequestModel.status == PullRequestStatus.PENDING,
                PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
                PullRequestModel.deleted_at.is_(None),
            )
        )
        or 0
    )
    pending_shipping = (
        session.scalar(
            select(func.count())
            .select_from(PullRequestModel)
            .where(
                PullRequestModel.status == PullRequestStatus.PENDING,
                PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
                PullRequestModel.deleted_at.is_(None),
            )
        )
        or 0
    )

    # Items received in last 7 days
    received_recent = (
        session.scalar(
            select(func.coalesce(func.sum(ReceiveLineItemModel.quantity_received), 0)).where(
                ReceiveLineItemModel.created_at >= seven_days_ago,
            )
        )
        or 0
    )

    # Back-ordered: count of active POs still owed anything (received < ordered on any line).
    back_ordered_po_count = (
        session.scalar(
            select(func.count(func.distinct(POModel.id)))
            .join(POLineItemModel, POLineItemModel.po_id == POModel.id)
            .where(
                POModel.status.in_([POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
                POModel.deleted_at.is_(None),
                POLineItemModel.ordered_quantity > POLineItemModel.received_quantity,
            )
        )
        or 0
    )

    # Deficient units held for review: the same rows the Deficient Items screen lists
    # (project inventory + stock pool), summed by quantity.
    deficient_project = (
        session.scalar(
            select(func.coalesce(func.sum(InventoryLocationModel.deficient_quantity), 0)).where(
                InventoryLocationModel.deficient_quantity > 0
            )
        )
        or 0
    )
    deficient_stock = (
        session.scalar(
            select(func.coalesce(func.sum(StockItemModel.deficient_quantity), 0)).where(
                StockItemModel.deficient_quantity > 0
            )
        )
        or 0
    )

    # Counted receives waiting on a Warehouse Manager - the approvals badge.
    from .receive_drafts import count_pending_drafts

    pending_drafts = count_pending_drafts(session)

    return {
        "total_item_count": int(inv_stats[0]),
        "total_value": float(inv_stats[1]),
        "unlocated_count": int(unlocated_count),
        "stock_item_count": int(stock_item_count),
        "stock_value": float(stock_value),
        "stock_unlocated_count": int(stock_unlocated_count),
        "pending_pull_shop": int(pending_shop),
        "pending_pull_shipping": int(pending_shipping),
        "received_last_7_days": int(received_recent),
        "back_ordered_po_count": int(back_ordered_po_count),
        "deficient_count": int(deficient_project) + int(deficient_stock),
        "pending_receive_draft_count": int(pending_drafts),
    }


PLACED_PO_STATUSES = (
    POStatus.GP_REGISTERED,
    POStatus.VENDOR_CONFIRMED,
    POStatus.PARTIALLY_RECEIVED,
    POStatus.CLOSED,
)


def get_project_progress_by_product(session: Session, project_id: uuid.UUID) -> list[dict]:
    """Per-product-code rollup of purchasing progress for a single project.

    Columns produced per (hardware_category, product_code) drawn from the project's hardware schedule:
    - required_quantity: sum of hardware_items.item_quantity
    - po_drafted: sum of po_line_items.ordered_quantity on DRAFT POs
    - ordered_quantity / received_quantity: sum of ordered/received on placed POs
      (status in PLACED_PO_STATUSES, deleted_at IS NULL)
    - back_ordered: sum of (ordered - received) on placed POs that are NOT yet CLOSED
      (i.e. GP_REGISTERED, VENDOR_CONFIRMED, PARTIALLY_RECEIVED)
    - shipped_out: sum of packing_slip_items.quantity for the project
    """
    required_subq = (
        select(
            HardwareItemModel.hardware_category.label("hardware_category"),
            HardwareItemModel.product_code.label("product_code"),
            func.sum(HardwareItemModel.item_quantity).label("required_quantity"),
        )
        .where(HardwareItemModel.project_id == project_id)
        .group_by(HardwareItemModel.hardware_category, HardwareItemModel.product_code)
        .subquery()
    )

    drafted_subq = (
        select(
            POLineItemModel.hardware_category.label("hardware_category"),
            POLineItemModel.product_code.label("product_code"),
            func.sum(POLineItemModel.ordered_quantity).label("po_drafted"),
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            POModel.deleted_at.is_(None),
            POModel.status == POStatus.DRAFT,
            POModel.project_id == project_id,
        )
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
        .subquery()
    )

    placed_subq = (
        select(
            POLineItemModel.hardware_category.label("hardware_category"),
            POLineItemModel.product_code.label("product_code"),
            func.sum(POLineItemModel.ordered_quantity).label("ordered_quantity"),
            func.sum(POLineItemModel.received_quantity).label("received_quantity"),
            func.sum(
                case(
                    (
                        POModel.status.in_(
                            [POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]
                        ),
                        POLineItemModel.ordered_quantity - POLineItemModel.received_quantity,
                    ),
                    else_=0,
                )
            ).label("back_ordered"),
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            POModel.deleted_at.is_(None),
            POModel.status.in_(PLACED_PO_STATUSES),
            POModel.project_id == project_id,
        )
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
        .subquery()
    )

    shipped_subq = (
        select(
            PackingSlipItemModel.hardware_category.label("hardware_category"),
            PackingSlipItemModel.product_code.label("product_code"),
            func.sum(PackingSlipItemModel.quantity).label("shipped_out"),
        )
        .join(PackingSlipModel, PackingSlipItemModel.packing_slip_id == PackingSlipModel.id)
        .where(PackingSlipModel.project_id == project_id)
        .group_by(PackingSlipItemModel.hardware_category, PackingSlipItemModel.product_code)
        .subquery()
    )

    stmt = (
        select(
            required_subq.c.hardware_category,
            required_subq.c.product_code,
            required_subq.c.required_quantity,
            func.coalesce(drafted_subq.c.po_drafted, 0).label("po_drafted"),
            func.coalesce(placed_subq.c.ordered_quantity, 0).label("ordered_quantity"),
            func.coalesce(placed_subq.c.received_quantity, 0).label("received_quantity"),
            func.coalesce(placed_subq.c.back_ordered, 0).label("back_ordered"),
            func.coalesce(shipped_subq.c.shipped_out, 0).label("shipped_out"),
        )
        .select_from(required_subq)
        .outerjoin(
            drafted_subq,
            and_(
                required_subq.c.hardware_category == drafted_subq.c.hardware_category,
                required_subq.c.product_code == drafted_subq.c.product_code,
            ),
        )
        .outerjoin(
            placed_subq,
            and_(
                required_subq.c.hardware_category == placed_subq.c.hardware_category,
                required_subq.c.product_code == placed_subq.c.product_code,
            ),
        )
        .outerjoin(
            shipped_subq,
            and_(
                required_subq.c.hardware_category == shipped_subq.c.hardware_category,
                required_subq.c.product_code == shipped_subq.c.product_code,
            ),
        )
        .order_by(required_subq.c.hardware_category, required_subq.c.product_code)
    )

    return [
        {
            "hardware_category": row.hardware_category,
            "product_code": row.product_code,
            "required_quantity": int(row.required_quantity),
            "po_drafted": int(row.po_drafted),
            "ordered_quantity": int(row.ordered_quantity),
            "received_quantity": int(row.received_quantity),
            "back_ordered": int(row.back_ordered),
            "shipped_out": int(row.shipped_out),
        }
        for row in session.execute(stmt).all()
    ]


def get_hardware_status_by_product(session: Session, project_ids: list[uuid.UUID]) -> list[dict]:
    """Per-product lifecycle rollup across one or more projects (admin Hardware Status page).

    One row per (hardware_category, product_code), quantities summed across the given projects:
    - required_quantity: sum of hardware_items.item_quantity
    - not_purchased: schedule lines still AVAILABLE (never drafted into a PO, or released back)
    - po_drafted: ordered_quantity on DRAFT POs
    - on_order: ordered - received on placed POs not yet CLOSED (still expected to arrive)
    - received_quantity: PO receipts on placed POs - NOT current inventory
    - on_hand: current project inventory (inventory_locations.quantity, pulls already deducted)
    - sent_to_shop: requested_quantity on COMPLETED SHOP_ASSEMBLY pulls. Shop assembly is outside
      the Nexus pipeline, so a shop pull is a lifecycle exit, the same shape as a shipment.
    - staged_for_shipping: the staging pool - completed SHIPPING_OUT pulls minus what packing slips
      carried out, positive part per (project, opening, category, product) to mirror
      shipping_repository.get_ship_ready_items, then summed per product.
    - shipped_out: sum of packing_slip_items.quantity - GROSS, returns never decrement it
    - returned_to_project: RETURN_TO_PROJECT shipment-return units. These are simultaneously back in
      on_hand AND still inside the gross shipped_out, so any reader summing "where the units are"
      across those columns must subtract this or count every returned unit twice (the re-import
      over-order guard does exactly that).

    Rows are the union of every key any source produced, so stock-allocated products that never
    appeared on a schedule still show (required 0) instead of vanishing with units on hand.
    """
    if not project_ids:
        return []

    fields = (
        "required_quantity",
        "not_purchased",
        "po_drafted",
        "on_order",
        "received_quantity",
        "on_hand",
        "sent_to_shop",
        "staged_for_shipping",
        "shipped_out",
        "returned_to_project",
    )
    rows: dict[tuple[str, str], dict] = {}

    def bucket(category: str, code: str) -> dict:
        key = (category, code)
        if key not in rows:
            rows[key] = dict.fromkeys(fields, 0)
        return rows[key]

    # Schedule: required total + the slice never drafted into a PO.
    required_stmt = (
        select(
            HardwareItemModel.hardware_category,
            HardwareItemModel.product_code,
            func.sum(HardwareItemModel.item_quantity).label("required_quantity"),
            func.sum(
                case(
                    (HardwareItemModel.state == HardwareItemState.AVAILABLE, HardwareItemModel.item_quantity),
                    else_=0,
                )
            ).label("not_purchased"),
        )
        .where(HardwareItemModel.project_id.in_(project_ids))
        .group_by(HardwareItemModel.hardware_category, HardwareItemModel.product_code)
    )
    for row in session.execute(required_stmt):
        b = bucket(row.hardware_category, row.product_code)
        b["required_quantity"] = int(row.required_quantity)
        b["not_purchased"] = int(row.not_purchased)

    # PO lines: drafted, receipts, and the open remainder still expected to arrive.
    po_stmt = (
        select(
            POLineItemModel.hardware_category,
            POLineItemModel.product_code,
            func.sum(case((POModel.status == POStatus.DRAFT, POLineItemModel.ordered_quantity), else_=0)).label(
                "po_drafted"
            ),
            func.sum(case((POModel.status.in_(PLACED_PO_STATUSES), POLineItemModel.received_quantity), else_=0)).label(
                "received_quantity"
            ),
            func.sum(
                case(
                    (
                        POModel.status.in_(
                            [POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]
                        ),
                        POLineItemModel.ordered_quantity - POLineItemModel.received_quantity,
                    ),
                    else_=0,
                )
            ).label("on_order"),
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(POModel.deleted_at.is_(None), POModel.project_id.in_(project_ids))
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
    )
    for row in session.execute(po_stmt):
        b = bucket(row.hardware_category, row.product_code)
        b["po_drafted"] = int(row.po_drafted)
        b["received_quantity"] = int(row.received_quantity)
        b["on_order"] = int(row.on_order)

    # Current shelves.
    on_hand_stmt = (
        select(
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.sum(InventoryLocationModel.quantity).label("on_hand"),
        )
        .where(InventoryLocationModel.project_id.in_(project_ids))
        .group_by(InventoryLocationModel.hardware_category, InventoryLocationModel.product_code)
    )
    for row in session.execute(on_hand_stmt):
        bucket(row.hardware_category, row.product_code)["on_hand"] = int(row.on_hand)

    # Exits to the shop.
    shop_stmt = (
        select(
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            func.sum(PullRequestItemModel.requested_quantity).label("sent_to_shop"),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id.in_(project_ids),
            PullRequestModel.source == PullRequestSource.SHOP_ASSEMBLY,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
        )
        .group_by(PullRequestItemModel.hardware_category, PullRequestItemModel.product_code)
    )
    for row in session.execute(shop_stmt):
        bucket(row.hardware_category, row.product_code)["sent_to_shop"] = int(row.sent_to_shop)

    # Shipping side: slips are the exits; the staging pool is pulled-minus-shipped per
    # (project, opening, category, product) - the same key get_ship_ready_items nets on, so this
    # page's Staged column agrees with what the shipping workspace offers to load.
    shipped_stmt = (
        select(
            PackingSlipModel.project_id,
            PackingSlipItemModel.opening_number,
            PackingSlipItemModel.hardware_category,
            PackingSlipItemModel.product_code,
            func.sum(PackingSlipItemModel.quantity).label("shipped"),
        )
        .join(PackingSlipModel, PackingSlipItemModel.packing_slip_id == PackingSlipModel.id)
        .where(PackingSlipModel.project_id.in_(project_ids))
        .group_by(
            PackingSlipModel.project_id,
            PackingSlipItemModel.opening_number,
            PackingSlipItemModel.hardware_category,
            PackingSlipItemModel.product_code,
        )
    )
    shipped_map: dict[tuple, int] = {}
    for row in session.execute(shipped_stmt):
        shipped_map[(row.project_id, row.opening_number, row.hardware_category, row.product_code)] = int(row.shipped)
        b = bucket(row.hardware_category, row.product_code)
        b["shipped_out"] += int(row.shipped)

    fulfilled_stmt = (
        select(
            PullRequestModel.project_id,
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
            func.sum(PullRequestItemModel.requested_quantity).label("fulfilled"),
        )
        .join(PullRequestModel, PullRequestItemModel.pull_request_id == PullRequestModel.id)
        .where(
            PullRequestModel.project_id.in_(project_ids),
            PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
        )
        .group_by(
            PullRequestModel.project_id,
            PullRequestItemModel.opening_number,
            PullRequestItemModel.hardware_category,
            PullRequestItemModel.product_code,
        )
    )
    for row in session.execute(fulfilled_stmt):
        key = (row.project_id, row.opening_number, row.hardware_category, row.product_code)
        staged = int(row.fulfilled) - shipped_map.get(key, 0)
        if staged > 0:
            b = bucket(row.hardware_category, row.product_code)
            b["staged_for_shipping"] += staged

    # Units that came back from site into project inventory. RETURN_TO_PROJECT only: a return routed
    # to the stock pool left the project, so it neither sits in on_hand nor needs netting.
    returned_stmt = (
        select(
            ShipmentReturnItemModel.hardware_category,
            ShipmentReturnItemModel.product_code,
            func.sum(ShipmentReturnItemModel.quantity).label("returned"),
        )
        .join(ShipmentReturnModel, ShipmentReturnItemModel.shipment_return_id == ShipmentReturnModel.id)
        .join(PackingSlipModel, ShipmentReturnModel.packing_slip_id == PackingSlipModel.id)
        .where(
            PackingSlipModel.project_id.in_(project_ids),
            ShipmentReturnItemModel.disposition == ReturnDisposition.RETURN_TO_PROJECT,
        )
        .group_by(ShipmentReturnItemModel.hardware_category, ShipmentReturnItemModel.product_code)
    )
    for row in session.execute(returned_stmt):
        bucket(row.hardware_category, row.product_code)["returned_to_project"] = int(row.returned)

    return [
        {"hardware_category": category, "product_code": code, **values}
        for (category, code), values in sorted(rows.items())
    ]
