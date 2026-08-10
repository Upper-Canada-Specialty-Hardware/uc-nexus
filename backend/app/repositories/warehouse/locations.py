"""Physical locations: normalization, location browse/utilization/duplicates, moves, merges."""

import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.models.inventory import InventoryLocation as InventoryLocationModel
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
    """Get all inventory and stock items at a given location, optionally scoped to one warehouse."""
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
        "stock_items": stock_items,
    }


def get_location_utilization(session: Session, warehouse_id: uuid.UUID | None = None) -> list[dict]:
    """Distinct (warehouse, aisle, row, bay) combos with item counts and total quantities from both sources.

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
        si_stmt = si_stmt.where(StockItemModel.warehouse_id == warehouse_id)

    for stmt in (inv_stmt, si_stmt):
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

    for model in (InventoryLocationModel, StockItemModel):
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
    for model in (InventoryLocationModel, StockItemModel):
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

    Touches inventory_locations and stock_items. Writes a MOVE audit per row
    so the merge is reconstructable. Returns counts per source table.
    """
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")

    to_aisle, to_row, to_bay = _normalize_and_validate_location_fields(to_aisle, to_row, to_bay)
    # from_* may already be in canonical form; either way only compare equality, no validation needed.

    counts = {"inventory_locations": 0, "stock_items": 0}

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


def split_inventory_location(
    session: Session, inv_id: uuid.UUID, quantity: int, *, performed_by: str
) -> tuple[InventoryLocationModel, InventoryLocationModel]:
    """Break `quantity` units off an inventory row into a second row (#501).

    Put-away moved after approval, so a receive books one row per PO line and the warehouse decides
    where it goes afterwards. Ten hinges rarely go in one bin: six in A-1-1 and four in B-2-2 is the
    normal case, and it needs two rows because a row carries exactly one aisle/row/bay.

    The new row copies the origin FKs and `received_at` verbatim. Those are what make the units
    traceable back to the receipt that booked them and what FIFO orders picks by - a split is a
    change of shelf, not of provenance, so inventing new values would quietly reorder the pick queue
    and orphan the audit trail.

    Deficient units stay with the original row. They are not on a shelf; they are a claim against
    the vendor, and moving a fraction of them to a bin nobody put them in would be a lie.
    """
    il = session.get(InventoryLocationModel, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")
    if quantity < 1:
        raise ValidationError("Split quantity must be at least 1", field="quantity")
    if quantity >= il.quantity:
        # Equal is refused too: splitting off everything is a no-op that leaves an empty row behind.
        raise ValidationError(
            f"Cannot split {quantity} off a row holding {il.quantity}; leave at least one unit behind",
            field="quantity",
        )

    remainder = InventoryLocationModel(
        project_id=il.project_id,
        po_line_item_id=il.po_line_item_id,
        receive_line_item_id=il.receive_line_item_id,
        stock_item_id=il.stock_item_id,
        shipment_return_item_id=il.shipment_return_item_id,
        warehouse_id=il.warehouse_id,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        quantity=quantity,
        deficient_quantity=0,
        aisle=None,
        row=None,
        bay=None,
        received_at=il.received_at,
    )
    il.quantity -= quantity
    session.add(remainder)
    session.flush()

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=remainder.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"splitFrom": str(il.id), "quantity": quantity},
    )
    return il, remainder
