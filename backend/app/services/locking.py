import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Base

T = TypeVar("T", bound=Base)


def lock_rows(
    session: Session,
    model_class: type[T],
    ids: list[uuid.UUID],
) -> list[T]:
    """Acquire SELECT FOR UPDATE locks on rows sorted by ID to prevent deadlocks."""
    if not ids:
        return []

    sorted_ids = sorted(ids)
    stmt = select(model_class).where(model_class.id.in_(sorted_ids)).with_for_update().order_by(model_class.id)
    result = session.execute(stmt)
    return list(result.scalars().all())


def lock_inventory_combo(session: Session, inventory_location_id: uuid.UUID):
    """Row-lock every inventory row of one row's (project, category, code) and return that row, fresh.

    For writers that read a row's count and then write an absolute value (#1119): without the lock a
    pick confirmed between the read and the write is silently undone. The whole combo is locked, in id
    order, because that is the set a reservation mint (`get_available_quantities(lock=True)`) locks
    too and a pick confirm locks a subset of in the same order - one order everywhere, so two writers
    cannot deadlock - and because a transfer or an override may write a second row of the same combo.
    `populate_existing` matters: the row is usually already in the session from the tenancy check, and
    a plain FOR UPDATE would hand back that stale copy instead of the value the lock now guarantees.

    Returns None when the row does not exist.
    """
    from app.models.inventory import InventoryLocation

    il = session.get(InventoryLocation, inventory_location_id)
    if il is None:
        return None
    session.scalars(
        select(InventoryLocation)
        .where(
            InventoryLocation.project_id == il.project_id,
            InventoryLocation.hardware_category == il.hardware_category,
            InventoryLocation.product_code == il.product_code,
        )
        .order_by(InventoryLocation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()
    return il
