"""Physical locations: normalization, the defined-locations registry, browse/utilization/duplicates,
moves, merges."""

import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import AuditAction, AuditEntityType
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse_location import WarehouseLocation as WarehouseLocationModel

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


def ensure_registered_location(session: Session, warehouse_id: uuid.UUID, aisle: str, row: str, bay: str) -> None:
    """Refuse a location triple that is not defined and active in the warehouse's registry (#632).

    Expects CANONICAL input - every caller normalizes first, and registry rows are stored normalized,
    so this is exact string equality. Callers pass the location the USER CHOSE (a put-away, a move, a
    destock/allocate target, a transfer destination); a location merely inherited off an existing row
    (destock keeping the source's shelf) is not re-checked, so retiring a location never strands the
    hardware already on it.
    """
    exists = session.scalar(
        select(WarehouseLocationModel.id).where(
            WarehouseLocationModel.warehouse_id == warehouse_id,
            WarehouseLocationModel.aisle == aisle,
            WarehouseLocationModel.row == row,
            WarehouseLocationModel.bay == bay,
            WarehouseLocationModel.active.is_(True),
        )
    )
    if exists is None:
        raise ValidationError(
            f"{aisle} / {row} / {bay} is not a defined location in this warehouse. "
            "Define it on the Locations tab first.",
            field="location",
        )


def get_warehouse_locations(
    session: Session, warehouse_id: uuid.UUID | None = None, active_only: bool = False
) -> list[WarehouseLocationModel]:
    """The registry, ordered for pickers and the Locations tab."""
    stmt = select(WarehouseLocationModel).order_by(
        WarehouseLocationModel.aisle, WarehouseLocationModel.row, WarehouseLocationModel.bay
    )
    if warehouse_id is not None:
        stmt = stmt.where(WarehouseLocationModel.warehouse_id == warehouse_id)
    if active_only:
        stmt = stmt.where(WarehouseLocationModel.active.is_(True))
    return list(session.scalars(stmt).all())


def create_warehouse_location(
    session: Session, warehouse_id: uuid.UUID, aisle: str, row: str, bay: str
) -> WarehouseLocationModel:
    """Define a location. Re-defining a deactivated one reactivates it - the row keeps its identity."""
    from app.models.warehouse import Warehouse as WarehouseModel

    if session.get(WarehouseModel, warehouse_id) is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    aisle, row, bay = _normalize_and_validate_location_fields(aisle, row, bay)

    existing = session.scalars(
        select(WarehouseLocationModel).where(
            WarehouseLocationModel.warehouse_id == warehouse_id,
            WarehouseLocationModel.aisle == aisle,
            WarehouseLocationModel.row == row,
            WarehouseLocationModel.bay == bay,
        )
    ).first()
    if existing is not None:
        if existing.active:
            raise ConflictError(f"{aisle} / {row} / {bay} is already defined in this warehouse")
        existing.active = True
        session.flush()
        return existing

    loc = WarehouseLocationModel(warehouse_id=warehouse_id, aisle=aisle, row=row, bay=bay, active=True)
    session.add(loc)
    session.flush()
    return loc


def deactivate_warehouse_location(session: Session, location_id: uuid.UUID) -> WarehouseLocationModel:
    """Retire a location from the pickers. Hardware already sitting there stays put - the utilization
    view keeps showing an occupied retired location until it drains."""
    loc = session.get(WarehouseLocationModel, location_id)
    if loc is None:
        raise NotFoundError(f"Warehouse location {location_id} not found")
    loc.active = False
    session.flush()
    return loc


def location_detail(aisle: str | None, row: str | None, bay: str | None, warehouse_id: uuid.UUID | None) -> dict:
    """A location object for an audit-log detail payload, stamped with the warehouse it happened in.

    get_location_audit_history filters by JSONB containment against this exact shape, so a move is
    only warehouse-filterable when the warehouse is written into its location object here. Every audit
    write whose detail carries a location (put-away, move, unlocate, merge, transfer, destock,
    allocate, receive, override) builds it through this helper so the write shape and the read filter
    cannot drift apart. Rows written before the stamp existed carry no warehouseId and fall out of a
    warehouse-scoped history query - decided and acceptable; an unscoped query still returns them.
    """
    return {
        "aisle": aisle,
        "row": row,
        "bay": bay,
        "warehouseId": str(warehouse_id) if warehouse_id else None,
    }


