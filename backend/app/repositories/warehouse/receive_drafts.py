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
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import NotificationType, ReceiveDraftStatus
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receive_draft import ReceiveDraft as ReceiveDraftModel
from app.models.receive_draft import ReceiveDraftLineItem as ReceiveDraftLineItemModel
from app.models.warehouse import Warehouse
from app.services import notification_service
from app.services.locking import lock_rows
from app.services.relay_gateway import DEFAULT_TIMEOUT_SECONDS as RELAY_CALL_TIMEOUT_SECONDS
from app.status_labels import REFRESH_HINT, status_label

from .receiving import validate_receive_eligibility

# The statuses that hold a claim on a PO line's pending quantity without having consumed it yet.
# APPROVING is mid-relay; APPROVED with no receive record is queued on the GP outbox. Both will
# eventually book units against the PO, so a third draft must be measured against them.
_IN_FLIGHT_STATUSES = (ReceiveDraftStatus.APPROVING, ReceiveDraftStatus.APPROVED)

MAX_REJECTION_REASON = 1000

# #1945: how long an approval attempt may still be running after it took or resumed its claim: the receipt
# relay call gives up at its timeout, and the margin covers the re-check before it and the persist after.
# A held approval is not released inside it - the attempt may be about to book, or to post, the receipt.
APPROVAL_ATTEMPT_SECONDS = RELAY_CALL_TIMEOUT_SECONDS + 60
MAX_RECEIVE_NOTES = 2000


