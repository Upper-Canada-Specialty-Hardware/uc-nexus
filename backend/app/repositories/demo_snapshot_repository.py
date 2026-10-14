"""The stored demo inventory snapshot (#1638): replacing it, and reading it back for the seed."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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


def current(session: Session) -> DemoInventorySnapshot | None:
    return session.scalars(select(DemoInventorySnapshot).order_by(DemoInventorySnapshot.uploaded_at.desc())).first()


def rows(session: Session) -> list[SnapshotRow]:
    """The stored snapshot's rows, or none when nothing has been uploaded."""
    snapshot = current(session)
    return [SnapshotRow.from_dict(r) for r in snapshot.rows] if snapshot else []
