import uuid
from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class SharepointMigrationRun(Base):
    """One completed SharePoint inventory migration. The wizard's re-run warning reads off this.

    `has_any_inventory` was never an idempotency marker - it answers "is this database empty", true on
    any environment that has ever received a PO. A row here means the migration actually ran, so the
    warning becomes definitive. Deliberately not preserved across a reset: a full data reset clears the
    table, which is what lets the cutover run the migration again after resetting.
    """

    __tablename__ = "sharepoint_migration_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    performed_by: Mapped[str] = mapped_column(String, nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_count: Mapped[int] = mapped_column(Integer, nullable=False)
