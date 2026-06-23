"""Repository for warehouse inventory and opening item data access."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    NotificationType,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receiving import ReceiveLineItem as ReceiveLineItemModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.models.shipping import PackingSlipItem as PackingSlipItemModel
from app.models.shop_assembly import ShopAssemblyRequest as SARModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.vendor import Vendor as VendorModel
from app.services import notification_service
from app.services.locking import lock_rows


def normalize_location_value(value: str | None) -> str | None:
    """Canonicalize a location string: uppercase, trim, collapse internal whitespace.

    Returns None for None input or for strings that become empty after normalization.
    Shared by both project-inventory and stock-pool repositories so writes agree on canonical form.
    """
    if value is None:
        return None
    normalized = " ".join(value.upper().strip().split())
    return normalized or None


def _log_audit_event(
    session: Session,
    *,
    project_id: uuid.UUID | None,
    entity_type: AuditEntityType,
    entity_id: uuid.UUID,
    action: AuditAction,
    performed_by: str,
    detail: dict | None = None,
) -> None:
    """Insert a row into inventory_audit_log."""
    session.add(
        InventoryAuditLog(
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            detail=detail,
            performed_by=performed_by,
        )
    )


def get_audit_log(
    session: Session,
    entity_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[InventoryAuditLog]:
    """Query audit log entries, optionally filtered by entity, type, or project."""
    stmt = select(InventoryAuditLog).order_by(InventoryAuditLog.created_at.desc())
    if entity_id is not None:
        stmt = stmt.where(InventoryAuditLog.entity_id == entity_id)
    if entity_type is not None:
        stmt = stmt.where(InventoryAuditLog.entity_type == entity_type)
    if project_id is not None:
        stmt = stmt.where(InventoryAuditLog.project_id == project_id)
    stmt = stmt.limit(limit)
    return list(session.scalars(stmt).all())


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
                POModel.status.in_([POStatus.ORDERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
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


def get_expected_deliveries(session: Session, project_id: uuid.UUID | None = None) -> list:
    """Active POs with outstanding line items, ordered by expected_delivery_date."""
    stmt = (
        select(POModel)
        .options(selectinload(POModel.line_items), selectinload(POModel.vendor))
        .where(
            POModel.status.in_([POStatus.ORDERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
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
            POModel.status.in_([POStatus.ORDERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
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


PLACED_PO_STATUSES = (
    POStatus.ORDERED,
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
      (i.e. ORDERED, VENDOR_CONFIRMED, PARTIALLY_RECEIVED)
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
                        POModel.status.in_([POStatus.ORDERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED]),
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


def get_inventory_by_vendor(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """Group inventory by vendor name (via PO.vendor_id → Vendor), then product_code."""
    stmt = (
        select(InventoryLocationModel, POLineItemModel.unit_cost, VendorModel.name)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .outerjoin(VendorModel, POModel.vendor_id == VendorModel.id)
        # Hide rows fully emptied by destock/allocation (kept in DB for FK integrity).
        .where(InventoryLocationModel.quantity > 0)
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    stmt = stmt.order_by(VendorModel.name, InventoryLocationModel.product_code)
    rows = list(session.execute(stmt).all())

    vendor_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il, unit_cost, vendor_name in rows:
        vname = vendor_name or "No Vendor"
        # Stock-allocated rows (stock_item origin) have no PO unit_cost; coerce to 0 like the
        # category hierarchy does, otherwise the float() in the value sum below blows up.
        vendor_map[vname][il.product_code].append((il, unit_cost or 0))

    result = []
    for vendor in sorted(vendor_map.keys()):
        pc_map = vendor_map[vendor]
        pc_nodes = []
        vendor_total = 0
        vendor_value = 0.0
        for pc in sorted(pc_map.keys()):
            items_with_cost = pc_map[pc]
            pc_total = sum(il.quantity for il, _ in items_with_cost)
            pc_value = sum(float(uc) * il.quantity for il, uc in items_with_cost)
            vendor_total += pc_total
            vendor_value += pc_value
            pc_nodes.append(
                {
                    "product_code": pc,
                    "items": [il for il, _ in items_with_cost],
                    "total_quantity": pc_total,
                    "total_value": pc_value,
                }
            )
        result.append(
            {
                "vendor_name": vendor,
                "product_codes": pc_nodes,
                "total_quantity": vendor_total,
                "total_value": vendor_value,
            }
        )
    return result


def get_location_contents(session: Session, aisle: str, bay: str | None = None, bin_name: str | None = None) -> dict:
    """Get all inventory, opening, and stock items at a given location."""
    # Inventory locations (project-bound)
    inv_stmt = (
        select(InventoryLocationModel, POLineItemModel.unit_cost, POModel.po_number)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(InventoryLocationModel.aisle == aisle, InventoryLocationModel.quantity > 0)
    )
    if bay is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.bay == bay)
    if bin_name is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.bin == bin_name)
    inv_rows = session.execute(inv_stmt).all()

    # Opening items (project-bound, post-assembly)
    oi_stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.aisle == aisle)
    )
    if bay is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.bay == bay)
    if bin_name is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.bin == bin_name)
    opening_items = list(session.scalars(oi_stmt).unique().all())

    # Stock items (company-owned pool, not project-bound)
    si_stmt = select(StockItemModel).where(
        StockItemModel.aisle == aisle,
        StockItemModel.quantity + StockItemModel.deficient_quantity > 0,
    )
    if bay is not None:
        si_stmt = si_stmt.where(StockItemModel.bay == bay)
    if bin_name is not None:
        si_stmt = si_stmt.where(StockItemModel.bin == bin_name)
    stock_items = list(session.scalars(si_stmt).all())

    return {
        "inventory_items": [
            {
                "inventory_location": row[0],
                "unit_cost": float(row[1]) if row[1] is not None else None,
                "po_number": row[2],
            }
            for row in inv_rows
        ],
        "opening_items": opening_items,
        "stock_items": stock_items,
    }


def get_location_utilization(session: Session) -> list[dict]:
    """Distinct aisle/bay/bin combos with item counts and total quantities across all three sources."""
    aggregated: dict[tuple[str, str | None, str | None], dict] = {}

    def _bump(aisle: str | None, bay: str | None, bin_name: str | None, count: int, qty: int) -> None:
        if aisle is None:
            return
        key = (aisle, bay, bin_name)
        slot = aggregated.setdefault(
            key, {"aisle": aisle, "bay": bay, "bin": bin_name, "item_count": 0, "total_quantity": 0}
        )
        slot["item_count"] += int(count)
        slot["total_quantity"] += int(qty)

    inv_rows = session.execute(
        select(
            InventoryLocationModel.aisle,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
            func.count().label("item_count"),
            func.sum(InventoryLocationModel.quantity).label("total_quantity"),
        )
        .where(InventoryLocationModel.aisle.is_not(None), InventoryLocationModel.quantity > 0)
        .group_by(InventoryLocationModel.aisle, InventoryLocationModel.bay, InventoryLocationModel.bin)
    ).all()
    for r in inv_rows:
        _bump(r[0], r[1], r[2], r[3], r[4])

    oi_rows = session.execute(
        select(
            OpeningItemModel.aisle,
            OpeningItemModel.bay,
            OpeningItemModel.bin,
            func.count().label("item_count"),
            func.sum(OpeningItemModel.quantity).label("total_quantity"),
        )
        .where(OpeningItemModel.aisle.is_not(None))
        .group_by(OpeningItemModel.aisle, OpeningItemModel.bay, OpeningItemModel.bin)
    ).all()
    for r in oi_rows:
        _bump(r[0], r[1], r[2], r[3], r[4])

    si_rows = session.execute(
        select(
            StockItemModel.aisle,
            StockItemModel.bay,
            StockItemModel.bin,
            func.count().label("item_count"),
            func.sum(StockItemModel.quantity).label("total_quantity"),
        )
        .where(
            StockItemModel.aisle.is_not(None),
            StockItemModel.quantity + StockItemModel.deficient_quantity > 0,
        )
        .group_by(StockItemModel.aisle, StockItemModel.bay, StockItemModel.bin)
    ).all()
    for r in si_rows:
        _bump(r[0], r[1], r[2], r[3], r[4])

    return sorted(aggregated.values(), key=lambda row: (row["aisle"] or "", row["bay"] or "", row["bin"] or ""))


def get_location_audit_history(
    session: Session, aisle: str, bay: str | None = None, bin_name: str | None = None, limit: int = 10
) -> list[InventoryAuditLog]:
    """Recent audit log entries whose detail.fromLocation or detail.toLocation matches the bin."""
    # Build the matching predicate via JSONB containment. Postgres-only — matches the JSONB column.
    from_match: dict = {"aisle": aisle}
    to_match: dict = {"aisle": aisle}
    if bay is not None:
        from_match["bay"] = bay
        to_match["bay"] = bay
    if bin_name is not None:
        from_match["bin"] = bin_name
        to_match["bin"] = bin_name

    stmt = (
        select(InventoryAuditLog)
        .where(
            InventoryAuditLog.entity_type.in_(
                [AuditEntityType.INVENTORY_LOCATION, AuditEntityType.OPENING_ITEM, AuditEntityType.STOCK_ITEM]
            ),
            or_(
                InventoryAuditLog.detail["fromLocation"].contains(from_match),
                InventoryAuditLog.detail["toLocation"].contains(to_match),
                InventoryAuditLog.detail["targetLocation"].contains(to_match),
                InventoryAuditLog.detail["location"].contains(to_match),
            ),
        )
        .order_by(InventoryAuditLog.created_at.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt).all())


def get_distinct_location_values(session: Session) -> dict[str, list[str]]:
    """Return distinct aisle/bay/bin values across inventory, opening, and stock tables for autocomplete."""
    aisles: set[str] = set()
    bays: set[str] = set()
    bins: set[str] = set()

    for model in (InventoryLocationModel, OpeningItemModel, StockItemModel):
        rows = session.execute(
            select(model.aisle, model.bay, model.bin).where(model.aisle.is_not(None)).distinct()
        ).all()
        for a, b, c in rows:
            if a:
                aisles.add(a)
            if b:
                bays.add(b)
            if c:
                bins.add(c)

    return {
        "aisles": sorted(aisles),
        "bays": sorted(bays),
        "bins": sorted(bins),
    }


def get_location_duplicates(session: Session) -> list[dict]:
    """Group location triples that collide on case-insensitive equality.

    Each group lists the distinct stored variants and the canonical (uppercase, trimmed) form.
    Only groups with 2+ variants are returned.
    """
    triples: set[tuple[str, str | None, str | None]] = set()
    for model in (InventoryLocationModel, OpeningItemModel, StockItemModel):
        rows = session.execute(
            select(model.aisle, model.bay, model.bin).where(model.aisle.is_not(None)).distinct()
        ).all()
        for a, b, c in rows:
            triples.add((a, b, c))

    groups: dict[tuple[str | None, str | None, str | None], list[tuple[str, str | None, str | None]]] = defaultdict(
        list
    )
    for triple in triples:
        canonical = (
            normalize_location_value(triple[0]),
            normalize_location_value(triple[1]),
            normalize_location_value(triple[2]),
        )
        groups[canonical].append(triple)

    result = []
    for canonical, variants in groups.items():
        if len(variants) < 2:
            continue
        result.append(
            {
                "canonical_aisle": canonical[0],
                "canonical_bay": canonical[1],
                "canonical_bin": canonical[2],
                "variants": [{"aisle": v[0], "bay": v[1], "bin": v[2]} for v in sorted(variants, key=lambda t: str(t))],
            }
        )
    return sorted(
        result,
        key=lambda g: (g["canonical_aisle"] or "", g["canonical_bay"] or "", g["canonical_bin"] or ""),
    )


def merge_locations(
    session: Session,
    *,
    from_aisle: str,
    from_bay: str,
    from_bin: str,
    to_aisle: str,
    to_bay: str,
    to_bin: str,
    performed_by: str,
) -> dict:
    """Rewrite every row at (from_aisle, from_bay, from_bin) to (to_aisle, to_bay, to_bin).

    Touches inventory_locations, opening_items, and stock_items. Writes a MOVE audit per row
    so the merge is reconstructable. Returns counts per source table.
    """
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")

    to_aisle, to_bay, to_bin = _normalize_and_validate_location_fields(to_aisle, to_bay, to_bin)
    # from_* may already be in canonical form; either way only compare equality, no validation needed.

    counts = {"inventory_locations": 0, "opening_items": 0, "stock_items": 0}

    inv_rows = list(
        session.scalars(
            select(InventoryLocationModel).where(
                InventoryLocationModel.aisle == from_aisle,
                InventoryLocationModel.bay == from_bay,
                InventoryLocationModel.bin == from_bin,
            )
        ).all()
    )
    for il in inv_rows:
        il.aisle, il.bay, il.bin = to_aisle, to_bay, to_bin
        _log_audit_event(
            session,
            project_id=il.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=il.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "bay": from_bay, "bin": from_bin},
                "toLocation": {"aisle": to_aisle, "bay": to_bay, "bin": to_bin},
                "reason": "location_merge",
            },
        )
    counts["inventory_locations"] = len(inv_rows)

    oi_rows = list(
        session.scalars(
            select(OpeningItemModel).where(
                OpeningItemModel.aisle == from_aisle,
                OpeningItemModel.bay == from_bay,
                OpeningItemModel.bin == from_bin,
            )
        ).all()
    )
    for oi in oi_rows:
        oi.aisle, oi.bay, oi.bin = to_aisle, to_bay, to_bin
        _log_audit_event(
            session,
            project_id=oi.project_id,
            entity_type=AuditEntityType.OPENING_ITEM,
            entity_id=oi.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "bay": from_bay, "bin": from_bin},
                "toLocation": {"aisle": to_aisle, "bay": to_bay, "bin": to_bin},
                "reason": "location_merge",
            },
        )
    counts["opening_items"] = len(oi_rows)

    si_rows = list(
        session.scalars(
            select(StockItemModel).where(
                StockItemModel.aisle == from_aisle,
                StockItemModel.bay == from_bay,
                StockItemModel.bin == from_bin,
            )
        ).all()
    )
    for si in si_rows:
        si.aisle, si.bay, si.bin = to_aisle, to_bay, to_bin
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "bay": from_bay, "bin": from_bin},
                "toLocation": {"aisle": to_aisle, "bay": to_bay, "bin": to_bin},
                "reason": "location_merge",
            },
        )
    counts["stock_items"] = len(si_rows)

    return counts


def get_inventory_hierarchy(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """
    Query all InventoryLocation rows joined with POLineItem for unit_cost,
    optionally filtered by project_id.
    Group by hardware_category, then product_code.
    At each level, sum quantities and compute total_value (unit_cost * quantity).
    Sort categories and product codes alphabetically.

    Return structure: list of dicts, each with:
    {
        "hardware_category": str,
        "product_codes": [
            {
                "product_code": str,
                "items": [InventoryLocationModel, ...],
                "total_quantity": int,
                "total_value": float
            },
            ...
        ],
        "total_quantity": int,
        "total_value": float
    }
    """
    stmt = select(InventoryLocationModel, POLineItemModel.unit_cost).outerjoin(
        POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id
    )
    # Hide rows fully emptied by destock/allocation (quantity = 0). They are kept in the DB
    # for FK integrity (origin of stock allocations) but should not clutter the inventory view.
    stmt = stmt.where(InventoryLocationModel.quantity > 0)
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    stmt = stmt.order_by(
        InventoryLocationModel.hardware_category,
        InventoryLocationModel.product_code,
    )
    rows = list(session.execute(stmt).all())

    # Group by hardware_category -> product_code, storing (il, unit_cost) pairs
    cat_map: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for il, unit_cost in rows:
        cat_map[il.hardware_category][il.product_code].append((il, unit_cost or 0))

    result = []
    for category in sorted(cat_map.keys()):
        product_codes_map = cat_map[category]
        product_code_nodes = []
        category_total = 0
        category_total_value = 0.0

        for pc in sorted(product_codes_map.keys()):
            items_with_cost = product_codes_map[pc]
            pc_total = sum(il.quantity for il, _ in items_with_cost)
            pc_total_value = sum(float(uc) * il.quantity for il, uc in items_with_cost)
            category_total += pc_total
            category_total_value += pc_total_value
            product_code_nodes.append(
                {
                    "product_code": pc,
                    "items": [il for il, _ in items_with_cost],
                    "total_quantity": pc_total,
                    "total_value": pc_total_value,
                }
            )

        result.append(
            {
                "hardware_category": category,
                "product_codes": product_code_nodes,
                "total_quantity": category_total,
                "total_value": category_total_value,
            }
        )

    return result


def get_inventory_items(
    session: Session,
    project_id: uuid.UUID | None,
    category: str,
    product_code: str,
) -> list[dict]:
    """
    Query InventoryLocation rows matching (optional project_id, category, product_code).
    JOIN to POLineItem (via po_line_item_id) then PurchaseOrder (via po_id) to get po_number and classification.

    Return list of dicts with keys: inventory_location, po_number, classification
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number, POLineItemModel.unit_cost)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.hardware_category == category,
            InventoryLocationModel.product_code == product_code,
            # Hide rows fully emptied by destock/allocation (kept in DB for FK integrity).
            InventoryLocationModel.quantity > 0,
        )
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    rows = session.execute(stmt).all()

    return [
        {
            "inventory_location": row[0],
            "classification": row[1],
            "po_number": row[2],
            "unit_cost": float(row[3]) if row[3] is not None else 0.0,
        }
        for row in rows
    ]


