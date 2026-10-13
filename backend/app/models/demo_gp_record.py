import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class DemoGpRecord(Base):
    """What the simulated GP of the demo company holds (#1608).

    The demo company's GP is answered in-process (app/services/demo_gp.py) and never reaches a real one,
    but it still has to remember what was written to it: a PO registered into it reads back with its
    number and lines, a receipt posted against that PO shows up as received on the next read-back, and a
    job created through it is listed by the next job sync. Each of those is one row here, keyed by what
    GP itself keys it by.

    `kind` is what the row is (job, po, receipt, buyer, customer_address) and `key` its GP key (job
    number, PO number, receipt number, buyer id, customer|address code). `data` is the record in the
    shape the relay reads it back in, so the simulation answers with it as it stands.

    The vendor, customer, tax and cost-code masters are not here: they are fixed, and live in the
    simulation's code. Reset deletes every row.
    """

    __tablename__ = "demo_gp_records"
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_demo_gp_records_kind_key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
