import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
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


class SharepointMigrationMark(Base):
    """The purchased-marking a migration run intended for one (project, category, code): N units.

    The marking itself lives as null-linked IN_PO HardwareItem rows, and those are rows a schedule
    re-import is free to wipe (`replace_schedule` deletes every HardwareItem). Without this record
    the marking would silently vanish with them and every rollup would read the project as
    never-purchased again. Finalize re-applies the recorded N against whatever rows the new schedule
    carries - see `import_repository`'s re-apply step. `quantity` is the coverage TARGET (what the
    migration landed on the shelf), not the row count the greedy pass happened to mark.
    """

    __tablename__ = "sharepoint_migration_marks"
    __table_args__ = (Index("ix_sharepoint_migration_marks_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sharepoint_migration_runs.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