def get_opening_items(session: Session, project_id: uuid.UUID | None = None) -> list[OpeningItemModel]:
    """
    Query all OpeningItem rows, optionally filtered by project_id.
    Eagerly load installed_hardware relationship (OpeningItemHardware).
    Sort by opening_number ASC.
    """
    stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .order_by(OpeningItemModel.opening_number.asc())
    )
    if project_id is not None:
        stmt = stmt.where(OpeningItemModel.project_id == project_id)
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


def _normalize_and_validate_location_fields(aisle: str, bay: str, bin: str) -> tuple[str, str, str]:
    """Normalize each of aisle/bay/bin then enforce 1-20 chars. Returns the canonical triple."""
    a = normalize_location_value(aisle) or ""
    b = normalize_location_value(bay) or ""
    c = normalize_location_value(bin) or ""
    for field_name, value in [("aisle", a), ("bay", b), ("bin", c)]:
        if not value or len(value) < 1 or len(value) > 20:
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)
    return (a, b, c)


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

    old_quantity = il.quantity
    il.quantity = new_quantity

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.ADJUSTMENT,
        performed_by="Admin/Manager",
        detail={
            "oldQuantity": old_quantity,
            "newQuantity": new_quantity,
            "adjustment": adjustment,
            "reason": reason,
        },
    )

    return il


