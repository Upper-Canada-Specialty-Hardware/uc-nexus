"""Repository for warehouse layout CRUD and utilization queries."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.opening_item import OpeningItem as OpeningItemModel
from app.models.warehouse_layout import WarehouseAisle, WarehouseBay, WarehouseBin, WarehouseRow


def _check_location_occupied(
    session: Session,
    aisle_name: str,
    row_name: str | None = None,
    bay_name: str | None = None,
    bin_name: str | None = None,
) -> int:
    """Count inventory items at a location. Returns total quantity."""
    inv_stmt = select(func.coalesce(func.sum(InventoryLocationModel.quantity), 0)).where(
        InventoryLocationModel.aisle == aisle_name,
        InventoryLocationModel.quantity > 0,
    )
    oi_stmt = select(func.count()).select_from(OpeningItemModel).where(OpeningItemModel.aisle == aisle_name)

    if row_name is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.row == row_name)
        oi_stmt = oi_stmt.where(OpeningItemModel.row == row_name)
    if bay_name is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.bay == bay_name)
        oi_stmt = oi_stmt.where(OpeningItemModel.bay == bay_name)
    if bin_name is not None:
        inv_stmt = inv_stmt.where(InventoryLocationModel.bin == bin_name)
        oi_stmt = oi_stmt.where(OpeningItemModel.bin == bin_name)

    inv_count = session.scalar(inv_stmt) or 0
    oi_count = session.scalar(oi_stmt) or 0
    return int(inv_count) + int(oi_count)


# ---------------------------------------------------------------------------
# Aisle CRUD
# ---------------------------------------------------------------------------


def get_aisles(session: Session, active_only: bool = True) -> list[WarehouseAisle]:
    stmt = select(WarehouseAisle).options(
        selectinload(WarehouseAisle.bays).selectinload(WarehouseBay.bins),
        selectinload(WarehouseAisle.rows),
    )
    if active_only:
        stmt = stmt.where(WarehouseAisle.is_active.is_(True))
    stmt = stmt.order_by(WarehouseAisle.x_position, WarehouseAisle.name)
    return list(session.scalars(stmt).unique().all())


def create_aisle(
    session: Session,
    name: str,
    label: str | None,
    orientation: str,
    x: int,
    y: int,
    w: int,
    h: int,
) -> WarehouseAisle:
    if not name or len(name) > 20:
        raise ValidationError("Aisle name must be 1-20 characters", field="name")
    if orientation not in ("HORIZONTAL", "VERTICAL"):
        raise ValidationError("Orientation must be HORIZONTAL or VERTICAL", field="orientation")
    aisle = WarehouseAisle(
        name=name,
        label=label,
        orientation=orientation,
        x_position=x,
        y_position=y,
        width=w,
        height=h,
    )
    session.add(aisle)
    session.flush()
    return aisle


def update_aisle(
    session: Session,
    aisle_id: uuid.UUID,
    name: str | None = None,
    label: str | None = None,
    orientation: str | None = None,
    x: int | None = None,
    y: int | None = None,
    w: int | None = None,
    h: int | None = None,
    is_active: bool | None = None,
) -> WarehouseAisle:
    aisle = session.get(WarehouseAisle, aisle_id)
    if aisle is None:
        raise NotFoundError(f"Aisle {aisle_id} not found")
    if name is not None:
        aisle.name = name
    if label is not None:
        aisle.label = label
    if orientation is not None:
        aisle.orientation = orientation
    if x is not None:
        aisle.x_position = x
    if y is not None:
        aisle.y_position = y
    if w is not None:
        aisle.width = w
    if h is not None:
        aisle.height = h
    if is_active is not None:
        if is_active is False and aisle.is_active is True:
            occupied = _check_location_occupied(session, aisle.name)
            if occupied > 0:
                raise ValidationError(
                    f"Cannot remove: {occupied} items are stored in Aisle {aisle.name}. Move or unlocate them first.",
                    field="is_active",
                )
        aisle.is_active = is_active
    return aisle


# ---------------------------------------------------------------------------
# Row CRUD
# ---------------------------------------------------------------------------


def get_rows(session: Session, aisle_id: uuid.UUID) -> list[WarehouseRow]:
    stmt = (
        select(WarehouseRow)
        .where(WarehouseRow.aisle_id == aisle_id, WarehouseRow.is_active.is_(True))
        .order_by(WarehouseRow.level, WarehouseRow.name)
    )
    return list(session.scalars(stmt).all())


def create_row(session: Session, aisle_id: uuid.UUID, name: str, level: int) -> WarehouseRow:
    if not name or len(name) > 20:
        raise ValidationError("Row name must be 1-20 characters", field="name")
    row = WarehouseRow(aisle_id=aisle_id, name=name, level=level)
    session.add(row)
    session.flush()
    return row


def update_row(
    session: Session,
    row_id: uuid.UUID,
    name: str | None = None,
    level: int | None = None,
    is_active: bool | None = None,
) -> WarehouseRow:
    row = session.get(WarehouseRow, row_id)
    if row is None:
        raise NotFoundError(f"Row {row_id} not found")
    if name is not None:
        row.name = name
    if level is not None:
        row.level = level
    if is_active is not None:
        if is_active is False and row.is_active is True:
            aisle = session.get(WarehouseAisle, row.aisle_id)
            aisle_name = aisle.name if aisle else ""
            occupied = _check_location_occupied(session, aisle_name, row_name=row.name)
            if occupied > 0:
                raise ValidationError(
                    f"Cannot remove: {occupied} items are stored in Row {row.name}. Move or unlocate them first.",
                    field="is_active",
                )
        row.is_active = is_active
    return row


# ---------------------------------------------------------------------------
# Bay CRUD
# ---------------------------------------------------------------------------


def get_bays(session: Session, aisle_id: uuid.UUID) -> list[WarehouseBay]:
    stmt = (
        select(WarehouseBay)
        .options(selectinload(WarehouseBay.bins))
        .where(WarehouseBay.aisle_id == aisle_id, WarehouseBay.is_active.is_(True))
        .order_by(WarehouseBay.row_position, WarehouseBay.col_position, WarehouseBay.name)
    )
    return list(session.scalars(stmt).unique().all())


def create_bay(session: Session, aisle_id: uuid.UUID, name: str, row_pos: int, col_pos: int) -> WarehouseBay:
    if not name or len(name) > 20:
        raise ValidationError("Bay name must be 1-20 characters", field="name")
    bay = WarehouseBay(aisle_id=aisle_id, name=name, row_position=row_pos, col_position=col_pos)
    session.add(bay)
    session.flush()
    return bay


def update_bay(
    session: Session,
    bay_id: uuid.UUID,
    name: str | None = None,
    row_pos: int | None = None,
    col_pos: int | None = None,
    is_active: bool | None = None,
) -> WarehouseBay:
    bay = session.get(WarehouseBay, bay_id)
    if bay is None:
        raise NotFoundError(f"Bay {bay_id} not found")
    if name is not None:
        bay.name = name
    if row_pos is not None:
        bay.row_position = row_pos
    if col_pos is not None:
        bay.col_position = col_pos
    if is_active is not None:
        if is_active is False and bay.is_active is True:
            aisle = session.get(WarehouseAisle, bay.aisle_id)
            aisle_name = aisle.name if aisle else ""
            occupied = _check_location_occupied(session, aisle_name, bay_name=bay.name)
            if occupied > 0:
                raise ValidationError(
                    f"Cannot remove: {occupied} items are stored in Bay {bay.name}. Move or unlocate them first.",
                    field="is_active",
                )
        bay.is_active = is_active
    return bay


# ---------------------------------------------------------------------------
# Bin CRUD
# ---------------------------------------------------------------------------


def get_bins(session: Session, bay_id: uuid.UUID, row_id: uuid.UUID | None = None) -> list[WarehouseBin]:
    stmt = (
        select(WarehouseBin)
        .where(WarehouseBin.bay_id == bay_id, WarehouseBin.is_active.is_(True))
        .order_by(WarehouseBin.row_position, WarehouseBin.col_position, WarehouseBin.name)
    )
    if row_id is not None:
        stmt = stmt.where(WarehouseBin.row_id == row_id)
    return list(session.scalars(stmt).all())


def create_bin(
    session: Session,
    bay_id: uuid.UUID,
    row_id: uuid.UUID | None,
    name: str,
    row_pos: int,
    col_pos: int,
    capacity: int | None,
) -> WarehouseBin:
    if not name or len(name) > 20:
        raise ValidationError("Bin name must be 1-20 characters", field="name")
    wbin = WarehouseBin(
        bay_id=bay_id,
        row_id=row_id,
        name=name,
        row_position=row_pos,
        col_position=col_pos,
        capacity=capacity,
    )
    session.add(wbin)
    session.flush()
    return wbin


def update_bin(
    session: Session,
    bin_id: uuid.UUID,
    name: str | None = None,
    row_pos: int | None = None,
    col_pos: int | None = None,
    capacity: int | None = None,
    is_active: bool | None = None,
) -> WarehouseBin:
    wbin = session.get(WarehouseBin, bin_id)
    if wbin is None:
        raise NotFoundError(f"Bin {bin_id} not found")
    if name is not None:
        wbin.name = name
    if row_pos is not None:
        wbin.row_position = row_pos
    if col_pos is not None:
        wbin.col_position = col_pos
    if capacity is not None:
        wbin.capacity = capacity
    if is_active is not None:
        if is_active is False and wbin.is_active is True:
            bay = session.get(WarehouseBay, wbin.bay_id)
            aisle = session.get(WarehouseAisle, bay.aisle_id) if bay else None
            aisle_name = aisle.name if aisle else ""
            bay_name = bay.name if bay else ""
            occupied = _check_location_occupied(session, aisle_name, bay_name=bay_name, bin_name=wbin.name)
            if occupied > 0:
                raise ValidationError(
                    f"Cannot remove: {occupied} items are stored in Bin {wbin.name}. Move or unlocate them first.",
                    field="is_active",
                )
        wbin.is_active = is_active
    return wbin


# ---------------------------------------------------------------------------
# Utilization queries (for viewer)
# ---------------------------------------------------------------------------


def get_aisle_utilization(session: Session) -> list[dict]:
    """Get aisles with aggregated inventory stats."""
    aisles = get_aisles(session, active_only=True)
    result = []
    for aisle in aisles:
        inv_stats = session.execute(
            select(
                func.coalesce(func.sum(InventoryLocationModel.quantity), 0),
                func.count(),
            ).where(InventoryLocationModel.aisle == aisle.name, InventoryLocationModel.quantity > 0)
        ).one()
        total_capacity = 0
        for bay in aisle.bays:
            for wbin in bay.bins:
                if wbin.capacity and wbin.is_active:
                    total_capacity += wbin.capacity
        result.append(
            {
                "aisle": aisle,
                "total_quantity": int(inv_stats[0]),
                "item_count": int(inv_stats[1]),
                "total_capacity": total_capacity,
            }
        )
    return result


def clone_aisle(
    session: Session,
    aisle_id: uuid.UUID,
    new_name: str,
    x: int,
    y: int,
) -> WarehouseAisle:
    """Clone an aisle with all its rows, bays, and bins."""
    if not new_name or len(new_name) > 20:
        raise ValidationError("Aisle name must be 1-20 characters", field="name")

    # Load source with all children
    stmt = (
        select(WarehouseAisle)
        .options(
            selectinload(WarehouseAisle.rows),
            selectinload(WarehouseAisle.bays).selectinload(WarehouseBay.bins),
        )
        .where(WarehouseAisle.id == aisle_id)
    )
    source = session.scalars(stmt).unique().first()
    if source is None:
        raise NotFoundError(f"Aisle {aisle_id} not found")

    # Create new aisle
    new_aisle = WarehouseAisle(
        name=new_name,
        label=source.label,
        orientation=source.orientation,
        x_position=x,
        y_position=y,
        width=source.width,
        height=source.height,
    )
    session.add(new_aisle)
    session.flush()

    # Copy rows, track old->new ID mapping
    row_id_map: dict[uuid.UUID, uuid.UUID] = {}
    for src_row in source.rows:
        if not src_row.is_active:
            continue
        new_row = WarehouseRow(
            aisle_id=new_aisle.id,
            name=src_row.name,
            level=src_row.level,
        )
        session.add(new_row)
        session.flush()
        row_id_map[src_row.id] = new_row.id

    # Copy bays and their bins
    for src_bay in source.bays:
        if not src_bay.is_active:
            continue
        new_bay = WarehouseBay(
            aisle_id=new_aisle.id,
            name=src_bay.name,
            row_position=src_bay.row_position,
            col_position=src_bay.col_position,
        )
        session.add(new_bay)
        session.flush()

        for src_bin in src_bay.bins:
            if not src_bin.is_active:
                continue
            new_row_id = row_id_map.get(src_bin.row_id) if src_bin.row_id else None
            new_bin = WarehouseBin(
                bay_id=new_bay.id,
                row_id=new_row_id,
                name=src_bin.name,
                row_position=src_bin.row_position,
                col_position=src_bin.col_position,
                capacity=src_bin.capacity,
            )
            session.add(new_bin)

    session.flush()
    return new_aisle


def suggest_put_away(
    session: Session,
    product_code: str,
    hardware_category: str,
    quantity: int,
) -> list[dict]:
    """Suggest bins for put-away based on co-location and capacity."""
    suggestions = []

    # 1. Co-located bins
    colocated = session.execute(
        select(
            InventoryLocationModel.aisle,
            InventoryLocationModel.row,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
            func.sum(InventoryLocationModel.quantity).label("current_qty"),
        )
        .where(
            InventoryLocationModel.product_code == product_code,
            InventoryLocationModel.aisle.is_not(None),
            InventoryLocationModel.quantity > 0,
        )
        .group_by(
            InventoryLocationModel.aisle,
            InventoryLocationModel.row,
            InventoryLocationModel.bay,
            InventoryLocationModel.bin,
        )
        .order_by(func.sum(InventoryLocationModel.quantity).desc())
        .limit(3)
    ).all()

    for r in colocated:
        suggestions.append(
            {
                "aisle": r[0],
                "row": r[1] or "",
                "bay": r[2],
                "bin": r[3],
                "reason": "co-located",
                "current_quantity": int(r[4]),
                "capacity": None,
            }
        )

    if len(suggestions) >= 3:
        return suggestions[:3]

    # 2. Bins with remaining capacity
    bins_with_cap = session.execute(
        select(WarehouseAisle.name, WarehouseBay.name, WarehouseBin.name, WarehouseBin.capacity)
        .join(WarehouseBay, WarehouseBin.bay_id == WarehouseBay.id)
        .join(WarehouseAisle, WarehouseBay.aisle_id == WarehouseAisle.id)
        .where(WarehouseBin.is_active.is_(True), WarehouseBin.capacity.is_not(None), WarehouseBin.capacity > 0)
        .order_by(WarehouseBin.capacity.desc())
        .limit(10)
    ).all()

    existing = {(s["aisle"], s["bay"], s["bin"]) for s in suggestions}
    for r in bins_with_cap:
        if len(suggestions) >= 3:
            break
        loc = (r[0], r[1], r[2])
        if loc in existing:
            continue
        current = (
            session.scalar(
                select(func.coalesce(func.sum(InventoryLocationModel.quantity), 0)).where(
                    InventoryLocationModel.aisle == r[0],
                    InventoryLocationModel.bay == r[1],
                    InventoryLocationModel.bin == r[2],
                )
            )
            or 0
        )
        remaining = r[3] - current
        if remaining >= quantity:
            suggestions.append(
                {
                    "aisle": r[0],
                    "row": "",
                    "bay": r[1],
                    "bin": r[2],
                    "reason": "capacity-available",
                    "current_quantity": int(current),
                    "capacity": r[3],
                }
            )

    return suggestions[:3]
