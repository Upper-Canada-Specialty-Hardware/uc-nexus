import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import ReceiveDecisionChoice, ReceiveDecisionStatus


class ReceiveDecision(Base):
    """ "This shipment landed - does it stay in the project's inventory or go straight back out?"

    Raised the moment an approved receive is persisted, and owed to the person who raised the PO:
    they are the only one who knows whether the site is waiting on this hardware or whether it was
    ordered ahead of the schedule. Until they answer, the hardware simply sits in project inventory,
    which is the safe default and why this is a prompt rather than a gate.

    `target_user_id` is stamped from `PurchaseOrder.created_by_user_id` and is NULL for every PO
    raised before that column existed. That is deliberately not backfilled: the fallback lives in the
    read (`get_pending_decisions_for_user` matches the PO's GP buyer against the *caller's* own
    gpBuyerId), which costs one Clerk lookup for the person asking rather than a roster sweep inside
    the persist transaction of a GP receipt that has already posted.

    One row per delivery, enforced by the unique constraints: a delivery is one truck and gets one
    decision, however many PO lines it covered. Stock POs get no row at all - a decision about which
    project's inventory to keep something in is meaningless without a project.

    Since #499 the question is raised when the count is SUBMITTED, not when it is approved. Asking
    after approval meant the hardware had already been booked and put away, so "send it straight back
    out" meant undoing work. A row therefore hangs off `receive_draft_id` first and gets its
    `receive_record_id` stamped on at approval. Rows written before that change have the record and
    no draft, and every read checks which it has rather than assuming.
    """

    __tablename__ = "receive_decisions"
    __table_args__ = (
        UniqueConstraint("receive_record_id", name="uq_receive_decisions_receive_record"),
        UniqueConstraint("receive_draft_id", name="uq_receive_decisions_receive_draft"),
        CheckConstraint(
            "receive_record_id IS NOT NULL OR receive_draft_id IS NOT NULL",
            name="ck_receive_decisions_has_source",
        ),
        Index("ix_receive_decisions_target_status", "target_user_id", "status"),
        Index("ix_receive_decisions_po_id", "po_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Null until approval books the receipt: a draft-stage decision names the count, not the record.
    receive_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("receive_records.id"), nullable=True)
    receive_draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("receive_drafts.id"), nullable=True)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    target_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[ReceiveDecisionStatus] = mapped_column(
        Enum(ReceiveDecisionStatus, name="receive_decision_status", create_constraint=True),
        nullable=False,
    )
    decision: Mapped[ReceiveDecisionChoice | None] = mapped_column(
        Enum(ReceiveDecisionChoice, name="receive_decision_choice", create_constraint=True),
        nullable=True,
    )
    decided_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
