"""Drafted receives and the approval that posts them.

A receive used to be one action. It is two now: somebody counts the truck and submits a draft, and a
Warehouse Manager approves it - which is the moment the GP-first pipeline in schemas/warehouse.py
runs (relay receipt -> RCT###### -> persist -> inventory). Everything in this module is the first
half plus the handover; nothing here touches GP or inventory.

The approve handover is the only subtle part. GP is a relay round trip and a database lock cannot be
held across it, so `claim_for_approval` flips the draft to APPROVING in a transaction the resolver
commits BEFORE calling the relay. That claim is what makes a second approver bounce off instead of
posting a duplicate GP receipt, and it is why the resolver has to release it (`release_approval_claim`)
if it fails before the relay call.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import NotificationType, ReceiveDraftStatus
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receive_draft import ReceiveDraft as ReceiveDraftModel
from app.models.receive_draft import ReceiveDraftLineItem as ReceiveDraftLineItemModel
from app.services import notification_service
from app.services.locking import lock_rows

from .receiving import validate_receive_eligibility

# The statuses that hold a claim on a PO line's pending quantity without having consumed it yet.
# APPROVING is mid-relay; APPROVED with no receive record is queued on the GP outbox. Both will
# eventually book units against the PO, so a third draft must be measured against them.
_IN_FLIGHT_STATUSES = (ReceiveDraftStatus.APPROVING, ReceiveDraftStatus.APPROVED)

MAX_REJECTION_REASON = 1000


class ApprovalContext:
    """What the approve resolver needs after the claim, in the shape the GP pipeline already speaks.

    Deliberately a plain object built inside the claim transaction rather than the ORM draft: the
    resolver hands `line_items_data` straight to `_prepare_create_receive` and, when the relay is
    down, to the outbox's JSON `persist_context`. Passing a detached ORM row instead would mean
    re-opening a session in the middle of an async resolver just to read attributes.
    """

    __slots__ = ("draft_id", "po_id", "warehouse_id", "author_name", "line_items_data")

    def __init__(self, draft_id, po_id, warehouse_id, author_name, line_items_data):
        self.draft_id = draft_id
        self.po_id = po_id
        self.warehouse_id = warehouse_id
        self.author_name = author_name
        self.line_items_data = line_items_data


def _line_items_data(draft: ReceiveDraftModel) -> list[dict]:
    """The draft's lines in the dict shape create_receive / the outbox context take. `locations` is
    stored in exactly that shape already, so this is a re-key, not a translation."""
    return [
        {
            "po_line_item_id": li.po_line_item_id,
            "quantity_received": li.quantity_received,
            "locations": [dict(loc) for loc in (li.locations or [])],
        }
        for li in draft.line_items
    ]


def _get_draft(session: Session, draft_id: uuid.UUID) -> ReceiveDraftModel:
    stmt = (
        select(ReceiveDraftModel)
        .options(selectinload(ReceiveDraftModel.line_items))
        .where(ReceiveDraftModel.id == draft_id)
    )
    draft = session.scalars(stmt).unique().first()
    if draft is None:
        raise NotFoundError(f"Receive draft {draft_id} not found")
    return draft


def _write_lines(session: Session, draft: ReceiveDraftModel, po: POModel, line_items_input: list[dict]) -> None:
    """Replace the draft's lines wholesale. A re-count is a new sheet, not a merge - the same reading
    `save_pick_draft` takes of a dictated pick."""
    for existing in list(draft.line_items):
        session.delete(existing)
    session.flush()

    poli_dict: dict[uuid.UUID, POLineItemModel] = {li.id: li for li in po.line_items}
    for li_input in line_items_input:
        poli = poli_dict[li_input["po_line_item_id"]]
        session.add(
            ReceiveDraftLineItemModel(
                id=uuid.uuid4(),
                receive_draft_id=draft.id,
                po_line_item_id=poli.id,
                hardware_category=poli.hardware_category,
                product_code=poli.product_code,
                quantity_received=li_input["quantity_received"],
                locations=[dict(loc) for loc in (li_input.get("locations") or [])],
            )
        )
    session.flush()


def _notify_submitted(session: Session, draft: ReceiveDraftModel, po: POModel) -> None:
    """Tell the manager audience there is something in the queue.

    Skipped for a stock PO: `notifications.project_id` is NOT NULL and inventing a project to satisfy
    it would be worse than the omission (the same call `_notify_failure` makes in the outbox worker).
    The approvals queue is the backstop - it lists every pending draft regardless.
    """
    if po.project_id is None:
        return
    total = sum(li.quantity_received for li in draft.line_items)
    notification_service.create_notification(
        session,
        project_id=po.project_id,
        recipient_role=notification_service.WAREHOUSE_MANAGER_RECIPIENT_ROLE,
        notification_type=NotificationType.RECEIVE_DRAFT_SUBMITTED,
        message=(
            f"{draft.created_by_name} submitted a receive of {total} "
            f"{'unit' if total == 1 else 'units'} against PO {po.po_number} for approval."
        ),
    )


def _validate_packing_slip(session: Session, po_id: uuid.UUID, document_id: uuid.UUID | None) -> None:
    """A draft is a count made against a piece of paper (#504), so it must name which one.

    Checked here rather than left to the FK: the document has to be a PACKING_SLIP AND belong to the
    PO being received, or the link records a slip from somebody else's delivery.
    """
    from app.models.enums import PODocumentType
    from app.models.purchase_order import PODocument

    if document_id is None:
        raise ValidationError(
            "A packing slip is required to record a delivery.",
            field="packing_slip_document_id",
        )

    doc = session.get(PODocument, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    if doc.po_id != po_id:
        raise ValidationError(
            "That packing slip belongs to a different purchase order.",
            field="packing_slip_document_id",
        )
    if doc.document_type != PODocumentType.PACKING_SLIP:
        raise ValidationError(
            "That document is not a packing slip.",
            field="packing_slip_document_id",
        )


def create_receive_draft(
    session: Session,
    po_id: uuid.UUID,
    line_items_input: list[dict],
    author_user_id: str,
    author_name: str,
    warehouse_id: uuid.UUID | None = None,
    *,
    idempotency_key: str | None = None,
    packing_slip_document_id: uuid.UUID | None = None,
) -> ReceiveDraftModel:
    """Record a counted delivery for a Warehouse Manager to approve.

    Validates with the SAME rules the GP pre-flight uses, so an over-receive or a receive against a
    closed PO is refused in front of the person holding the packing slip rather than surfacing hours
    later to whoever opens the queue. Approval re-validates anyway - the world can move underneath a
    draft - but a draft nobody could ever approve is not worth creating.
    """
    _validate_packing_slip(session, po_id, packing_slip_document_id)

    if idempotency_key:
        existing = session.scalars(
            select(ReceiveDraftModel)
            .options(selectinload(ReceiveDraftModel.line_items))
            .where(ReceiveDraftModel.create_idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            return existing

    validate_receive_eligibility(session, po_id, author_name, line_items_input)

    po = (
        session.scalars(select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id))
        .unique()
        .first()
    )

    draft = ReceiveDraftModel(
        id=uuid.uuid4(),
        po_id=po_id,
        warehouse_id=warehouse_id,
        status=ReceiveDraftStatus.PENDING_APPROVAL,
        created_by_user_id=author_user_id,
        created_by_name=author_name,
        create_idempotency_key=idempotency_key or None,
        packing_slip_document_id=packing_slip_document_id,
    )
    session.add(draft)
    session.flush()

    _write_lines(session, draft, po, line_items_input)
    session.refresh(draft)

    # #499: the keep-or-ship question belongs to whoever raised the PO, and they get the whole
    # approval window to answer it now instead of being asked after the hardware was already booked
    # and put away. No-ops for a stock PO - there is no project whose inventory to keep it in.
    from .receive_decisions import create_decision_for_draft

    create_decision_for_draft(
        session,
        po,
        draft.id,
        total_quantity=sum(li["quantity_received"] for li in line_items_input),
    )

    _notify_submitted(session, draft, po)
    return draft


def get_receive_drafts(
    session: Session,
    status: ReceiveDraftStatus | None = None,
    po_id: uuid.UUID | None = None,
    created_by_user_id: str | None = None,
) -> list[tuple]:
    """Drafts with the PO they are against and the keep-or-ship decision they raised, newest first.

    The decision rides along since #499 because the approvals queue is filtered by it: a draft its
    creator answered SHIP_OUT is not the warehouse manager's to approve - the shipping request does
    that booking - and an unanswered one still is, with the fact that it is unanswered on the row.

    Returns pairs rather than drafts alone because every consumer renders the PO number and project
    beside the draft, and letting the converter walk a lazy `draft.purchase_order` would be one
    SELECT per row - the N+1 this codebase keeps paying for elsewhere.
    """
    from app.models.receive_decision import ReceiveDecision as ReceiveDecisionModel

    stmt = (
        select(ReceiveDraftModel, POModel, ReceiveDecisionModel)
        .join(POModel, POModel.id == ReceiveDraftModel.po_id)
        # Outer: a stock PO raises no decision at all, and drafts predating #499 have none either.
        .outerjoin(ReceiveDecisionModel, ReceiveDecisionModel.receive_draft_id == ReceiveDraftModel.id)
        .options(selectinload(ReceiveDraftModel.line_items))
        .order_by(ReceiveDraftModel.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(ReceiveDraftModel.status == status)
    if po_id is not None:
        stmt = stmt.where(ReceiveDraftModel.po_id == po_id)
    if created_by_user_id is not None:
        stmt = stmt.where(ReceiveDraftModel.created_by_user_id == created_by_user_id)
    return [(draft, po, decision) for draft, po, decision in session.execute(stmt).unique().all()]


def get_receive_draft(session: Session, draft_id: uuid.UUID):
    """One draft, with its PO and the keep-or-ship decision it raised (#499)."""
    from app.models.receive_decision import ReceiveDecision as ReceiveDecisionModel

    draft = _get_draft(session, draft_id)
    po = session.get(POModel, draft.po_id)
    decision = session.scalars(
        select(ReceiveDecisionModel).where(ReceiveDecisionModel.receive_draft_id == draft.id)
    ).first()
    return draft, po, decision


def count_pending_drafts(session: Session) -> int:
    """How many drafts are waiting on a manager - the approvals badge."""
    return int(
        session.scalar(
            select(func.count())
            .select_from(ReceiveDraftModel)
            .where(ReceiveDraftModel.status == ReceiveDraftStatus.PENDING_APPROVAL)
        )
        or 0
    )


def _assert_can_edit(draft: ReceiveDraftModel, actor_user_id: str, actor_is_manager: bool) -> None:
    if draft.status not in (ReceiveDraftStatus.PENDING_APPROVAL, ReceiveDraftStatus.REJECTED):
        raise InvalidStateTransitionError(
            f"A receive draft can only be edited while it is awaiting approval or rejected, got {draft.status.value}"
        )
    is_author = draft.created_by_user_id == actor_user_id
    if is_author:
        return
    if not actor_is_manager:
        raise ConflictError("Only the person who submitted this draft, or a Warehouse Manager, can edit it")
    if draft.status == ReceiveDraftStatus.REJECTED:
        # A rejected draft is back in the author's hands. A manager editing it there would be
        # answering their own rejection on somebody else's behalf.
        raise InvalidStateTransitionError(
            "This draft was rejected and is back with its author; they resubmit it, not a reviewer"
        )


def update_receive_draft(
    session: Session,
    draft_id: uuid.UUID,
    line_items_input: list[dict],
    actor_user_id: str,
    actor_is_manager: bool,
    warehouse_id: uuid.UUID | None = None,
) -> ReceiveDraftModel:
    """Rewrite what a draft says was counted.

    Validation runs against the AUTHOR's name, not the editor's: `received_by` belongs to whoever
    counted the hardware, and a manager correcting a quantity does not take that over.

    A None `warehouse_id` means "not being changed", not "clear it". The GraphQL input defaults it to
    null, so treating it as an assignment would let a caller sending only corrected quantities
    silently move the delivery to whatever `get_primary_warehouse_id` returns at approval - hardware
    booked into the wrong building with nothing reported.
    """
    draft = _get_draft(session, draft_id)
    _assert_can_edit(draft, actor_user_id, actor_is_manager)

    validate_receive_eligibility(session, draft.po_id, draft.created_by_name, line_items_input)
    po = (
        session.scalars(select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == draft.po_id))
        .unique()
        .first()
    )

    if warehouse_id is not None:
        draft.warehouse_id = warehouse_id
    _write_lines(session, draft, po, line_items_input)
    session.refresh(draft)
    return draft


def resubmit_receive_draft(session: Session, draft_id: uuid.UUID, actor_user_id: str) -> ReceiveDraftModel:
    """Send a rejected draft back to the queue. Author only - it is their count being restated."""
    draft = _get_draft(session, draft_id)
    if draft.status != ReceiveDraftStatus.REJECTED:
        raise InvalidStateTransitionError(f"Only a rejected draft can be resubmitted, got {draft.status.value}")
    if draft.created_by_user_id != actor_user_id:
        raise ConflictError("Only the person who submitted this draft can resubmit it")

    validate_receive_eligibility(session, draft.po_id, draft.created_by_name, _line_items_data(draft))

    draft.status = ReceiveDraftStatus.PENDING_APPROVAL
    draft.reviewed_by_user_id = None
    draft.reviewed_by_name = None
    draft.reviewed_at = None
    draft.rejection_reason = None
    session.flush()

    po = session.get(POModel, draft.po_id)
    _notify_submitted(session, draft, po)
    return draft


def reject_receive_draft(
    session: Session,
    draft_id: uuid.UUID,
    reason: str,
    reviewer_user_id: str,
    reviewer_name: str,
) -> ReceiveDraftModel:
    """Send a draft back to its author with a reason, which is required: "rejected" on its own tells
    the person who counted the truck nothing they can act on."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A rejection reason is required", field="reason")
    if len(reason) > MAX_REJECTION_REASON:
        raise ValidationError(f"A rejection reason must be {MAX_REJECTION_REASON} characters or fewer", field="reason")

    lock_rows(session, ReceiveDraftModel, [draft_id])
    draft = _get_draft(session, draft_id)
    if draft.status != ReceiveDraftStatus.PENDING_APPROVAL:
        raise InvalidStateTransitionError(f"Only a draft awaiting approval can be rejected, got {draft.status.value}")

    draft.status = ReceiveDraftStatus.REJECTED
    draft.reviewed_by_user_id = reviewer_user_id
    draft.reviewed_by_name = reviewer_name
    draft.reviewed_at = datetime.utcnow()
    draft.rejection_reason = reason
    session.flush()

    po = session.get(POModel, draft.po_id)
    if po.project_id is not None:
        notification_service.create_notification(
            session,
            project_id=po.project_id,
            recipient_role=draft.created_by_user_id,
            notification_type=NotificationType.RECEIVE_DRAFT_REJECTED,
            message=(
                f"For {draft.created_by_name}: {reviewer_name} sent back your receive against "
                f"PO {po.po_number} - {reason}"
            ),
        )
    return draft


def delete_receive_draft(
    session: Session,
    draft_id: uuid.UUID,
    actor_user_id: str,
    actor_is_manager: bool,
) -> None:
    """Throw away a count. Refused once approval has started, because from APPROVING onwards the
    draft is the only record of what a GP receipt is being posted for."""
    draft = _get_draft(session, draft_id)
    if draft.status in _IN_FLIGHT_STATUSES:
        raise InvalidStateTransitionError(f"A draft that has been approved cannot be deleted, got {draft.status.value}")
    if draft.created_by_user_id != actor_user_id and not actor_is_manager:
        raise ConflictError("Only the person who submitted this draft, or a Warehouse Manager, can delete it")
    session.delete(draft)


def _assert_no_conflicting_claim(session: Session, draft: ReceiveDraftModel) -> None:
    """Refuse a claim whose quantities cannot survive alongside drafts already mid-approval.

    Two drafts against the same PO line are legitimate (two deliveries, one PO), and each was checked
    against the PO's pending quantity when it was written. What neither can see is the other: if both
    are approved, the second one's units have nowhere to go, and by then GP holds a receipt Nexus will
    refuse to book - the split-brain the GP-first ordering exists to avoid.

    So the claim measures this draft against every OTHER draft that is APPROVING or APPROVED-but-not-
    yet-persisted (queued on the outbox). Drafts that already persisted are not counted: their units
    are in `POLineItem.received_quantity`, which the eligibility check reads directly.

    The PO lines are locked FOR UPDATE first, and that lock is what makes this a check rather than a
    guess. Two approvals racing on the same line each UPDATE a different draft row, so neither blocks
    the other, and neither has committed by the time it reads - under READ COMMITTED both would see
    the other as still PENDING and both would post a receipt. Locking the line they have in common
    serializes them. It is held only until the claim commits, which is before any relay call.
    """
    wanted: dict[uuid.UUID, int] = {}
    for li in draft.line_items:
        wanted[li.po_line_item_id] = wanted.get(li.po_line_item_id, 0) + li.quantity_received
    if not wanted:
        return
    lock_rows(session, POLineItemModel, list(wanted))

    rows = session.execute(
        select(
            ReceiveDraftLineItemModel.po_line_item_id,
            func.sum(ReceiveDraftLineItemModel.quantity_received),
        )
        .join(ReceiveDraftModel, ReceiveDraftModel.id == ReceiveDraftLineItemModel.receive_draft_id)
        .where(
            ReceiveDraftModel.po_id == draft.po_id,
            ReceiveDraftModel.id != draft.id,
            ReceiveDraftModel.status.in_(_IN_FLIGHT_STATUSES),
            ReceiveDraftModel.receive_record_id.is_(None),
            ReceiveDraftLineItemModel.po_line_item_id.in_(list(wanted)),
        )
        .group_by(ReceiveDraftLineItemModel.po_line_item_id)
    ).all()
    in_flight = {po_line_item_id: int(total or 0) for po_line_item_id, total in rows}
    if not in_flight:
        return

    poli_dict = {
        li.id: li for li in session.scalars(select(POLineItemModel).where(POLineItemModel.id.in_(list(wanted)))).all()
    }
    for poli_id, qty in wanted.items():
        claimed = in_flight.get(poli_id, 0)
        if not claimed:
            continue
        poli = poli_dict[poli_id]
        pending = poli.ordered_quantity - poli.received_quantity
        if qty + claimed > pending:
            raise ConflictError(
                f"Another receive of {claimed} {'unit' if claimed == 1 else 'units'} of "
                f"{poli.product_code} is already posting against this PO. Only {pending} "
                f"{'unit is' if pending == 1 else 'units are'} outstanding, so this draft would "
                f"over-receive it - wait for the other receive to land, then adjust this one."
            )


def claim_for_approval(
    session: Session,
    draft_id: uuid.UUID,
    reviewer_user_id: str,
    reviewer_name: str,
    idempotency_key: str,
) -> ApprovalContext:
    """Take exclusive ownership of a draft so the GP receipt can be posted for it.

    The claim is a status flip the caller commits BEFORE talking to the relay, because the relay call
    is a network round trip no database lock should span. Once it lands, a concurrent approver sees
    APPROVING and is refused; the caller that holds it either finishes (APPROVED) or releases it.

    A retry carrying the same key resumes rather than conflicting: the GP idempotency ledger will
    return the already-posted receipt, so re-entering this path is exactly what should happen after a
    dropped connection.
    """
    rowcount = session.execute(
        update(ReceiveDraftModel)
        .where(
            ReceiveDraftModel.id == draft_id,
            ReceiveDraftModel.status == ReceiveDraftStatus.PENDING_APPROVAL,
        )
        .values(
            status=ReceiveDraftStatus.APPROVING,
            reviewed_by_user_id=reviewer_user_id,
            reviewed_by_name=reviewer_name,
            reviewed_at=datetime.utcnow(),
            approval_idempotency_key=idempotency_key,
            rejection_reason=None,
            updated_at=datetime.utcnow(),
        )
    ).rowcount

    draft = _get_draft(session, draft_id)
    if rowcount == 0:
        if draft.status == ReceiveDraftStatus.APPROVING and draft.approval_idempotency_key == idempotency_key:
            # Our own interrupted approval, resuming. Fall through and hand back the context.
            pass
        elif draft.status == ReceiveDraftStatus.APPROVING:
            raise ConflictError(f"{draft.reviewed_by_name or 'Another reviewer'} is approving this draft right now")
        elif draft.status == ReceiveDraftStatus.APPROVED:
            raise ConflictError("This draft has already been approved")
        else:
            raise InvalidStateTransitionError(
                f"Only a draft awaiting approval can be approved, got {draft.status.value}"
            )
    else:
        _assert_no_conflicting_claim(session, draft)

    return ApprovalContext(
        draft_id=draft.id,
        po_id=draft.po_id,
        warehouse_id=draft.warehouse_id,
        author_name=draft.created_by_name,
        line_items_data=_line_items_data(draft),
    )


def release_approval_claim(session: Session, draft_id: uuid.UUID, idempotency_key: str) -> None:
    """Undo a claim that never reached GP, so the draft goes back in the queue instead of parking.

    Only releases a claim held under the same key: a claim somebody else took after ours failed is
    theirs, and stealing it back would be the very race the claim exists to prevent.
    """
    session.execute(
        update(ReceiveDraftModel)
        .where(
            ReceiveDraftModel.id == draft_id,
            ReceiveDraftModel.status == ReceiveDraftStatus.APPROVING,
            ReceiveDraftModel.approval_idempotency_key == idempotency_key,
        )
        .values(
            status=ReceiveDraftStatus.PENDING_APPROVAL,
            approval_idempotency_key=None,
            updated_at=datetime.utcnow(),
        )
    )


def mark_approved(
    session: Session,
    draft_id: uuid.UUID,
    *,
    receive_record_id: uuid.UUID | None = None,
    outbox_entry_id: uuid.UUID | None = None,
) -> ReceiveDraftModel | None:
    """Finish the approval, whichever way the GP write went.

    Idempotent, and it never nulls out a link a previous phase recorded: a queued approval stamps the
    outbox entry now and the receive record when the worker drains, and re-running either half must
    not erase the other. Returns None if the draft is gone, since a caller running inside the persist
    transaction has nothing useful to do about that.
    """
    draft = session.get(ReceiveDraftModel, draft_id)
    if draft is None:
        return None
    draft.status = ReceiveDraftStatus.APPROVED
    if receive_record_id is not None:
        draft.receive_record_id = receive_record_id
    if outbox_entry_id is not None:
        draft.approved_outbox_entry_id = outbox_entry_id
    session.flush()
    return draft