def _clean_notes(notes: str | None) -> str | None:
    """Strip and bound a receive remark. Empty collapses to None so the columns stay null-or-text."""
    cleaned = (notes or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > MAX_RECEIVE_NOTES:
        raise ValidationError(f"Notes must be {MAX_RECEIVE_NOTES} characters or fewer", field="notes")
    return cleaned


class ApprovalContext:
    """What the approve resolver needs after the claim, in the shape the GP pipeline already speaks.

    Deliberately a plain object built inside the claim transaction rather than the ORM draft: the
    resolver hands `line_items_data` straight to `_prepare_create_receive` and, when the relay is
    down, to the outbox's JSON `persist_context`. Passing a detached ORM row instead would mean
    re-opening a session in the middle of an async resolver just to read attributes.
    """

    __slots__ = ("draft_id", "po_id", "warehouse_id", "author_name", "line_items_data", "resumed")

    def __init__(self, draft_id, po_id, warehouse_id, author_name, line_items_data, resumed=False):
        self.draft_id = draft_id
        self.po_id = po_id
        self.warehouse_id = warehouse_id
        self.author_name = author_name
        self.line_items_data = line_items_data
        # #1945: the draft was already APPROVING under this key, so an earlier attempt may have sent its
        # receipt to GP. The resolver must not let go of the claim on a refusal it raises itself.
        self.resumed = resumed


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


def _lock_draft(session: Session, draft_id: uuid.UUID) -> ReceiveDraftModel:
    """Row-lock a draft and return it, fresh (#1195), for writers that check its status and then write.

    Unlocked, an approval claim committing between the read and the write slips underneath: an edit
    rewrites the lines after GP was handed the old counts, a delete removes the draft a receipt is
    posting against. `populate_existing` matters because the draft is usually already in the session
    from the tenancy check, and a plain read would hand back that copy instead of what the lock holds.
    """
    lock_rows(session, ReceiveDraftModel, [draft_id])
    stmt = (
        select(ReceiveDraftModel)
        .options(selectinload(ReceiveDraftModel.line_items))
        .where(ReceiveDraftModel.id == draft_id)
        .execution_options(populate_existing=True)
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
        # So deleting the draft withdraws this notice (#1898).
        receive_draft_id=draft.id,
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


def _draft_for_create_key(session: Session, idempotency_key: str | None) -> ReceiveDraftModel | None:
    """The draft a submission with this create key already wrote, if any (fresh, not cached)."""
    if not idempotency_key:
        return None
    return session.scalars(
        select(ReceiveDraftModel)
        .options(selectinload(ReceiveDraftModel.line_items))
        .where(ReceiveDraftModel.create_idempotency_key == idempotency_key)
        .execution_options(populate_existing=True)
    ).first()


def _replayed_on_this_po(existing: ReceiveDraftModel, po_id: uuid.UUID) -> ReceiveDraftModel:
    """A create key's draft, handed back only to a retry on the PO it was written for (#1871). The key is
    global, so one reused on another PO used to answer with that PO's draft - another purchase order's
    count, possibly another company's."""
    if existing.po_id != po_id:
        raise ValidationError("This draft key was already used on another purchase order.", field="idempotency_key")
    return existing


def _assert_no_pending_draft(
    session: Session,
    po_id: uuid.UUID,
    *,
    exclude_draft_id: uuid.UUID | None = None,
) -> None:
    """One counted delivery per PO at a time (#641).

    This used to be a warning on the frontend, on the reading that two deliveries against one PO
    before the first is approved are legitimate. They are - but the second submission is almost never
    that; it is somebody re-counting a delivery that is already in the approvals queue, and until now
    nothing said so. Now the pending draft holds the PO out of the receiving queue
    (`_pending_receive_draft_exists`) and holds this door shut, so the state is tracked in one place
    rather than described in an alert.

    The PO row is locked FOR UPDATE first: without it two submissions racing each other both read
    "nothing pending" under READ COMMITTED and both write a draft. An idempotent retry never reaches
    here - the create key short-circuits above it - so the lock only ever serialises genuinely
    distinct submissions.
    """
    lock_rows(session, POModel, [po_id])
    stmt = select(ReceiveDraftModel.id).where(
        ReceiveDraftModel.po_id == po_id,
        ReceiveDraftModel.status == ReceiveDraftStatus.PENDING_APPROVAL,
    )
    if exclude_draft_id is not None:
        stmt = stmt.where(ReceiveDraftModel.id != exclude_draft_id)
    if session.scalars(stmt).first() is not None:
        raise ConflictError(
            "A receive for this PO is already pending approval - these quantities are awaiting "
            "review. The PO comes back to the receiving queue once a Warehouse Manager approves or "
            "rejects it."
        )


def _assert_draft_warehouse(session: Session, warehouse_id: uuid.UUID | None, po) -> None:
    """A draft's chosen warehouse is active (#1374) and the PO's own company's building (#1375), so the
    approval never books a delivery into a retired building or another tenant's. None means "not
    chosen" - the approval falls back to the PO company's primary - and is left alone."""
    if warehouse_id is None:
        return
    from app.repositories import warehouse_admin_repository

    warehouse_admin_repository.assert_usable_destination(
        session, warehouse_id, company=po.company if po is not None else None, field="warehouse_id"
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
    notes: str | None = None,
) -> ReceiveDraftModel:
    """Record a counted delivery for a Warehouse Manager to approve.

    Validates with the SAME rules the GP pre-flight uses, so an over-receive or a receive against a
    closed PO is refused in front of the person holding the packing slip rather than surfacing hours
    later to whoever opens the queue. Approval re-validates anyway - the world can move underneath a
    draft - but a draft nobody could ever approve is not worth creating.

    Refused outright if the PO already has a draft awaiting approval (#641) - see
    `_assert_no_pending_draft`.
    """
    _validate_packing_slip(session, po_id, packing_slip_document_id)

    existing = _draft_for_create_key(session, idempotency_key)
    if existing is not None:
        return _replayed_on_this_po(existing, po_id)

    if idempotency_key:
        # #1402: a retry that overlaps the first submit passes the unlocked check above, then waits on
        # the PO lock while the first commits. Look again under that lock, so the retry gets the draft
        # its own first attempt wrote rather than a conflict with itself.
        lock_rows(session, POModel, [po_id])
        existing = _draft_for_create_key(session, idempotency_key)
        if existing is not None:
            return _replayed_on_this_po(existing, po_id)

    # After the idempotency short-circuit, never before it: a retry of the submission that wrote the
    # pending draft must get that draft back, not a conflict with itself.
    _assert_no_pending_draft(session, po_id)

    validate_receive_eligibility(session, po_id, author_name, line_items_input)

    po = (
        session.scalars(select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == po_id))
        .unique()
        .first()
    )
    _assert_draft_warehouse(session, warehouse_id, po)

    # #1344: a draft with no warehouse falls back to the company's default building at approval;
    # with no active building at all that approval can never succeed, so refuse the draft now,
    # in front of the person counting, rather than after.
    if warehouse_id is None and po is not None:
        has_active_warehouse = session.scalar(
            select(Warehouse.id).where(Warehouse.company == po.company, Warehouse.is_active.is_(True)).limit(1)
        )
        if has_active_warehouse is None:
            raise ValidationError(
                "No active warehouse to receive into. A Tenant Owner must add one under Tenant Owner -> "
                "Warehouses before hardware can be received.",
                field="warehouse_id",
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
        notes=_clean_notes(notes),
    )
    session.add(draft)
    session.flush()

    _write_lines(session, draft, po, line_items_input)
    session.refresh(draft)

    _notify_submitted(session, draft, po)
    return draft


def get_receive_drafts(
    session: Session,
    status: ReceiveDraftStatus | None = None,
    po_id: uuid.UUID | None = None,
    created_by_user_id: str | None = None,
    *,
    company: str | None = None,
    statuses: list[ReceiveDraftStatus] | None = None,
    held_on_gp: bool = False,
) -> list[tuple]:
    """Drafts with the PO they are against, newest first.

    Returns pairs rather than drafts alone because every consumer renders the PO number and project
    beside the draft, and letting the converter walk a lazy `draft.purchase_order` would be one
    SELECT per row - the N+1 this codebase keeps paying for elsewhere.

    `statuses` filters to any of a set (#1889): my drafts shows only the rejected and the waiting, and
    an author's approved drafts only accumulate, so they are never read for it. Additive with `status`.
    `held_on_gp` keeps the approvals a manager may have to release after checking GP (#1945).
    """
    stmt = (
        select(ReceiveDraftModel, POModel)
        .join(POModel, POModel.id == ReceiveDraftModel.po_id)
        .options(selectinload(ReceiveDraftModel.line_items))
        .order_by(ReceiveDraftModel.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(ReceiveDraftModel.status == status)
    if statuses:
        stmt = stmt.where(ReceiveDraftModel.status.in_(statuses))
    if held_on_gp:
        # #1945: the approvals held on GP - claimed, or approved with nothing booked behind a queued receipt
        # that stopped. Narrowed here, settled by `drafts_with_stopped_receipts` below.
        stmt = stmt.where(
            ReceiveDraftModel.status.in_(_IN_FLIGHT_STATUSES), ReceiveDraftModel.receive_record_id.is_(None)
        )
    if po_id is not None:
        stmt = stmt.where(ReceiveDraftModel.po_id == po_id)
    if created_by_user_id is not None:
        stmt = stmt.where(ReceiveDraftModel.created_by_user_id == created_by_user_id)
    if company is not None:
        # Through the PO, which is already joined: a draft has a nullable warehouse but always a PO,
        # and the PO is what the receive is for.
        stmt = stmt.where(POModel.company == company)
    rows = [(draft, po) for draft, po in session.execute(stmt).unique().all()]
    if held_on_gp:
        stopped = drafts_with_stopped_receipts(session, [draft for draft, _ in rows])
        rows = [(d, po) for d, po in rows if d.status == ReceiveDraftStatus.APPROVING or d.id in stopped]
    return rows


def get_receive_draft(session: Session, draft_id: uuid.UUID):
    """One draft, with its PO."""
    draft = _get_draft(session, draft_id)
    po = session.get(POModel, draft.po_id)
    return draft, po


def count_pending_drafts(session: Session, *, company: str | None = None) -> int:
    """How many drafts are waiting on a manager - the approvals badge, within the caller's
    company (#637)."""
    stmt = (
        select(func.count())
        .select_from(ReceiveDraftModel)
        .where(ReceiveDraftModel.status == ReceiveDraftStatus.PENDING_APPROVAL)
    )
    if company is not None:
        stmt = stmt.join(POModel, POModel.id == ReceiveDraftModel.po_id).where(POModel.company == company)
    return int(session.scalar(stmt) or 0)


def _assert_can_edit(draft: ReceiveDraftModel, actor_user_id: str, actor_is_manager: bool) -> None:
    if draft.status not in (ReceiveDraftStatus.PENDING_APPROVAL, ReceiveDraftStatus.REJECTED):
        raise InvalidStateTransitionError(
            f"A receive draft can only be edited while it is awaiting approval or rejected; this one is "
            f"{status_label(draft.status)}. {REFRESH_HINT}"
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
    notes: str | None = None,
    expected_updated_at: datetime | None = None,
) -> ReceiveDraftModel:
    """Rewrite what a draft says was counted.

    Validation runs against the AUTHOR's name, not the editor's: `received_by` belongs to whoever
    counted the hardware, and a manager correcting a quantity does not take that over.

    A None `warehouse_id` means "not being changed", not "clear it". The GraphQL input defaults it to
    null, so treating it as an assignment would let a caller sending only corrected quantities
    silently move the delivery to whatever `get_primary_warehouse_id` returns at approval - hardware
    booked into the wrong building with nothing reported.

    `notes` follows the same reading: None leaves the remark alone, an empty string clears it.

    `expected_updated_at` (#1497) is the draft's updated_at as the editor loaded it. Checked under the
    lock, so an edit made over a newer one - a manager's correction, the author's own second tab - is
    refused rather than silently replacing it. None (an older client) skips the check.
    """
    draft = _lock_draft(session, draft_id)
    _assert_unchanged_since(draft, expected_updated_at)
    _assert_can_edit(draft, actor_user_id, actor_is_manager)

    validate_receive_eligibility(session, draft.po_id, draft.created_by_name, line_items_input)
    po = (
        session.scalars(select(POModel).options(selectinload(POModel.line_items)).where(POModel.id == draft.po_id))
        .unique()
        .first()
    )

    if warehouse_id is not None:
        _assert_draft_warehouse(session, warehouse_id, po)
        draft.warehouse_id = warehouse_id
    if notes is not None:
        draft.notes = _clean_notes(notes)
    _write_lines(session, draft, po, line_items_input)
    # #982: a rewrite that only touches the line rows leaves the draft row as it was, so its own
    # updated_at would keep the first count's time; the review reads it as when the count last changed.
    # #1497: it is also the version an edit or approval is checked against, so it must move on every
    # edit - strictly later than the last, even when two land inside one tick of a coarse clock.
    draft.updated_at = max(datetime.utcnow(), draft.updated_at + timedelta(microseconds=1))
    session.flush()
    session.refresh(draft)
    return draft


def resubmit_receive_draft(session: Session, draft_id: uuid.UUID, actor_user_id: str) -> ReceiveDraftModel:
    """Send a rejected draft back to the queue. Author only - it is their count being restated."""
    draft = _lock_draft(session, draft_id)
    if draft.status != ReceiveDraftStatus.REJECTED:
        raise InvalidStateTransitionError(
            f"Only a rejected draft can be resubmitted; this one is {status_label(draft.status)}. {REFRESH_HINT}"
        )
    if draft.created_by_user_id != actor_user_id:
        raise ConflictError("Only the person who submitted this draft can resubmit it")

    # A resubmission is a submission: it puts a draft back into PENDING_APPROVAL, so it is held to the
    # same one-per-PO rule a fresh count is (#641). Somebody counted this delivery again while the
    # rejection sat unanswered, and two pending drafts on one PO is the state that rule exists to
    # prevent.
    _assert_no_pending_draft(session, draft.po_id, exclude_draft_id=draft.id)

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

    draft = _lock_draft(session, draft_id)
    if draft.status != ReceiveDraftStatus.PENDING_APPROVAL:
        raise InvalidStateTransitionError(
            f"Only a draft awaiting approval can be rejected; this one is {status_label(draft.status)}. {REFRESH_HINT}"
        )

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
            recipient_role=None,
            recipient_user_id=draft.created_by_user_id,
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
) -> str | None:
    """Throw away a count. Refused once approval has started, because from APPROVING onwards the
    draft is the only record of what a GP receipt is being posted for.

    #1048: the packing slip pinned to the count goes with it, unless another draft - pending, sent
    back or approved, so a posted receipt too - names the same slip; otherwise a PO collects slips for
    counts that never happened. Returns the slip's storage key for the caller to remove once the
    delete has committed, or None when no slip was removed.
    """
    from app.models.purchase_order import PODocument

    draft = _lock_draft(session, draft_id)
    if draft.status in _IN_FLIGHT_STATUSES:
        raise InvalidStateTransitionError(
            f"An approved draft cannot be deleted; this one is {status_label(draft.status)}. {REFRESH_HINT}"
        )
    if draft.created_by_user_id != actor_user_id and not actor_is_manager:
        raise ConflictError("Only the person who submitted this draft, or a Warehouse Manager, can delete it")
    slip_id = draft.packing_slip_document_id
    # #1898: its waiting-for-approval notice goes with it, or every manager's bell keeps a draft the
    # queue no longer holds.
    notification_service.withdraw_receive_draft_submitted(session, draft.id)
    session.delete(draft)
    session.flush()
    if slip_id is None:
        return None
    shared = session.scalar(
        select(ReceiveDraftModel.id).where(ReceiveDraftModel.packing_slip_document_id == slip_id).limit(1)
    )
    slip = session.get(PODocument, slip_id) if shared is None else None
    if slip is None:
        return None
    s3_key = slip.s3_key
    session.delete(slip)
    return s3_key


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
            ReceiveDraftModel.approved_outbox_entry_id,
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
        .group_by(ReceiveDraftLineItemModel.po_line_item_id, ReceiveDraftModel.approved_outbox_entry_id)
    ).all()
    # #1298: a queued approval whose receipt never reached GP holds nothing, even when it is still
    # APPROVED because it finished before drafts were released on that path.
    from app.models.gp_outbox import GpWriteOutbox

    entry_ids = {entry_id for _, entry_id, _ in rows if entry_id is not None}
    dead_entries = {
        e.id
        for e in (
            session.scalars(select(GpWriteOutbox).where(GpWriteOutbox.id.in_(entry_ids))).all() if entry_ids else []
        )
        if outbox_entry_never_reached_gp(session, e)
    }
    in_flight: dict[uuid.UUID, int] = {}
    for po_line_item_id, entry_id, total in rows:
        if entry_id in dead_entries:
            continue
        in_flight[po_line_item_id] = in_flight.get(po_line_item_id, 0) + int(total or 0)

    # Read under the lock, refreshed: a receive that persisted since this draft was written has moved
    # received_quantity, and this draft's own total is checked against that even with nothing else in
    # flight (#1120) - it used to return early here and trust the check made when it was written.
    poli_dict = {
        li.id: li
        for li in session.scalars(
            select(POLineItemModel)
            .where(POLineItemModel.id.in_(list(wanted)))
            .execution_options(populate_existing=True)
        ).all()
    }
    for poli_id, qty in wanted.items():
        claimed = in_flight.get(poli_id, 0)
        poli = poli_dict[poli_id]
        pending = poli.ordered_quantity - poli.received_quantity
        if not claimed and qty > pending:
            raise ConflictError(
                f"This draft receives {qty} of {poli.product_code}, but only {pending} "
                f"{'unit is' if pending == 1 else 'units are'} still outstanding on this PO. "
                "Adjust the count to what is outstanding."
            )
        if claimed and qty + claimed > pending:
            raise ConflictError(
                f"Another receive of {claimed} {'unit' if claimed == 1 else 'units'} of "
                f"{poli.product_code} is already posting against this PO. Only {pending} "
                f"{'unit is' if pending == 1 else 'units are'} outstanding, so this draft would "
                f"over-receive it - wait for the other receive to land, then adjust this one."
            )


COUNT_CHANGED_MESSAGE = "This count changed since you opened it - review the new numbers before going on."
# The field the refusal names, so a client can tell it from other conflicts without matching text.
COUNT_CHANGED_FIELD = "expected_updated_at"


def _assert_unchanged_since(draft: ReceiveDraftModel, expected_updated_at: datetime | None) -> None:
    """Refuse a write based on an older view of the draft (#1497).

    updated_at moves on every change to the draft (#982 stamps it on a line rewrite; the column's
    onupdate covers the rest), and it round-trips GraphQL exactly - a naive datetime serialised with its
    microseconds and parsed back the same - so plain equality is the right comparison.
    """
    if expected_updated_at is None:
        return
    if draft.updated_at != expected_updated_at.replace(tzinfo=None):
        raise ConflictError(COUNT_CHANGED_MESSAGE, field=COUNT_CHANGED_FIELD)


# #1963: what a fresh approval sent under a spent key is refused with. The approval that key belonged to has
# ended - its queued receipt cancelled or failed, or GP's answer held after its claim was released - and the
# draft came back for review since. Nothing was sent this time; the client mints a new key for the next press.
APPROVAL_KEY_SPENT = (
    "This approval was sent under the key of an earlier approval of this draft, which has since ended. "
    "Nothing was sent to GP this time; approve it again to send it as a new approval."
)


def approval_key_spent(session: Session, key: str) -> bool:
    """Whether a receipt approval was already written under `key` (#1963): queued on the GP write queue, or
    answered by GP into the ledger. Only a resume - the draft still APPROVING under the key - may carry such
    a key. A fresh claim with one would relink the dead queued row (its Retry then posting the count as it
    was before the review) or book the ledger's answer, a receipt GP held when the approval was let go and
    that may since have been reversed there. A key that only ever met a refusal (the claim released before
    anything was recorded) is not spent, so the same press retried after a dropped connection still works."""
    from app.models.gp_outbox import GpWriteOutbox
    from app.models.gp_write import GpWriteIdempotency

    if session.get(GpWriteIdempotency, key) is not None:
        return True
    return session.scalar(select(GpWriteOutbox.id).where(GpWriteOutbox.idempotency_key == key).limit(1)) is not None


def claim_for_approval(
    session: Session,
    draft_id: uuid.UUID,
    reviewer_user_id: str,
    reviewer_name: str,
    idempotency_key: str,
    expected_updated_at: datetime | None = None,
) -> ApprovalContext:
    """Take exclusive ownership of a draft so the GP receipt can be posted for it.

    The claim is a status flip the caller commits BEFORE talking to the relay, because the relay call
    is a network round trip no database lock should span. Once it lands, a concurrent approver sees
    APPROVING and is refused; the caller that holds it either finishes (APPROVED) or releases it.

    A retry carrying the same key resumes rather than conflicting: the GP idempotency ledger will
    return the already-posted receipt, so re-entering this path is exactly what should happen after a
    dropped connection. That resume - the draft APPROVING under the key - is the only way back into an
    approval (`ApprovalContext.resumed`). A draft awaiting approval is a fresh one, and its key must be
    unspent (#1963, `approval_key_spent`).

    `expected_updated_at` (#1497) is the draft's updated_at as the reviewer saw it. It is part of the
    claim's own WHERE, so an edit can't land between a check and the claim: a count changed since the
    review is refused and stays pending, and GP never receives numbers nobody reviewed. A same-key
    resume is not re-checked: GP may already hold that receipt, and nothing can edit a claimed draft.
    """
    conditions = [
        ReceiveDraftModel.id == draft_id,
        ReceiveDraftModel.status == ReceiveDraftStatus.PENDING_APPROVAL,
    ]
    if expected_updated_at is not None:
        conditions.append(ReceiveDraftModel.updated_at == expected_updated_at.replace(tzinfo=None))
    rowcount = session.execute(
        update(ReceiveDraftModel)
        .where(*conditions)
        .values(
            status=ReceiveDraftStatus.APPROVING,
            reviewed_by_user_id=reviewer_user_id,
            reviewed_by_name=reviewer_name,
            reviewed_at=datetime.utcnow(),
            approval_idempotency_key=idempotency_key,
            rejection_reason=None,
            # #1497: held, not stamped - the column's onupdate would otherwise move it. The claim
            # changes no count, and a claim released after a GP failure must leave the version the
            # reviewer holds intact, or their retry would be refused as a changed count.
            updated_at=ReceiveDraftModel.updated_at,
        )
    ).rowcount

    draft = _get_draft(session, draft_id)
    resumed = False
    if rowcount == 0:
        if draft.status == ReceiveDraftStatus.APPROVING and draft.approval_idempotency_key == idempotency_key:
            # Our own interrupted approval, resuming. Fall through and hand back the context. #1945: the
            # claim is stamped again, so a release waits out this attempt as it would a fresh one.
            resumed = True
            session.execute(
                update(ReceiveDraftModel)
                .where(ReceiveDraftModel.id == draft_id)
                # Held, as the claim holds it (#1497): the resume changes no count.
                .values(reviewed_at=datetime.utcnow(), updated_at=ReceiveDraftModel.updated_at)
            )
        elif draft.status == ReceiveDraftStatus.APPROVING:
            raise ConflictError(f"{draft.reviewed_by_name or 'Another reviewer'} is approving this draft right now")
        elif draft.status == ReceiveDraftStatus.APPROVED:
            raise ConflictError("This draft has already been approved")
        elif draft.status == ReceiveDraftStatus.PENDING_APPROVAL:
            # Still pending, so only the version condition can have missed: it changed since review.
            raise ConflictError(COUNT_CHANGED_MESSAGE, field=COUNT_CHANGED_FIELD)
        else:
            raise InvalidStateTransitionError(
                f"Only a draft awaiting approval can be approved; this one is "
                f"{status_label(draft.status)}. {REFRESH_HINT}"
            )
    else:
        # #1963: a fresh claim is a new approval, and only a key nothing has been written under may start
        # one. Refused, the claim this transaction just took is rolled back with it: the draft stays pending.
        if approval_key_spent(session, idempotency_key):
            raise ConflictError(APPROVAL_KEY_SPENT, field="idempotency_key")
        _assert_no_conflicting_claim(session, draft)
        # #1401: the warehouse was checked when the draft was saved, but it can be retired or moved to
        # another company since. Re-checked on a fresh claim, before the caller commits it and before
        # anything reaches GP - live or queued - so a refusal leaves the draft pending and GP untouched.
        # A same-key resume is not re-checked: GP may already hold that receipt.
        _assert_draft_warehouse(session, draft.warehouse_id, session.get(POModel, draft.po_id))

    return ApprovalContext(
        draft_id=draft.id,
        po_id=draft.po_id,
        warehouse_id=draft.warehouse_id,
        author_name=draft.created_by_name,
        line_items_data=_line_items_data(draft),
        resumed=resumed,
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
            # #1497: held for the same reason as the claim - releasing it changes no count.
            updated_at=ReceiveDraftModel.updated_at,
        )
    )


