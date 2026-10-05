"""Physical locations: normalization, the defined-locations registry, browse/utilization/duplicates,
moves, merges."""

import re
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
from app.repositories import tenancy

from .audit import _log_audit_event, audit_scope


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


def _natural_key(value: str | None) -> tuple:
    """Natural order for a location part (#1569): digit runs as numbers, so bay 2 sorts before bay 10.

    Aisle, row and bay are text; a plain sort listed A-1-10 before A-1-2. The split always alternates text
    and digits starting with text, so the parts line up by type and the tuples compare safely.
    """
    parts = re.split(r"(\d+)", (value or "").casefold())
    return tuple(int(p) if i % 2 else p for i, p in enumerate(parts))


def get_warehouse_locations(
    session: Session,
    warehouse_id: uuid.UUID | None = None,
    active_only: bool = False,
    *,
    company: str | None = None,
) -> list[WarehouseLocationModel]:
    """The registry, ordered for pickers and the Locations tab. Scoped to the caller's company
    (#637) through the warehouse each location belongs to."""
    stmt = select(WarehouseLocationModel)
    if warehouse_id is not None:
        stmt = stmt.where(WarehouseLocationModel.warehouse_id == warehouse_id)
    if active_only:
        stmt = stmt.where(WarehouseLocationModel.active.is_(True))
    if company is not None:
        stmt = stmt.where(WarehouseLocationModel.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
    # #1569: natural order (A-1-2 before A-1-10), which SQL's text ordering can't give; the registry is small.
    return sorted(
        session.scalars(stmt).all(),
        key=lambda loc: (_natural_key(loc.aisle), _natural_key(loc.row), _natural_key(loc.bay)),
    )


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

    # The read above is unlocked, so two people defining the same shelf at once both reach here. The
    # insert runs in a savepoint and the loser's unique-key violation becomes the same conflict the
    # read gives, instead of a masked server error that also poisons the outer transaction (#1387).
    from sqlalchemy.exc import IntegrityError

    loc = WarehouseLocationModel(warehouse_id=warehouse_id, aisle=aisle, row=row, bay=bay, active=True)
    try:
        with session.begin_nested():
            session.add(loc)
            session.flush()
    except IntegrityError:
        raise ConflictError(f"{aisle} / {row} / {bay} is already defined in this warehouse") from None
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


# A location part the caller did not give at all, as against one given as null (#1251). An aisle-only
# shelf (row and bay null) is a place of its own: its panel must list what sits there, not every row
# in the aisle. So null matches NULL, and only an omitted part matches anything.
ANY_LOCATION_PART = object()


def _part_filter(column, value):
    if value is ANY_LOCATION_PART:
        return None
    if value is None:
        return column.is_(None)
    return column == value


def get_location_contents(
    session: Session,
    aisle: str,
    row_name: str | None | object = ANY_LOCATION_PART,
    bay: str | None | object = ANY_LOCATION_PART,
    warehouse_id: uuid.UUID | None = None,
    *,
    company: str | None = None,
) -> dict:
    """Get all inventory and stock items at a given location, optionally scoped to one warehouse
    and, since #637, to the caller's company - inventory through its project, stock through its
    warehouse."""
    # Inventory locations (project-bound)
    inv_stmt = (
        select(InventoryLocationModel, POLineItemModel.unit_cost, POModel.po_number)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .where(InventoryLocationModel.aisle == aisle, InventoryLocationModel.quantity > 0)
    )
    for clause in (
        _part_filter(InventoryLocationModel.row, row_name),
        _part_filter(InventoryLocationModel.bay, bay),
    ):
        if clause is not None:
            inv_stmt = inv_stmt.where(clause)
    if warehouse_id is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.warehouse_id == warehouse_id)
    if company is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.project_id.in_(tenancy.project_ids_for(company)))
    inv_rows = session.execute(inv_stmt).all()

    # Stock items (company-owned pool, not project-bound)
    si_stmt = select(StockItemModel).where(
        StockItemModel.aisle == aisle,
        StockItemModel.quantity + StockItemModel.deficient_quantity > 0,
    )
    for clause in (_part_filter(StockItemModel.row, row_name), _part_filter(StockItemModel.bay, bay)):
        if clause is not None:
            si_stmt = si_stmt.where(clause)
    if warehouse_id is not None:
        si_stmt = si_stmt.where(StockItemModel.warehouse_id == warehouse_id)
    if company is not None:
        si_stmt = si_stmt.where(StockItemModel.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
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


def get_location_utilization(
    session: Session, warehouse_id: uuid.UUID | None = None, *, company: str | None = None
) -> list[dict]:
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
    if company is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.project_id.in_(tenancy.project_ids_for(company)))
        si_stmt = si_stmt.where(StockItemModel.warehouse_id.in_(tenancy.warehouse_ids_for(company)))

    for stmt in (inv_stmt, si_stmt):
        for r in session.execute(stmt).all():
            _bump(r[0], r[1], r[2], r[3], r[4], r[5])

    return sorted(
        aggregated.values(),
        # #1569: natural order within a warehouse, so A-1-2 comes before A-1-10.
        key=lambda entry: (
            str(entry["warehouse_id"]),
            _natural_key(entry["aisle"]),
            _natural_key(entry["row"]),
            _natural_key(entry["bay"]),
        ),
    )