def clone_origin_fields(source: InventoryLocationModel) -> dict:
    """The four origin FKs (plus off-PO unit cost) that make an InventoryLocation traceable, copied verbatim.

    Every row derived from another - a transfer's new bin, an override-increase's added row, a
    split's remainder - inherits its parent's origin so the ck_inventory_locations_has_origin CHECK
    holds and its valuation keeps the parent's PO/return provenance. All four FKs travel together:
    dropping shipment_return_item_id orphans a return-origin row (its other three FKs are null) and
    the CHECK rejects the write with a raw 500.

    `unit_cost` rides alongside them: a PO-origin row carries null here (its cost is on the PO line),
    but a migrated off-PO row's cost lives only on this column, so a derived row that dropped it would
    silently value at zero.
    """
    return {
        "po_line_item_id": source.po_line_item_id,
        "receive_line_item_id": source.receive_line_item_id,
        "stock_item_id": source.stock_item_id,
        "shipment_return_item_id": source.shipment_return_item_id,
        "unit_cost": source.unit_cost,
    }


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

    def _unit_cost(il, po_unit_cost):
        # PO line cost, then the row's own off-PO cost (the migration), then None.
        if po_unit_cost is not None:
            return float(po_unit_cost)
        return float(il.unit_cost) if il.unit_cost is not None else None

    return {
        "inventory_items": [
            {
                "inventory_location": row[0],
                "unit_cost": _unit_cost(row[0], row[1]),
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
    session: Session,
    aisle: str,
    row_name: str | None = None,
    bay: str | None = None,
    limit: int = 10,
    warehouse_id: uuid.UUID | None = None,
) -> list[InventoryAuditLog]:
    """Recent audit log entries whose detail.fromLocation or detail.toLocation matches the location.

    When warehouse_id is given the match tightens to entries whose location object also carries that
    warehouse (via location_detail's warehouseId stamp). Entries written before the stamp existed have
    no warehouseId and so drop out of a scoped query - decided and acceptable; unscoped is unchanged.
    """
    # Build the matching predicate via JSONB containment. Postgres-only — matches the JSONB column.
    from_match: dict = {"aisle": aisle}
    to_match: dict = {"aisle": aisle}
    if row_name is not None:
        from_match["row"] = row_name
        to_match["row"] = row_name
    if bay is not None:
        from_match["bay"] = bay
        to_match["bay"] = bay
    if warehouse_id is not None:
        wid = str(warehouse_id)
        from_match["warehouseId"] = wid
        to_match["warehouseId"] = wid

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
    """Return distinct aisle/row/bay values across inventory and stock tables for autocomplete."""
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
    """Group location triples that collide on case-insensitive equality, scoped per warehouse.

    A location string is one physical place only WITHIN a warehouse, so the same (aisle, row, bay)
    triple stored two ways in two warehouses is two independent groups, not one - grouping across
    warehouses would offer a merge that rewrites rows in a warehouse the admin never looked at. Each
    group carries its warehouse (id + code label), lists the distinct stored variants, and the
    canonical (uppercase, trimmed) form. Only groups with 2+ variants are returned.
    """
    from app.models.warehouse import Warehouse as WarehouseModel

    quads: set[tuple[uuid.UUID | None, str, str | None, str | None]] = set()
    for model in (InventoryLocationModel, StockItemModel):
        records = session.execute(
            select(model.warehouse_id, model.aisle, model.row, model.bay).where(model.aisle.is_not(None)).distinct()
        ).all()
        for wh, a, b, c in records:
            quads.add((wh, a, b, c))

    groups: dict[tuple, list[tuple[str, str | None, str | None]]] = defaultdict(list)
    for wh, a, b, c in quads:
        canonical = (
            normalize_location_value(a),
            normalize_location_value(b),
            normalize_location_value(c),
        )
        groups[(wh, *canonical)].append((a, b, c))

    labels = {wid: code for wid, code in session.execute(select(WarehouseModel.id, WarehouseModel.code)).all()}

    result = []
    for (wh, canon_aisle, canon_row, canon_bay), variants in groups.items():
        if len(variants) < 2:
            continue
        result.append(
            {
                "warehouse_id": wh,
                "warehouse_label": labels.get(wh),
                "canonical_aisle": canon_aisle,
                "canonical_row": canon_row,
                "canonical_bay": canon_bay,
                "variants": [{"aisle": v[0], "row": v[1], "bay": v[2]} for v in sorted(variants, key=lambda t: str(t))],
            }
        )
    return sorted(
        result,
        key=lambda g: (
            g["warehouse_label"] or "",
            g["canonical_aisle"] or "",
            g["canonical_row"] or "",
            g["canonical_bay"] or "",
        ),
    )


def merge_locations(
    session: Session,
    *,
    warehouse_id: uuid.UUID,
    from_aisle: str,
    from_row: str,
    from_bay: str,
    to_aisle: str,
    to_row: str,
    to_bay: str,
    performed_by: str,
) -> dict:
    """Rewrite every row at (from_aisle, from_row, from_bay) to (to_aisle, to_row, to_bay), in one warehouse.

    Scoped to warehouse_id: a location string is one physical place only within a warehouse, so a
    merge must not touch a row that happens to share the string in another warehouse. Touches
    inventory_locations and stock_items. Writes a MOVE audit per row so the merge is reconstructable.
    Returns counts per source table.
    """
    if not performed_by:
        raise ValidationError("performed_by is required", field="performed_by")

    to_aisle, to_row, to_bay = _normalize_and_validate_location_fields(to_aisle, to_row, to_bay)
    ensure_registered_location(session, warehouse_id, to_aisle, to_row, to_bay)
    # from_* may already be in canonical form; either way only compare equality, no validation needed.

    counts = {"inventory_locations": 0, "stock_items": 0}
    from_loc = location_detail(from_aisle, from_row, from_bay, warehouse_id)
    to_loc = location_detail(to_aisle, to_row, to_bay, warehouse_id)

    inv_rows = list(
        session.scalars(
            select(InventoryLocationModel).where(
                InventoryLocationModel.warehouse_id == warehouse_id,
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
                "fromLocation": from_loc,
                "toLocation": to_loc,
                "reason": "location_merge",
            },
        )
    counts["inventory_locations"] = len(inv_rows)

    si_rows = list(
        session.scalars(
            select(StockItemModel).where(
                StockItemModel.warehouse_id == warehouse_id,
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
                "fromLocation": from_loc,
                "toLocation": to_loc,
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
    ensure_registered_location(session, il.warehouse_id, new_aisle, new_row, new_bay)

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
            "fromLocation": location_detail(old_aisle, old_row, old_bay, il.warehouse_id),
            "toLocation": location_detail(new_aisle, new_row, new_bay, il.warehouse_id),
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
        detail={"fromLocation": location_detail(old_aisle, old_row, old_bay, il.warehouse_id)},
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
    ensure_registered_location(session, il.warehouse_id, aisle, row, bay)

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
        detail={"toLocation": location_detail(aisle, row, bay, il.warehouse_id)},
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
        **clone_origin_fields(il),
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