def release_held_approval(session: Session, draft_id: uuid.UUID, manager_name: str) -> ReceiveDraftModel:
    """Let go of an approval claim GP may have taken, once a manager has checked GP holds no receipt (#1945).

    A resumed approval refused on its re-check keeps its claim, because the attempt before it may have
    posted the receipt, and nothing else released an APPROVING draft: it sat claimed for good. Only a
    person can answer the question the claim is guarding, by looking in GP, so only a manager's word lets
    it go. Refused while the ledger holds GP's answer for the claim's key: GP took that receipt, and the
    same-key retry is what books it.

    So is an APPROVED draft with nothing booked whose queued receipt ended - cancelled, or failed - without
    an answer from GP. One that may be in GP never hands its draft back on its own (#1849), so the draft
    stayed approved for good and its units blocked every re-count (`_assert_no_conflicting_claim`)."""
    from app.models.gp_outbox import GpWriteOutbox
    from app.models.gp_write import GpWriteIdempotency

    # The queued row's lock before the draft's, the order the outbox's own release takes them in.
    seen = session.get(ReceiveDraftModel, draft_id)
    entry = None
    if seen is not None and seen.approved_outbox_entry_id is not None:
        entry = session.get(GpWriteOutbox, seen.approved_outbox_entry_id, with_for_update=True, populate_existing=True)
    draft = _lock_draft(session, draft_id)
    if draft.receive_record_id is not None or draft.status not in _IN_FLIGHT_STATUSES:
        raise InvalidStateTransitionError(
            f"Only an approval still held on GP can be released; this draft is {status_label(draft.status)}. "
            f"{REFRESH_HINT}"
        )
    key = draft.approval_idempotency_key
    if draft.status == ReceiveDraftStatus.APPROVING and approval_attempt_may_be_running(draft, datetime.utcnow()):
        # #1945: a second manager released a claim while the first's relay call was still out, and the
        # receipt that call posted then had no claim to book against.
        raise ConflictError(
            "An approval attempt on this draft may still be posting the receipt to GP. Wait a couple of "
            "minutes, check GP again, then release it."
        )
    if draft.status == ReceiveDraftStatus.APPROVED:
        if entry is None or entry.id != draft.approved_outbox_entry_id:
            raise InvalidStateTransitionError(
                f"Only an approval still held on GP can be released; this draft is approved. {REFRESH_HINT}"
            )
        if entry.status not in ("CANCELLED", "FAILED"):
            raise ConflictError(
                "This draft's GP receipt is still queued, so the approval can't be released. It books itself "
                "when the receipt posts."
            )
        key = entry.idempotency_key
    ledger = session.get(GpWriteIdempotency, key) if key else None
    if ledger is not None and ledger.relay_result is not None:
        raise ConflictError(
            "GP already took this receipt, so the approval can't be released. Retry posting to book it here."
        )
    draft.status = ReceiveDraftStatus.PENDING_APPROVAL
    draft.approval_idempotency_key = None
    # A queued row released from is left as it ended; its Retry is refused, as the draft is no longer its.
    draft.approved_outbox_entry_id = None
    draft.reviewed_by_user_id = None
    draft.reviewed_by_name = None
    draft.reviewed_at = None
    draft.rejection_reason = (
        f"Back for review: {manager_name} checked GP and released the held approval, as no receipt was posted"
    )
    session.flush()
    return draft


