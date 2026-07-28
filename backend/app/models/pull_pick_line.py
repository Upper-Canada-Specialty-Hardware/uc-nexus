import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import PullPickLineState


class PullPickLine(Base):
    """One line of what the warehouse user dictated: this many units of this product came off this
    location for this pull (#367).

    This is the record the old FIFO deduction never kept. Approval used to walk `received_at` order
    and take units off whichever rows were oldest, so the answer to "where did the hardware for pull
    X actually come from" existed only as a scatter of audit rows nobody could reassemble. The picker
    now names the rows, on paper first and then in the system, and each named row becomes one of
    these.

    Two states, and the difference is whether inventory has moved:

    - **DRAFT** is the sheet being keyed in. Nothing has been deducted; the rows are a saved
      work-in-progress that survives a reload, and `save_pick_draft` replaces the whole set every
      time rather than merging, because the paper sheet - not the database - is the thing being
      transcribed.
    - **APPLIED** is a confirmed pick. The units are off the shelf, `applied_at` says when, and the
      row is now history: nothing rewrites or deletes it short of the pull being cancelled.

    `inventory_location_id` is nullable on purpose (ON DELETE SET NULL). A location can be merged
    away or deleted long after the pick, and when that happens the honest reading is "these units
    came from a row that no longer exists" - which the cancel path handles by falling back to the
    per-combo return. Keeping the category and code on the row is what makes that fallback possible
    without the FK.
    """

    __tablename__ = "pull_pick_lines"
    __table_args__ = (
        Index("ix_pull_pick_lines_pull_request", "pull_request_id"),
        Index("ix_pull_pick_lines_inventory_location", "inventory_location_id"),
        CheckConstraint("quantity >= 1", name="ck_pull_pick_lines_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    pull_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pull_requests.id", ondelete="CASCADE"), nullable=False
    )
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    inventory_location_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("inventory_locations.id", ondelete="SET NULL"), nullable=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[PullPickLineState] = mapped_column(
        Enum(PullPickLineState, name="pull_pick_line_state", create_constraint=True),
        nullable=False,
    )
    entered_by: Mapped[str] = mapped_column(String, nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
