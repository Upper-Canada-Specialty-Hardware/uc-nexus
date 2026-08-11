"""Cross-domain dashboard aggregations for Home, Shop Assembly, and Admin landings.

All counts use scalar `func.count()` / `func.sum()` queries with no relationship
loads, per the project's N+1 avoidance rules.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import (
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShipmentStatus,
    ShippingOutRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipment_container import ShipmentContainer
from app.models.shipping import PackingSlip
from app.models.shipping_out_request import ShippingOutRequest

OPEN_PO_STATUSES = (
    POStatus.GP_REGISTERED,
    POStatus.VENDOR_CONFIRMED,
    POStatus.PARTIALLY_RECEIVED,
)


def get_home_dashboard_stats(session: Session) -> dict:
    """Cross-app KPIs for the Home dashboard."""
    open_pos = (
        session.scalar(
            select(func.count())
            .select_from(PurchaseOrder)
            .where(
                PurchaseOrder.deleted_at.is_(None),
                PurchaseOrder.status.in_(OPEN_PO_STATUSES),
            )
        )
        or 0
    )

    pending_pulls = (
        session.scalar(
            select(func.count())
            .select_from(PullRequest)
            .where(
                PullRequest.deleted_at.is_(None),
                PullRequest.status == PullRequestStatus.PENDING,
            )
        )
        or 0
    )

    items_pending = (
        session.scalar(
            select(func.coalesce(func.sum(POLineItem.ordered_quantity - POLineItem.received_quantity), 0))
            .select_from(POLineItem)
            .join(PurchaseOrder, POLineItem.po_id == PurchaseOrder.id)
            .where(
                PurchaseOrder.deleted_at.is_(None),
                PurchaseOrder.status.in_(OPEN_PO_STATUSES),
                POLineItem.ordered_quantity > POLineItem.received_quantity,
            )
        )
        or 0
    )

    project_count = session.scalar(select(func.count()).select_from(Project)) or 0

    return {
        "open_po_count": int(open_pos),
        "pending_pull_request_count": int(pending_pulls),
        "items_pending_receiving": int(items_pending),
        "project_count": int(project_count),
    }


def get_shop_assembly_stats(session: Session) -> dict:
    """KPIs for the Shop Assembly landing."""
    active_shop_pulls = (
        session.scalar(
            select(func.count())
            .select_from(PullRequest)
            .where(
                PullRequest.deleted_at.is_(None),
                PullRequest.source == PullRequestSource.SHOP_ASSEMBLY,
                PullRequest.status.in_((PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS)),
            )
        )
        or 0
    )

    return {
        "active_pull_request_count": int(active_shop_pulls),
    }


def get_shipping_stats(session: Session) -> dict:
    """Pipeline gauges for the Shipping landing (#589). Every figure is a scalar count with no
    relationship load, per the project's N+1 rules."""
    pending_requests = (
        session.scalar(
            select(func.count())
            .select_from(ShippingOutRequest)
            .where(ShippingOutRequest.status == ShippingOutRequestStatus.PENDING)
        )
        or 0
    )

    # Open containers: still being built, so no slip stamped on them yet (see ShipmentContainer).
    staging_containers = (
        session.scalar(
            select(func.count()).select_from(ShipmentContainer).where(ShipmentContainer.packing_slip_id.is_(None))
        )
        or 0
    )

    scheduled_shipments = (
        session.scalar(
            select(func.count()).select_from(PackingSlip).where(PackingSlip.status == ShipmentStatus.SCHEDULED)
        )
        or 0
    )

    in_transit_shipments = (
        session.scalar(
            select(func.count()).select_from(PackingSlip).where(PackingSlip.status == ShipmentStatus.PICKED_UP)
        )
        or 0
    )

    return {
        "pending_request_count": int(pending_requests),
        "staging_container_count": int(staging_containers),
        "scheduled_shipment_count": int(scheduled_shipments),
        "in_transit_shipment_count": int(in_transit_shipments),
    }


def get_admin_stats(session: Session, user_count: int) -> dict:
    """KPIs for the Admin landing. `user_count` is injected since users live in Clerk."""
    # Distinct (category, code) pairs via subquery — portable across dialects.
    distinct_pairs_subq = (
        select(HardwareItem.hardware_category, HardwareItem.product_code)
        .group_by(HardwareItem.hardware_category, HardwareItem.product_code)
        .subquery()
    )
    hardware_item_count = session.scalar(select(func.count()).select_from(distinct_pairs_subq)) or 0

    opening_count = session.scalar(select(func.count()).select_from(Opening)) or 0

    return {
        "user_count": int(user_count),
        "hardware_item_count": int(hardware_item_count),
        "opening_count": int(opening_count),
    }