def approval_attempt_may_be_running(draft: ReceiveDraftModel, now: datetime) -> bool:
    """Whether the attempt holding an APPROVING draft's claim may still be running (#1945)."""
    return draft.reviewed_at is not None and draft.reviewed_at > now - timedelta(seconds=APPROVAL_ATTEMPT_SECONDS)


def approval_releasable_at(draft: ReceiveDraftModel) -> datetime | None:
    """When an APPROVING draft's claim has outlived any attempt that took it, so it may be released."""
    if draft.status != ReceiveDraftStatus.APPROVING or draft.reviewed_at is None:
        return None
    return draft.reviewed_at + timedelta(seconds=APPROVAL_ATTEMPT_SECONDS)


# #1945: what the persist and the queueing refuse an attempt whose claim was released, and maybe re-claimed,
# while it was out at GP. The code is the one the review modal reads as "GP may hold this receipt".
APPROVAL_RELEASED_MEANWHILE = (
    "This approval was released while the attempt was still out at GP, so its receipt was not booked here"
)


def approval_still_held(session: Session, draft_id: uuid.UUID, key: str) -> bool:
    """Whether the draft is still this attempt's, under its row lock: claimed under `key` (APPROVING), or
    approved under it with its receipt queued (APPROVED), and nothing booked (#1945). A manager may release
    a claim while its attempt is out at GP, and someone may claim the draft again; the late attempt must
    not book over that, or link its queued receipt to it."""
    lock_rows(session, ReceiveDraftModel, [draft_id])
    draft = session.get(ReceiveDraftModel, draft_id, populate_existing=True)
    return (
        draft is not None
        and draft.status in _IN_FLIGHT_STATUSES
        and draft.approval_idempotency_key == key
        and draft.receive_record_id is None
    )


