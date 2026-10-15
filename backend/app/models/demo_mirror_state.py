from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class DemoMirrorState(Base):
    """What the demo copy of UBC is built from and how its last runs went (#1657), one row per key.

      - `gp_masters`: UBC's GP masters as last read through the relay - vendors, customers, tax, cost
        codes, employees, buyers - which the simulated GP answers with.
      - `legacy_list`: how the last read of the legacy inventory list went (the rows themselves are in
        `demo_inventory_snapshots`).
      - `build`: the last full build - who started it, when, how it ended.
      - `nightly`: the last nightly sync - when, how it ended, what it added.

    No company column on purpose, like `demo_inventory_snapshots`: a rebuild wipes the rows that say
    `DEMO` and what hangs off them, and what it is built from must outlive it.
    """

    __tablename__ = "demo_mirror_state"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