def override_inventory_quantity(
    session: Session,
    *,
    inv_id: uuid.UUID,
    new_quantity: int,
    reason: str,
    destinations: list[dict],
    performed_by: str,
) -> InventoryLocationModel:
    """Set an InventoryLocation row to an absolute new_quantity. Reason always required, audit-logged.

    Decrease: the row shrinks to new_quantity (lost units written off with the reason); it cannot drop
    below the row's own deficient_quantity.

    Increase: the added (new_quantity - current) units must be placed via `destinations`, whose
    quantities sum to the delta. A destination at the row's own aisle/bay/bin bumps this row; any other
    destination becomes a new InventoryLocation that inherits this row's origin, so the has-origin CHECK
    holds and valuations keep the same unit_cost.
    """
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")
    if not reason or len(reason) > 500:
        raise ValidationError("reason_text must be 1-500 characters", field="reason_text")
    if new_quantity < 0:
        raise ValidationError("new_quantity must be >= 0", field="new_quantity")

    old_quantity = il.quantity
    delta = new_quantity - old_quantity
    if delta == 0:
        raise ValidationError("new_quantity must differ from the current quantity", field="new_quantity")

    created: list[InventoryLocationModel] = []
    audit_destinations: list[dict] = []

    if delta < 0:
        if new_quantity < il.deficient_quantity:
            raise ValidationError(
                "Cannot set quantity below this row's deficient quantity",
                field="new_quantity",
            )
        il.quantity = new_quantity
    else:
        if not destinations:
            raise ValidationError(
                "destination location(s) are required when increasing quantity",
                field="destinations",
            )
        normalized: list[dict] = []
        for dest in destinations:
            qty = dest["quantity"]
            if qty < 1:
                raise ValidationError("destination quantity must be >= 1", field="destinations")
            a, b, c = _normalize_and_validate_location_fields(dest["aisle"], dest["bay"], dest["bin"])
            normalized.append({"aisle": a, "bay": b, "bin": c, "quantity": qty})
        if sum(d["quantity"] for d in normalized) != delta:
            raise ValidationError(
                "destination quantities must sum to the added quantity",
                field="destinations",
            )

        now = datetime.utcnow()
        for dest in normalized:
            audit_destinations.append(dest)
            if (dest["aisle"], dest["bay"], dest["bin"]) == (il.aisle, il.bay, il.bin):
                il.quantity += dest["quantity"]
            else:
                new_il = InventoryLocationModel(
                    project_id=il.project_id,
                    po_line_item_id=il.po_line_item_id,
                    receive_line_item_id=il.receive_line_item_id,
                    stock_item_id=il.stock_item_id,
                    warehouse_id=il.warehouse_id,
                    hardware_category=il.hardware_category,
                    product_code=il.product_code,
                    quantity=dest["quantity"],
                    deficient_quantity=0,
                    aisle=dest["aisle"],
                    bay=dest["bay"],
                    bin=dest["bin"],
                    received_at=now,
                )
                session.add(new_il)
                created.append(new_il)

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail={
            "oldQuantity": old_quantity,
            "newQuantity": new_quantity,
            "delta": delta,
            "reason": reason,
            "override": True,
            "destinations": audit_destinations,
        },
    )

    session.flush()
    for new_il in created:
        _log_audit_event(
            session,
            project_id=new_il.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=new_il.id,
            action=AuditAction.ADJUSTMENT,
            performed_by=performed_by,
            detail={
                "createdByOverrideOf": str(il.id),
                "quantity": new_il.quantity,
                "location": {"aisle": new_il.aisle, "bay": new_il.bay, "bin": new_il.bin},
                "reason": reason,
            },
        )

    return il