def drafts_with_stopped_receipts(session: Session, drafts) -> set[uuid.UUID]:
    """The approved drafts, of `drafts`, whose queued receipt ended - cancelled, or failed - with no answer
    from GP and nothing booked (#1945): the ones a manager who checked GP can release. One read for the lot."""
    from app.models.gp_outbox import GpWriteOutbox
    from app.repositories import gp_outbox_repository

    queued = {
        d.approved_outbox_entry_id: d.id
        for d in drafts
        if d.status == ReceiveDraftStatus.APPROVED
        and d.receive_record_id is None
        and d.approved_outbox_entry_id is not None
    }
    if not queued:
        return set()
    entries = list(
        session.scalars(
            select(GpWriteOutbox).where(
                GpWriteOutbox.id.in_(list(queued)), GpWriteOutbox.status.in_(("CANCELLED", "FAILED"))
            )
        ).all()
    )
    ledgers = gp_outbox_repository.ledgers_for(session, entries)
    return {
        queued[e.id]
        for e in entries
        if (ledger := ledgers.get(e.idempotency_key)) is None or ledger.relay_result is None
    }


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


# Failure kinds that say GP refused or never received the receipt. "ambiguous" (the job was on the
# wire when the link died) and "persist_failed" (GP committed, Nexus refused it) are deliberately
# absent: GP may hold those receipts, so their draft must stay put for a person to reconcile.
_NEVER_REACHED_GP_KINDS = ("gp_rejected", "exhausted")


