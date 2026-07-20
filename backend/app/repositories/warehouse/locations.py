"""Physical locations: normalization, bin browse/utilization/duplicates, moves, merges."""

import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.stock_item import StockItem as StockItemModel

from .audit import _log_audit_event


def normalize_location_value(value: str | None) -> str | None:
    """Canonicalize a location string: uppercase, trim, collapse internal whitespace.

    Returns None for None input or for strings that become empty after normalization.
    Shared by both project-inventory and stock-pool repositories so writes agree on canonical form.
    """
    if value is None:
        return None
    normalized = " ".join(value.upper().strip().split())
    return normalized or None


def _normalize_and_validate_location_fields(aisle: str, bay: str, bin: str) -> tuple[str, str, str]:
    """Normalize each of aisle/bay/bin then enforce 1-20 chars. Returns the canonical triple."""
    a = normalize_location_value(aisle) or ""
    b = normalize_location_value(bay) or ""
    c = normalize_location_value(bin) or ""
    for field_name, value in [("aisle", a), ("bay", b), ("bin", c)]:
        if not value or len(value) < 1 or len(value) > 20:
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)
    return (a, b, c)


def get_location_contents(
    session: Session,
    aisle: str,
    bay: str | None = None,
    bin_name: str | None = None,
    warehouse_id: uuid.UUID | None = None,
) -> dict:
    """Get all inventory, opening, and stock items at a given location, optionally scoped to one warehouse."""
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
    if warehouse_id is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
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
    if warehouse_id is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.warehouse_id == warehouse_id)
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
    if warehouse_id is not None:
        si_stmt = si_stmt.where(StockItemModel.warehouse_id == warehouse_id)
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


def get_location_utilization(session: Session, warehouse_id: uuid.UUID | None = None) -> list[dict]:
    """Distinct (warehouse, aisle, bay, bin) combos with item counts and total quantities across all three sources.

    A bin string is one physical place only within a warehouse, so rows are grouped by warehouse too.
    """
    from sqlalchemy import func

    aggregated: dict[tuple, dict] = {}

    def _bump(wh, aisle: str | None, bay: str | None, bin_name: str | None, count: int, qty: int) -> None:
        if aisle is None:
            return
        key = (wh, aisle, bay, bin_name)
        slot = aggregated.setdefault(
            key,
            {"warehouse_id": wh, "aisle": aisle, "bay": bay, "bin": bin_name, "item_count": 0, "total_quantity": 0},
        )
        slot["item_count"] += int(count)
        slot["total_quantity"] += int(qty)

    inv_stmt = (
        select(
            InventoryLocationModel.warehouse_id,
            InventoryLocationModel.aisle,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
            func.count().label("item_count"),
            func.sum(InventoryLocationModel.quantity).label("total_quantity"),
        )
        .where(InventoryLocationModel.aisle.is_not(None), InventoryLocationModel.quantity > 0)
        .group_by(
            InventoryLocationModel.warehouse_id,
            InventoryLocationModel.aisle,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
        )
    )
    oi_stmt = (
        select(
            OpeningItemModel.warehouse_id,
            OpeningItemModel.aisle,
            OpeningItemModel.bay,
            OpeningItemModel.bin,
            func.count().label("item_count"),
            func.sum(OpeningItemModel.quantity).label("total_quantity"),
        )
        .where(OpeningItemModel.aisle.is_not(None))
        .group_by(OpeningItemModel.warehouse_id, OpeningItemModel.aisle, OpeningItemModel.bay, OpeningItemModel.bin)
    )
    si_stmt = (
        select(
            StockItemModel.warehouse_id,
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
        .group_by(StockItemModel.warehouse_id, StockItemModel.aisle, StockItemModel.bay, StockItemModel.bin)
    )
    if warehouse_id is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
        oi_stmt = oi_stmt.where(OpeningItemModel.warehouse_id == warehouse_id)
        si_stmt = si_stmt.where(StockItemModel.warehouse_id == warehouse_id)

    for stmt in (inv_stmt, oi_stmt, si_stmt):
        for r in session.execute(stmt).all():
            _bump(r[0], r[1], r[2], r[3], r[4], r[5])

    return sorted(
        aggregated.values(),
        key=lambda row: (str(row["warehouse_id"]), row["aisle"] or "", row["bay"] or "", row["bin"] or ""),
    )


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