def move_inventory_location(
    session: Session, inv_id: uuid.UUID, new_aisle: str, new_bay: str, new_bin: str
) -> InventoryLocationModel:
    """Move an InventoryLocation to a new aisle/bay/bin."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    new_aisle, new_bay, new_bin = _normalize_and_validate_location_fields(new_aisle, new_bay, new_bin)

    old_aisle, old_bay, old_bin = il.aisle, il.bay, il.bin
    il.aisle = new_aisle
    il.bay = new_bay
    il.bin = new_bin

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.MOVE,
        performed_by="Admin/Manager",
        detail={
            "fromLocation": {"aisle": old_aisle, "bay": old_bay, "bin": old_bin},
            "toLocation": {"aisle": new_aisle, "bay": new_bay, "bin": new_bin},
        },
    )

    return il


def mark_inventory_unlocated(session: Session, inv_id: uuid.UUID) -> InventoryLocationModel:
    """Clear the aisle/bay/bin on an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    old_aisle, old_bay, old_bin = il.aisle, il.bay, il.bin
    il.aisle = None
    il.bay = None
    il.bin = None

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.UNLOCATE,
        performed_by="Admin/Manager",
        detail={"fromLocation": {"aisle": old_aisle, "bay": old_bay, "bin": old_bin}},
    )

    return il