def _refused_after_its_key_was_looked_up(entry) -> bool:
    from app.repositories import gp_outbox_repository

    return (
        entry.status == "FAILED"
        and entry.failure_kind == "gp_rejected"
        and gp_outbox_repository.retry_is_safe(entry.relay_op, entry.payload)
    )


def outbox_entry_never_reached_gp(session: Session, entry) -> bool:
    """True when a queued receipt's outbox row is finished and GP never committed it (#1298).

    A row that may be in GP (#1849) never qualifies. A cancelled row qualifies unless it had already
    failed ambiguously or after GP committed; a failed row only for the kinds above. Either way the GP
    idempotency ledger has the last word: a recorded relay result means GP answered with a receipt,
    whatever the row says now."""
    if entry is None or entry.op != "create_receive":
        return False
    # #1849: an earlier attempt may have left the receipt in GP under this row's key, whatever the row's
    # last outcome says. Released, the draft would be approved under a new key and posted a second time.
    # Except a keyed receipt GP then refused: the relay looks the key up before anything else, so a
    # refusal after that lookup says GP holds no receipt under it.
    if entry.maybe_in_gp and not _refused_after_its_key_was_looked_up(entry):
        return False
    if entry.status == "CANCELLED":
        if entry.failure_kind not in (None, *_NEVER_REACHED_GP_KINDS):
            return False
    elif not (entry.status == "FAILED" and entry.failure_kind in _NEVER_REACHED_GP_KINDS):
        return False
    from app.models.gp_write import GpWriteIdempotency

    ledger = session.get(GpWriteIdempotency, entry.idempotency_key)
    return ledger is None or ledger.relay_result is None


