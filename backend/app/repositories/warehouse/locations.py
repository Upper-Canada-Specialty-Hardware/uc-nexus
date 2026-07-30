"""Physical locations: normalization, location browse/utilization/duplicates, moves, merges."""

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


def _normalize_and_validate_location_fields(aisle: str, row: str, bay: str) -> tuple[str, str, str]:
    """Normalize each of aisle/row/bay then enforce 1-20 chars. Returns the canonical triple."""
    a = normalize_location_value(aisle) or ""
    b = normalize_location_value(row) or ""
    c = normalize_location_value(bay) or ""
    for field_name, value in [("aisle", a), ("row", b), ("bay", c)]:
        if not value or len(value) < 1 or len(value) > 20:
            raise ValidationError(f"{field_name} must be 1-20 characters", field=field_name)
    return (a, b, c)


def get_location_contents(
    session: Session,
    aisle: str,
    row_name: str | None = None,
    bay: str | None = None,
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
    if row_name is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.row == row_name)
    if bay is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.bay == bay)
    if warehouse_id is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
    inv_rows = session.execute(inv_stmt).all()

    # Opening items (project-bound, post-assembly)
    oi_stmt = (
        select(OpeningItemModel)
        .options(selectinload(OpeningItemModel.installed_hardware))
        .where(OpeningItemModel.aisle == aisle)
    )
    if row_name is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.row == row_name)
    if bay is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.bay == bay)
    if warehouse_id is not None:
        oi_stmt = oi_stmt.where(OpeningItemModel.warehouse_id == warehouse_id)
    opening_items = list(session.scalars(oi_stmt).unique().all())

    # Stock items (company-owned pool, not project-bound)
    si_stmt = select(StockItemModel).where(
        StockItemModel.aisle == aisle,
        StockItemModel.quantity + StockItemModel.deficient_quantity > 0,
    )
    if row_name is not None:
        si_stmt = si_stmt.where(StockItemModel.row == row_name)
    if bay is not None:
        si_stmt = si_stmt.where(StockItemModel.bay == bay)
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
    """Distinct (warehouse, aisle, row, bay) combos with item counts and total quantities across all three sources.

    A location string is one physical place only within a warehouse, so rows are grouped by warehouse too.
    """
    from sqlalchemy import func

    aggregated: dict[tuple, dict] = {}

    def _bump(wh, aisle: str | None, row_name: str | None, bay: str | None, count: int, qty: int) -> None:
        if aisle is None:
            return
        key = (wh, aisle, row_name, bay)
        slot = aggregated.setdefault(
            key,
            {"warehouse_id": wh, "aisle": aisle, "row": row_name, "bay": bay, "item_count": 0, "total_quantity": 0},
        )
        slot["item_count"] += int(count)
        slot["total_quantity"] += int(qty)

    inv_stmt = (
        select(
            InventoryLocationModel.warehouse_id,
            InventoryLocationModel.aisle,
            InventoryLocationModel.row,
            InventoryLocationModel.bay,
            func.count().label("item_count"),
            func.sum(InventoryLocationModel.quantity).label("total_quantity"),
        )
        .where(InventoryLocationModel.aisle.is_not(None), InventoryLocationModel.quantity > 0)
        .group_by(
            InventoryLocationModel.warehouse_id,
            InventoryLocationModel.aisle,
            InventoryLocationModel.row,
            InventoryLocationModel.bay,
        )
    )
    oi_stmt = (
        select(
            OpeningItemModel.warehouse_id,
            OpeningItemModel.aisle,
            OpeningItemModel.row,
            OpeningItemModel.bay,
            func.count().label("item_count"),
            func.sum(OpeningItemModel.quantity).label("total_quantity"),
        )
        .where(OpeningItemModel.aisle.is_not(None))
        .group_by(OpeningItemModel.warehouse_id, OpeningItemModel.aisle, OpeningItemModel.row, OpeningItemModel.bay)
    )
    si_stmt = (
        select(
            StockItemModel.warehouse_id,
            StockItemModel.aisle,
            StockItemModel.row,
            StockItemModel.bay,
            func.count().label("item_count"),
            func.sum(StockItemModel.quantity).label("total_quantity"),
        )
        .where(
            StockItemModel.aisle.is_not(None),
            StockItemModel.quantity + StockItemModel.deficient_quantity > 0,
        )
        .group_by(StockItemModel.warehouse_id, StockItemModel.aisle, StockItemModel.row, StockItemModel.bay)
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
        key=lambda entry: (str(entry["warehouse_id"]), entry["aisle"] or "", entry["row"] or "", entry["bay"] or ""),
    )