def assign_inventory_location(
    session: Session, inv_id: uuid.UUID, aisle: str, bay: str, bin: str
) -> InventoryLocationModel:
    """Assign aisle/bay/bin to an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    aisle, bay, bin = _normalize_and_validate_location_fields(aisle, bay, bin)

    il.aisle = aisle
    il.bay = bay
    il.bin = bin

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.PUT_AWAY,
        performed_by="Admin/Manager",
        detail={"toLocation": {"aisle": aisle, "bay": bay, "bin": bin}},
    )

    return il


def move_opening_item_location(
    session: Session,
    oi_id: uuid.UUID,
    aisle: str,
    bay: str,
    bin: str,
    warehouse_id: uuid.UUID | None = None,
) -> OpeningItemModel:
    """Move an OpeningItem (whole kit) to a new aisle/bay/bin, optionally a different warehouse."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    aisle, bay, bin = _normalize_and_validate_location_fields(aisle, bay, bin)

    old_aisle, old_bay, old_bin, old_wh = oi.aisle, oi.bay, oi.bin, oi.warehouse_id
    oi.aisle = aisle
    oi.bay = bay
    oi.bin = bin
    if warehouse_id is not None:
        from app.models.warehouse import Warehouse

        if session.get(Warehouse, warehouse_id) is None:
            raise NotFoundError(f"Warehouse {warehouse_id} not found")
        oi.warehouse_id = warehouse_id

    _log_audit_event(
        session,
        project_id=oi.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=oi.id,
        action=AuditAction.MOVE,
        performed_by="Admin/Manager",
        detail={
            "fromWarehouseId": str(old_wh),
            "fromLocation": {"aisle": old_aisle, "bay": old_bay, "bin": old_bin},
            "toWarehouseId": str(oi.warehouse_id),
            "toLocation": {"aisle": aisle, "bay": bay, "bin": bin},
        },
    )

    return oi