def release_draft_for_outbox_entry(session: Session, entry) -> ReceiveDraftModel | None:
    """Send a queued approval's draft back for review when its receipt never reached GP (#1298).

    Without this the draft stays APPROVED with no receive record for good: it counts as in flight
    against its PO lines (so a fresh receive of them is refused as "already posting"), and it can be
    neither deleted nor resubmitted. Called from the outbox's terminal transitions; a no-op for any
    row that is not a never-committed receipt, or whose draft has already moved on."""
    if not outbox_entry_never_reached_gp(session, entry):
        return None
    draft = session.scalars(
        select(ReceiveDraftModel)
        .where(
            ReceiveDraftModel.approved_outbox_entry_id == entry.id,
            ReceiveDraftModel.status == ReceiveDraftStatus.APPROVED,
            ReceiveDraftModel.receive_record_id.is_(None),
        )
        .with_for_update()
    ).first()
    if draft is None:
        return None
    why = (
        "the queued GP receipt was cancelled"
        if entry.status == "CANCELLED"
        else f"GP did not take the queued receipt: {entry.last_error or 'unknown error'}"
    )
    draft.status = ReceiveDraftStatus.PENDING_APPROVAL
    draft.approved_outbox_entry_id = None
    draft.approval_idempotency_key = None
    draft.reviewed_by_user_id = None
    draft.reviewed_by_name = None
    draft.reviewed_at = None
    draft.rejection_reason = f"Back for review: {why}"
    session.flush()

    po = session.get(POModel, draft.po_id)
    if po is not None and po.project_id is not None:
        notification_service.create_notification(
            session,
            project_id=po.project_id,
            recipient_role=None,
            recipient_user_id=draft.created_by_user_id,
            notification_type=NotificationType.RECEIVE_DRAFT_REJECTED,
            message=(
                f"For {draft.created_by_name}: your receive against PO {po.po_number} is back awaiting "
                f"approval - {why}. Nothing was received into inventory."
            ),
        )
    return draft