def get_location_audit_history(
    session: Session, aisle: str, row_name: str | None = None, bay: str | None = None, limit: int = 10
) -> list[InventoryAuditLog]:
    """Recent audit log entries whose detail.fromLocation or detail.toLocation matches the location."""
    # Build the matching predicate via JSONB containment. Postgres-only — matches the JSONB column.
    from_match: dict = {"aisle": aisle}
    to_match: dict = {"aisle": aisle}
    if row_name is not None:
        from_match["row"] = row_name
        to_match["row"] = row_name
    if bay is not None:
        from_match["bay"] = bay
        to_match["bay"] = bay

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
    """Return distinct aisle/row/bay values across inventory, opening, and stock tables for autocomplete."""
    aisles: set[str] = set()
    row_values: set[str] = set()
    bays: set[str] = set()

    for model in (InventoryLocationModel, OpeningItemModel, StockItemModel):
        records = session.execute(
            select(model.aisle, model.row, model.bay).where(model.aisle.is_not(None)).distinct()
        ).all()
        for a, b, c in records:
            if a:
                aisles.add(a)
            if b:
                row_values.add(b)
            if c:
                bays.add(c)

    return {
        "aisles": sorted(aisles),
        "rows": sorted(row_values),
        "bays": sorted(bays),
    }


def get_location_duplicates(session: Session) -> list[dict]:
    """Group location triples that collide on case-insensitive equality.

    Each group lists the distinct stored variants and the canonical (uppercase, trimmed) form.
    Only groups with 2+ variants are returned.
    """
    triples: set[tuple[str, str | None, str | None]] = set()
    for model in (InventoryLocationModel, OpeningItemModel, StockItemModel):
        records = session.execute(
            select(model.aisle, model.row, model.bay).where(model.aisle.is_not(None)).distinct()
        ).all()
        for a, b, c in records:
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
                "canonical_row": canonical[1],
                "canonical_bay": canonical[2],
                "variants": [{"aisle": v[0], "row": v[1], "bay": v[2]} for v in sorted(variants, key=lambda t: str(t))],
            }
        )
    return sorted(
        result,
        key=lambda g: (g["canonical_aisle"] or "", g["canonical_row"] or "", g["canonical_bay"] or ""),
    )


def merge_locations(
    session: Session,
    *,
    from_aisle: str,
    from_row: str,
    from_bay: str,
    to_aisle: str,
    to_row: str,
    to_bay: str,
    performed_by: str,
) -> dict:
    """Rewrite every row at (from_aisle, from_row, from_bay) to (to_aisle, to_row, to_bay).

    Touches inventory_locations, opening_items, and stock_items. Writes a MOVE audit per row
    so the merge is reconstructable. Returns counts per source table.
    """
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")

    to_aisle, to_row, to_bay = _normalize_and_validate_location_fields(to_aisle, to_row, to_bay)
    # from_* may already be in canonical form; either way only compare equality, no validation needed.

    counts = {"inventory_locations": 0, "opening_items": 0, "stock_items": 0}

    inv_rows = list(
        session.scalars(
            select(InventoryLocationModel).where(
                InventoryLocationModel.aisle == from_aisle,
                InventoryLocationModel.row == from_row,
                InventoryLocationModel.bay == from_bay,
            )
        ).all()
    )
    for il in inv_rows:
        il.aisle, il.row, il.bay = to_aisle, to_row, to_bay
        _log_audit_event(
            session,
            project_id=il.project_id,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=il.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "row": from_row, "bay": from_bay},
                "toLocation": {"aisle": to_aisle, "row": to_row, "bay": to_bay},
                "reason": "location_merge",
            },
        )
    counts["inventory_locations"] = len(inv_rows)

    oi_rows = list(
        session.scalars(
            select(OpeningItemModel).where(
                OpeningItemModel.aisle == from_aisle,
                OpeningItemModel.row == from_row,
                OpeningItemModel.bay == from_bay,
            )
        ).all()
    )
    for oi in oi_rows:
        oi.aisle, oi.row, oi.bay = to_aisle, to_row, to_bay
        _log_audit_event(
            session,
            project_id=oi.project_id,
            entity_type=AuditEntityType.OPENING_ITEM,
            entity_id=oi.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "row": from_row, "bay": from_bay},
                "toLocation": {"aisle": to_aisle, "row": to_row, "bay": to_bay},
                "reason": "location_merge",
            },
        )
    counts["opening_items"] = len(oi_rows)

    si_rows = list(
        session.scalars(
            select(StockItemModel).where(
                StockItemModel.aisle == from_aisle,
                StockItemModel.row == from_row,
                StockItemModel.bay == from_bay,
            )
        ).all()
    )
    for si in si_rows:
        si.aisle, si.row, si.bay = to_aisle, to_row, to_bay
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=si.id,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail={
                "fromLocation": {"aisle": from_aisle, "row": from_row, "bay": from_bay},
                "toLocation": {"aisle": to_aisle, "row": to_row, "bay": to_bay},
                "reason": "location_merge",
            },
        )
    counts["stock_items"] = len(si_rows)

    return counts


