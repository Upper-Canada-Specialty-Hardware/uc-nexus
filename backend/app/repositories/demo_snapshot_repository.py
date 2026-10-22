"""The stored demo inventory snapshot (#1638): replacing it, and reading it back for the seed."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, defer

from app.models.demo_inventory_snapshot import DemoInventorySnapshot
from app.services.demo_snapshot import SnapshotRow


def store(session: Session, *, file_name: str, rows: list[SnapshotRow], uploaded_by: str) -> DemoInventorySnapshot:
    """Replace the stored snapshot. The caller commits. The next demo reset seeds from it."""
    session.execute(delete(DemoInventorySnapshot))
    snapshot = DemoInventorySnapshot(
        file_name=file_name.strip()[:255] or "inventory.csv",
        rows=[r.to_dict() for r in rows],
        row_count=len(rows),
        uploaded_by=uploaded_by[:255],
        uploaded_at=datetime.utcnow(),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def current(session: Session, *, with_rows: bool = True) -> DemoInventorySnapshot | None:
    """The stored snapshot. Without its rows (#1833), for a reader that wants only when it was read and how
    many rows it has: the rows are the whole legacy list as JSON."""
    query = select(DemoInventorySnapshot).order_by(DemoInventorySnapshot.uploaded_at.desc())
    if not with_rows:
        query = query.options(defer(DemoInventorySnapshot.rows))
    return session.scalars(query).first()


def rows(session: Session) -> list[SnapshotRow]:
    """The stored snapshot's rows, or none when nothing has been uploaded."""
    snapshot = current(session)
    return [SnapshotRow.from_dict(r) for r in snapshot.rows] if snapshot else []


def clear(session: Session) -> bool:
    """Drop the stored snapshot. The caller commits. Whether there was one."""
    return session.execute(delete(DemoInventorySnapshot)).rowcount > 0