def mark_opening_item_unlocated(session: Session, oi_id: uuid.UUID) -> OpeningItemModel:
    """Clear the aisle/bay/bin on an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    old_aisle, old_bay, old_bin = oi.aisle, oi.bay, oi.bin
    oi.aisle = None
    oi.bay = None
    oi.bin = None

    _log_audit_event(
        session,
        project_id=oi.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=oi.id,
        action=AuditAction.UNLOCATE,
        performed_by="Admin/Manager",
        detail={"fromLocation": {"aisle": old_aisle, "bay": old_bay, "bin": old_bin}},
    )

    return oi


def assign_opening_item_location(
    session: Session, oi_id: uuid.UUID, aisle: str, bay: str, bin: str
) -> OpeningItemModel:
    """Assign aisle/bay/bin to an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    aisle, bay, bin = _normalize_and_validate_location_fields(aisle, bay, bin)

    oi.aisle = aisle
    oi.bay = bay
    oi.bin = bin

    _log_audit_event(
        session,
        project_id=oi.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=oi.id,
        action=AuditAction.PUT_AWAY,
        performed_by="Admin/Manager",
        detail={"toLocation": {"aisle": aisle, "bay": bay, "bin": bin}},
    )

    return oi


# ---------------------------------------------------------------------------
# Receiving helpers and functions
# ---------------------------------------------------------------------------


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
    if po.status not in (POStatus.ORDERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED):
        raise InvalidStateTransitionError(
            f"PO status must be Ordered, Vendor_Confirmed, or Partially_Received to receive, got {po.status.value}"
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
            from app.repositories import stock_repository

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


# ---------------------------------------------------------------------------
# Pull Request functions
# ---------------------------------------------------------------------------


def get_pull_requests(
    session: Session,
    project_id: uuid.UUID | None = None,
    source=None,
    status=None,
) -> list[PullRequestModel]:
    """
    Query PullRequest WHERE deleted_at IS NULL, optionally filtered by project_id.
    Optional source filter, optional status filter.
    Order by created_at ASC (FIFO — oldest first).
    Eagerly load items (PullRequestItem).
    """
    stmt = (
        select(PullRequestModel)
        .options(selectinload(PullRequestModel.items))
        .where(PullRequestModel.deleted_at.is_(None))
    )
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
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

    # 4. Check sufficiency — only non-deficient (available) units can satisfy a pull
    insufficient = False
    if needed_combos:
        # Group locked inventory by (cat, code)
        inv_by_combo: dict[tuple[str, str], list] = defaultdict(list)
        for il in locked_inventory:
            key = (il.hardware_category, il.product_code)
            inv_by_combo[key].append(il)

        for (cat, code), requested in needed_combos.items():
            available = sum(il.quantity - (il.deficient_quantity or 0) for il in inv_by_combo.get((cat, code), []))
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
                # Deficient units must stay on the row — only available units can be pulled
                row_available = row.quantity - (row.deficient_quantity or 0)
                if row_available <= 0:
                    continue
                deduct = min(remaining, row_available)
                old_qty = row.quantity
                row.quantity -= deduct
                remaining -= deduct
                _log_audit_event(
                    session,
                    project_id=pr.project_id,
                    entity_type=AuditEntityType.INVENTORY_LOCATION,
                    entity_id=row.id,
                    action=AuditAction.PULL_DEDUCTION,
                    performed_by=approved_by,
                    detail={
                        "oldQuantity": old_qty,
                        "newQuantity": row.quantity,
                        "deducted": deduct,
                        "pullRequestNumber": pr.request_number,
                        "hardwareCategory": cat,
                        "productCode": code,
                    },
                )

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


# ---------------------------------------------------------------------------
# Unlocated Inventory & Recent Receives
# ---------------------------------------------------------------------------


def get_unlocated_inventory(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    """
    Query InventoryLocation rows where aisle, bay, and bin are all NULL and quantity > 0.
    Joins to POLineItem for unit_cost/classification and PurchaseOrder for po_number.
    """
    stmt = (
        select(InventoryLocationModel, POLineItemModel.classification, POModel.po_number, POLineItemModel.unit_cost)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            InventoryLocationModel.aisle.is_(None),
            InventoryLocationModel.bay.is_(None),
            InventoryLocationModel.bin.is_(None),
            InventoryLocationModel.quantity > 0,
        )
    )
    if project_id is not None:
        stmt = stmt.where(InventoryLocationModel.project_id == project_id)
    stmt = stmt.order_by(
        InventoryLocationModel.hardware_category,
        InventoryLocationModel.product_code,
        InventoryLocationModel.received_at.desc(),
    )
    rows = session.execute(stmt).all()

    return [
        {
            "inventory_location": row[0],
            "classification": row[1],
            "po_number": row[2],
            "unit_cost": float(row[3]) if row[3] is not None else 0.0,
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