def _receive_draft_id_of(entry) -> uuid.UUID | None:
    draft_id = (entry.persist_context or {}).get("receive_draft_id")
    try:
        return uuid.UUID(str(draft_id)) if draft_id else None
    except ValueError:
        return None


def _draft_moved_on(entry, draft) -> bool:
    """THE answer to "has this queued receipt's draft moved on from it?" - for Retry, for Cancel letting it go
    and for the queue's flag alike (#1961, #1964). `draft` is the row's draft (anything with its status, key
    and link).

    It has not while it waits on the row: linked to it (approved with the row as its queued receipt), or
    claimed or approved under the row's own key with no link. That second one is the approval the row was
    written for and nothing else - the key is the approval's identity, and the relay answers a repeat of it
    with the receipt it holds: a held row whose draft was claimed again under its key, or a resume refused
    with its claim kept. The row's Retry, or the claim's own retry, books it; let go, its key's ledger is
    settled as reconciled (`cancel_entry`) and the draft stuck APPROVING for good - approve finds the key
    finished as another receive's, release finds GP's answer, delete finds a claim. Anything else - pending
    again, rejected, or approved under another key - is someone else's approval now: the row never posts."""
    if draft.approved_outbox_entry_id == entry.id:
        return False
    return not (draft.status in _IN_FLIGHT_STATUSES and draft.approval_idempotency_key == entry.idempotency_key)


def receipts_whose_draft_moved_on(session: Session, entries) -> set[uuid.UUID]:
    """The queued receipts, of `entries`, whose draft is there and has moved on from them (`_draft_moved_on`),
    in one read.

    Such a row never posts - its Retry is refused (`assert_outbox_entry_retryable`) - whatever GP made of it:
    sent back for review, or held linked to no draft because the approval was released while it was out at
    GP (#1945). The draft is someone else's to approve now, so a receipt GP took under the row is a manager's
    to reconcile in GP by hand, and the row can be let go (#1961, see `cancel_entry`)."""
    by_draft: dict[uuid.UUID, list] = {}
    for entry in entries:
        draft_id = _receive_draft_id_of(entry) if entry.op == "create_receive" else None
        if draft_id is not None:
            by_draft.setdefault(draft_id, []).append(entry)
    if not by_draft:
        return set()
    drafts = {
        row.id: row
        for row in session.execute(
            select(
                ReceiveDraftModel.id,
                ReceiveDraftModel.status,
                ReceiveDraftModel.approval_idempotency_key,
                ReceiveDraftModel.approved_outbox_entry_id,
            ).where(ReceiveDraftModel.id.in_(list(by_draft)))
        ).all()
    }
    return {
        entry.id
        for draft_id, linked in by_draft.items()
        if draft_id in drafts
        for entry in linked
        if _draft_moved_on(entry, drafts[draft_id])
    }


def assert_outbox_entry_retryable(session: Session, entry) -> None:
    """Refuse to replay a queued receipt whose draft has moved on from it (#1298, `_draft_moved_on`).

    Once the draft is pending again, a manager can approve it afresh under a new key; replaying the old
    row as well would post the same receipt to GP twice."""
    if entry is None or entry.op != "create_receive":
        return
    if entry.id in receipts_whose_draft_moved_on(session, [entry]):
        raise ConflictError(
            "This receipt's draft went back for review when the GP write stopped. Approve the draft "
            "again from Receive Approvals instead of retrying this entry."
        )