def get_location_audit_history(
    session: Session,
    aisle: str,
    row_name: str | None | object = ANY_LOCATION_PART,
    bay: str | None | object = ANY_LOCATION_PART,
    limit: int = 10,
    warehouse_id: uuid.UUID | None = None,
    *,
    company: str | None = None,
) -> list[InventoryAuditLog]:
    """Recent audit log entries whose detail.fromLocation or detail.toLocation matches the location.

    When warehouse_id is given the match tightens to entries whose location object also carries that
    warehouse (via location_detail's warehouseId stamp). Entries written before the stamp existed have
    no warehouseId and so drop out of a scoped query - decided and acceptable; unscoped is unchanged.
    """
    # Build the matching predicate via JSONB containment. Postgres-only — matches the JSONB column.
    from_match: dict = {"aisle": aisle}
    to_match: dict = {"aisle": aisle}
    # A null part is written into the location object as JSON null (location_detail), so containment
    # on {"row": None} matches exactly the aisle-only entries (#1251); an omitted part matches any.
    if row_name is not ANY_LOCATION_PART:
        from_match["row"] = row_name
        to_match["row"] = row_name
    if bay is not ANY_LOCATION_PART:
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
            # #1574: a fold is logged on both rows with the same locations; the shelf shows it once, from the
            # source's entry. The surviving row's mirror stays in its own drawer.
            ~InventoryAuditLog.detail.has_key("foldedFromStockItemId"),
        )
        .order_by(InventoryAuditLog.created_at.desc())
    )
    if company is not None:
        # Job rows scope through their project, stock rows through the stock item's warehouse (#1045).
        stmt = stmt.where(audit_scope(company))
    return list(session.scalars(stmt.limit(limit)).all())


def _holds_something(model):
    """A row that holds something, as the contents and utilization views count it (#1587): an inventory row
    with units, or a pool row with sound or deficient units. An emptied row - picked down to 0, or a stock
    row a fold kept because something still points at it - is hidden everywhere else, so it must not keep a
    duplicate group listed (or be offered for a merge that can only fold 0)."""
    if model is StockItemModel:
        return StockItemModel.quantity + StockItemModel.deficient_quantity > 0
    return InventoryLocationModel.quantity > 0


