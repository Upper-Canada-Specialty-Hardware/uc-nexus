import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class DemoInventorySnapshot(Base):
    """The legacy inventory export the demo company's warehouse is seeded from (#1638).

    One row at most: an upload replaces it. `rows` holds the export reduced by
    `app/services/demo_snapshot.parse_csv` to what the seed reads - no POs, notes or people.

    There is no company column on purpose. The demo reset deletes the rows that say `DEMO` and the rows
    that hang off them, so this one survives every reset and every reset seeds from it.
    """

    __tablename__ = "demo_inventory_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    rows: Mapped[list] = mapped_column(JSON, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
