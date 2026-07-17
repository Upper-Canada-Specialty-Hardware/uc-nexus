"""Warehouse dashboard stats + per-project purchasing progress rollups."""

import uuid
from datetime import datetime

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.models.enums import POStatus, PullRequestSource, PullRequestStatus
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.models.shipping import PackingSlipItem as PackingSlipItemModel


def get_warehouse_dashboard(session: Session) -> dict:
    """Compute cross-project warehouse dashboard statistics."""
    from datetime import timedelta

    now = datetime.utcnow()
    seven_days_ago = now - timedelta(days=7)

    # Total inventory value and item count — LEFT JOIN since stock-allocated rows have no PO line
    inv_stats = session.execute(
        select(
            func.coalesce(func.sum(InventoryLocationModel.quantity), 0),
            func.coalesce(
                func.sum(InventoryLocationModel.quantity * func.coalesce(POLineItemModel.unit_cost, 0)),
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

    # Back-ordered: PO line items where received < ordered on active POs
    back_ordered = (
        session.scalar(
            select(func.coalesce(func.sum(POLineItemModel.ordered_quantity - POLineItemModel.received_quantity), 0))
            .join(POModel, POLineItemModel.po_id == POModel.id)
            .where(
                POModel.status.in_([POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
                POModel.deleted_at.is_(None),
                POLineItemModel.ordered_quantity > POLineItemModel.received_quantity,
            )
        )
        or 0
    )

    return {
        "total_item_count": int(inv_stats[0]),
        "total_value": float(inv_stats[1]),
        "unlocated_count": int(unlocated_count),
        "pending_pull_shop": int(pending_shop),
        "pending_pull_shipping": int(pending_shipping),
        "received_last_7_days": int(received_recent),
        "back_ordered_count": int(back_ordered),
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