def get_distinct_location_values(session: Session, *, company: str | None = None) -> dict[str, list[str]]:
    """Return distinct aisle/row/bay values across inventory and stock tables for autocomplete,
    within the caller's company (#637)."""
    aisles: set[str] = set()
    row_values: set[str] = set()
    bays: set[str] = set()

    for model in (InventoryLocationModel, StockItemModel):
        stmt = (
            select(model.aisle, model.row, model.bay)
            .where(model.aisle.is_not(None), _holds_something(model))
            .distinct()
        )
        if company is not None:
            stmt = stmt.where(model.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
        records = session.execute(stmt).all()
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


def get_location_duplicates(session: Session, *, company: str | None = None) -> list[dict]:
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
        stmt = (
            select(model.warehouse_id, model.aisle, model.row, model.bay)
            .where(model.aisle.is_not(None), _holds_something(model))
            .distinct()
        )
        if company is not None:
            stmt = stmt.where(model.warehouse_id.in_(tenancy.warehouse_ids_for(company)))
        for wh, a, b, c in session.execute(stmt).all():
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


def _matches_from(column, value: str | None):
    """A merge's from row or bay as a filter, never the aisle. The cleanup page sends a variant's
    missing row or bay as an empty string (#1199), and `column == ''` never matches the NULL the row
    actually holds, so an empty or missing value matches a NULL (or empty) column instead."""
    if value is None or value == "":
        return or_(column.is_(None), column == "")
    return column == value


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

    # The aisle is what makes a row located: an empty from-aisle would name the unlocated rows, and
    # null-matching it would sweep every one of them in the warehouse onto the target shelf. Only row
    # and bay match null (#1199); the aisle is required and compared as given.
    if not (from_aisle or "").strip():
        raise ValidationError("from_aisle is required", field="from_aisle")
    to_aisle, to_row, to_bay = _normalize_and_validate_location_fields(to_aisle, to_row, to_bay)
    ensure_registered_location(session, warehouse_id, to_aisle, to_row, to_bay)
    # from_* may already be in canonical form; either way only compare equality, no validation needed.

    counts = {"inventory_locations": 0, "stock_items": 0}
    from_loc = location_detail(from_aisle, from_row, from_bay, warehouse_id)
    to_loc = location_detail(to_aisle, to_row, to_bay, warehouse_id)

    # Locked (#1422): only the shelf columns are written, so a concurrent quantity change survives the
    # UPDATE either way, but an unlocked read let a row moved off this shelf meanwhile be dragged back
    # onto the target, and one deleted meanwhile fail the flush. Under the lock Postgres re-checks the
    # shelf filter against the committed row, so neither is picked up. Id order, one order everywhere.
    inv_rows = list(
        session.scalars(
            select(InventoryLocationModel)
            .where(
                InventoryLocationModel.warehouse_id == warehouse_id,
                InventoryLocationModel.aisle == from_aisle,
                _matches_from(InventoryLocationModel.row, from_row),
                _matches_from(InventoryLocationModel.bay, from_bay),
            )
            .order_by(InventoryLocationModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
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

    from app.repositories.stock.common import (
        _find_stock_row,
        fold_into_same_key_row,
        lock_pool_rows,
        log_stock_shelf_event,
    )

    found = list(
        session.scalars(
            select(StockItemModel).where(
                StockItemModel.warehouse_id == warehouse_id,
                StockItemModel.aisle == from_aisle,
                _matches_from(StockItemModel.row, from_row),
                _matches_from(StockItemModel.bay, from_bay),
                # #1587: an empty pool row a fold kept (still referenced) stays hidden where it is. Moving it
                # onto the destination would put two rows of one key on one shelf (#1164); folding it moves 0
                # units and only writes another entry and a misleading count.
                _holds_something(StockItemModel),
            )
        ).all()
    )
    # #1422: a fold adds the source's units to the target and zeroes the source, so both rows are
    # written from their counts. Every source and the same-key row each would fold into are locked
    # together, fresh and in id order (#1401) - the fold used to work from this unlocked read, and a pull
    # or adjustment committed in between was overwritten: the source zeroed, its stale count added to
    # the target. Targets are found unlocked first; the fold re-finds its target, already held.
    targets = [
        _find_stock_row(
            session,
            warehouse_id=si.warehouse_id,
            hardware_category=si.hardware_category,
            product_code=si.product_code,
            aisle=to_aisle,
            row=to_row,
            bay=to_bay,
            kind=si.kind,
            unit_cost=si.unit_cost,
            lock=False,
        )
        for si in found
    ]
    locked = lock_pool_rows(session, [si.id for si in found] + [t.id for t in targets if t is not None])

    def _still_on_source_shelf(si: StockItemModel) -> bool:
        # A row moved off the shelf while the lock waited is no longer this merge's to move.
        def same(value, wanted):
            return (value or "") == (wanted or "")

        return si.aisle == from_aisle and same(si.row, from_row) and same(si.bay, from_bay)

    # A source a concurrent move folded away and deleted is not in the locked rows; it is gone, not moved.
    si_rows = [locked[si.id] for si in found if si.id in locked and _still_on_source_shelf(locked[si.id])]

    for si in si_rows:
        # A row already on the target shelf with this row's key takes its units (#1164), through the
        # same fold a single move or put-away uses (#1377).
        detail = {"fromLocation": from_loc, "toLocation": to_loc, "reason": "location_merge"}
        source_id, moved, moved_deficient = si.id, si.quantity, si.deficient_quantity
        target = fold_into_same_key_row(session, si, aisle=to_aisle, row=to_row, bay=to_bay)
        if target is None:
            si.aisle, si.row, si.bay = to_aisle, to_row, to_bay
        session.flush()
        log_stock_shelf_event(
            session,
            source_id=source_id,
            target=target,
            moved_quantity=moved,
            moved_deficient=moved_deficient,
            action=AuditAction.MOVE,
            performed_by=performed_by,
            detail=detail,
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


def refuse_if_already_located(aisle: str | None, row: str | None, bay: str | None) -> None:
    """Put-away is for a row with no shelf; one already on a shelf was put away by someone else (#1567)."""
    if aisle is None:
        return
    label = "-".join(p for p in (aisle, row, bay) if p)
    raise ConflictError(f"This was already put away at {label} - refresh to see it.")


def assign_inventory_location(
    session: Session, inv_id: uuid.UUID, aisle: str, row: str, bay: str, *, performed_by: str
) -> InventoryLocationModel:
    """Assign aisle/row/bay to an InventoryLocation."""
    from app.services.locking import lock_inventory_combo

    aisle, row, bay = _normalize_and_validate_location_fields(aisle, row, bay)
    # #1567: locked, and refused once it is on a shelf. Two workers on the same put-away list both saw the
    # row unlocated; the second silently moved hardware the first had already shelved, so Nexus named the
    # wrong bin. Moving a shelved row is Move's job, and says so.
    il = lock_inventory_combo(session, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")
    refuse_if_already_located(il.aisle, il.row, il.bay)
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
    from app.services.locking import lock_inventory_combo

    if quantity < 1:
        raise ValidationError("Split quantity must be at least 1", field="quantity")
    il = lock_inventory_combo(session, inv_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inv_id} not found")
    # #1567: a partial put-away splits first; a row someone else already shelved must not be split off it.
    refuse_if_already_located(il.aisle, il.row, il.bay)
    deficient = il.deficient_quantity or 0
    if quantity >= il.quantity:
        # Equal is refused too: splitting off everything is a no-op that leaves an empty row behind.
        raise ValidationError(
            f"Cannot split {quantity} off a row holding {il.quantity}; leave at least one unit behind",
            field="quantity",
        )
    if quantity > il.quantity - deficient:
        # The deficient units stay on this row, so only the sound ones can leave it (#1130). Without
        # this the row drops below its own deficient count and the CHECK fails as a raw 500.
        raise ValidationError(
            f"Cannot split {quantity} off this row: {deficient} of its {il.quantity} are deficient and stay "
            f"behind, so at most {il.quantity - deficient} can be put away elsewhere",
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
    old_quantity = il.quantity
    il.quantity -= quantity
    session.add(remainder)
    session.flush()

    # #1574: both rows, so the original's history explains the units that left it - not only the new
    # row's. The split is a step of a put-away, not one: the remainder is still unlocated here.
    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.ADJUSTMENT,
        performed_by=performed_by,
        detail={
            "reason": "split",
            "splitInto": str(remainder.id),
            "quantity": quantity,
            # The history drawer renders an adjustment as old -> new (signed change).
            "adjustment": -quantity,
            "oldQuantity": old_quantity,
            "newQuantity": il.quantity,
        },
    )
    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=remainder.id,
        action=AuditAction.PUT_AWAY,
        performed_by=performed_by,
        detail={"reason": "split", "splitFrom": str(il.id), "quantity": quantity},
    )
    return il, remainder