def move_inventory_location(
    session: Session, inv_id: uuid.UUID, new_aisle: str, new_row: str, new_bay: str, *, performed_by: str
) -> InventoryLocationModel:
    """Move an InventoryLocation to a new aisle/row/bay.

    `performed_by` is keyword-only and required (#427): the six put-away/unlocate/move helpers below
    all hardcoded "Admin/Manager", which is what the location history panel showed for every physical
    move of stock regardless of who made it."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    new_aisle, new_row, new_bay = _normalize_and_validate_location_fields(new_aisle, new_row, new_bay)

    old_aisle, old_row, old_bay = il.aisle, il.row, il.bay
    il.aisle = new_aisle
    il.row = new_row
    il.bay = new_bay

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.MOVE,
        performed_by=performed_by,
        detail={
            "fromLocation": {"aisle": old_aisle, "row": old_row, "bay": old_bay},
            "toLocation": {"aisle": new_aisle, "row": new_row, "bay": new_bay},
        },
    )

    return il


def mark_inventory_unlocated(session: Session, inv_id: uuid.UUID, *, performed_by: str) -> InventoryLocationModel:
    """Clear the aisle/row/bay on an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    old_aisle, old_row, old_bay = il.aisle, il.row, il.bay
    il.aisle = None
    il.row = None
    il.bay = None

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.UNLOCATE,
        performed_by=performed_by,
        detail={"fromLocation": {"aisle": old_aisle, "row": old_row, "bay": old_bay}},
    )

    return il


def assign_inventory_location(
    session: Session, inv_id: uuid.UUID, aisle: str, row: str, bay: str, *, performed_by: str
) -> InventoryLocationModel:
    """Assign aisle/row/bay to an InventoryLocation."""
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")

    aisle, row, bay = _normalize_and_validate_location_fields(aisle, row, bay)

    il.aisle = aisle
    il.row = row
    il.bay = bay

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"toLocation": {"aisle": aisle, "row": row, "bay": bay}},
    )

    return il


def move_opening_item_location(
    session: Session,
    oi_id: uuid.UUID,
    aisle: str,
    row: str,
    bay: str,
    warehouse_id: uuid.UUID | None = None,
    *,
    performed_by: str,
) -> OpeningItemModel:
    """Move an OpeningItem (whole kit) to a new aisle/row/bay, optionally a different warehouse."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    aisle, row, bay = _normalize_and_validate_location_fields(aisle, row, bay)

    old_aisle, old_row, old_bay, old_wh = oi.aisle, oi.row, oi.bay, oi.warehouse_id
    oi.aisle = aisle
    oi.row = row
    oi.bay = bay
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
        performed_by=performed_by,
        detail={
            "fromWarehouseId": str(old_wh),
            "fromLocation": {"aisle": old_aisle, "row": old_row, "bay": old_bay},
            "toWarehouseId": str(oi.warehouse_id),
            "toLocation": {"aisle": aisle, "row": row, "bay": bay},
        },
    )

    return oi


def mark_opening_item_unlocated(session: Session, oi_id: uuid.UUID, *, performed_by: str) -> OpeningItemModel:
    """Clear the aisle/row/bay on an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    old_aisle, old_row, old_bay = oi.aisle, oi.row, oi.bay
    oi.aisle = None
    oi.row = None
    oi.bay = None

    _log_audit_event(
        session,
        project_id=oi.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=oi.id,
        action=AuditAction.UNLOCATE,
        performed_by=performed_by,
        detail={"fromLocation": {"aisle": old_aisle, "row": old_row, "bay": old_bay}},
    )

    return oi


def assign_opening_item_location(
    session: Session, oi_id: uuid.UUID, aisle: str, row: str, bay: str, *, performed_by: str
) -> OpeningItemModel:
    """Assign aisle/row/bay to an OpeningItem."""
    oi = session.get(OpeningItemModel, oi_id)
    if oi is None:
        raise NotFoundError(f"Opening item {oi_id} not found")

    aisle, row, bay = _normalize_and_validate_location_fields(aisle, row, bay)

    oi.aisle = aisle
    oi.row = row
    oi.bay = bay

    _log_audit_event(
        session,
        project_id=oi.project_id,
        entity_type=AuditEntityType.OPENING_ITEM,
        entity_id=oi.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"toLocation": {"aisle": aisle, "row": row, "bay": bay}},
    )

    return oi
