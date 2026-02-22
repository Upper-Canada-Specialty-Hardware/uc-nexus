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
