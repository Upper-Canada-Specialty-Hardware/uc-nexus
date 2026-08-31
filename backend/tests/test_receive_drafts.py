"""A receive is counted first and posted second, and the gap between the two is a draft.

The behaviour worth pinning is not "a row gets written" - it is everything that had to stay true
while the GP-first pipeline moved from submission to approval:

* The receive records who COUNTED the hardware, not who signed it off. A manager editing a quantity
  before approving does not take the receive over.
* Approval takes an exclusive claim before the relay is called, because a database lock cannot span
  a network round trip. Two approvers on one draft must not both post a GP receipt.
* Two drafts against the same PO line are legitimate, and approving both when only one line's worth
  is outstanding is not. The second is refused BEFORE GP is touched - after it, GP holds a receipt
  Nexus will not book, which is the split-brain the whole GP-first ordering exists to avoid.
* A failure before the relay call releases the claim. A draft parked in APPROVING for a validation
  error nobody can see would be worse than the error.

The approve tests drive the resolver, not the repository, because the claim/release/mark sequence is
the resolver's and is exactly what a repository-level test would miss. The relay is stubbed; nothing
here talks to GP.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest

from app.auth import ADMIN_ROLE
from app.errors import AppError, RelayUnavailableError, ValidationError
from app.models.enums import NotificationType, POStatus, ReceiveDraftStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receive_draft import ReceiveDraft
from app.repositories import warehouse as warehouse_repository
from app.schemas import warehouse as warehouse_module

AUTHOR = "u_author"
AUTHOR_NAME = "Wendy Warehouse"
MANAGER = "u_manager"
MANAGER_NAME = "Manny Manager"


# --- fixtures -------------------------------------------------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _make_po(session, project_id, *, ordered=10, status=POStatus.GP_REGISTERED):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=status,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        vendor_name_snapshot="Acme",
        company="TUBC",
    )
    session.add(po)
    session.flush()
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=ordered,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=16384,
    )
    session.add(li)
    session.flush()
    return po, li


def _lines(li, quantity):
    return [
        {
            "po_line_item_id": li.id,
            "quantity_received": quantity,
            "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": quantity}],
        }
    ]


def _packing_slip(session, po):
    """#504: a draft is a count made against a piece of paper, so every one needs a slip on its PO."""
    import uuid as _uuid

    from app.models.enums import PODocumentType
    from app.models.purchase_order import PODocument

    doc = PODocument(
        id=_uuid.uuid4(),
        po_id=po.id,
        file_name="slip.pdf",
        content_type="application/pdf",
        file_size=12,
        document_type=PODocumentType.PACKING_SLIP,
        s3_key=f"po-documents/{po.id}/slip-{_uuid.uuid4().hex[:8]}.pdf",
    )
    session.add(doc)
    session.flush()
    return doc


def _draft(session, po, li, quantity=3, *, author_user_id=AUTHOR, author_name=AUTHOR_NAME, notes=None):
    draft = warehouse_repository.create_receive_draft(
        session,
        po.id,
        _lines(li, quantity),
        author_user_id,
        author_name,
        packing_slip_document_id=_packing_slip(session, po).id,
        notes=notes,
    )
    session.flush()
    return draft


def _notifications(session, project_id, notification_type):
    return [
        n
        for n in session.query(Notification).filter(Notification.project_id == project_id).all()
        if n.type == notification_type
    ]


# --- creating, editing, rejecting -------------------------------------------------------------------


def test_a_draft_records_who_counted_the_hardware(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    draft = _draft(db_session, po, li, 4)

    assert draft.status == ReceiveDraftStatus.PENDING_APPROVAL
    assert draft.created_by_user_id == AUTHOR
    assert draft.created_by_name == AUTHOR_NAME
    assert [(x.product_code, x.quantity_received) for x in draft.line_items] == [("HG-100", 4)]
    assert draft.line_items[0].locations == [{"aisle": "A", "row": "1", "bay": "1", "quantity": 4}]
    # Nothing reached inventory: the PO line is untouched.
    db_session.refresh(li)
    assert li.received_quantity == 0


def test_a_draft_that_could_never_be_approved_is_refused_at_submission(db_session):
    """The eligibility rules run at draft time as well as approval time. A count of more than the PO
    is owed is a mistake worth catching in front of the person holding the packing slip."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id, ordered=5)

    with pytest.raises(AppError) as excinfo:
        _draft(db_session, po, li, 6)

    assert "exceeds pending quantity" in excinfo.value.message


def test_submitting_a_draft_tells_the_manager_audience(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    _draft(db_session, po, li, 2)

    raised = _notifications(db_session, project.id, NotificationType.RECEIVE_DRAFT_SUBMITTED)
    assert len(raised) == 1
    assert raised[0].recipient_role == "WAREHOUSE_MANAGER"
    assert AUTHOR_NAME in raised[0].message


def test_resubmitting_the_same_key_returns_the_first_draft(db_session):
    """A network retry must not leave two counts of one delivery in the queue."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    slip = _packing_slip(db_session, po)
    first = warehouse_repository.create_receive_draft(
        db_session,
        po.id,
        _lines(li, 3),
        AUTHOR,
        AUTHOR_NAME,
        idempotency_key="k-1",
        packing_slip_document_id=slip.id,
    )
    db_session.flush()
    second = warehouse_repository.create_receive_draft(
        db_session,
        po.id,
        _lines(li, 3),
        AUTHOR,
        AUTHOR_NAME,
        idempotency_key="k-1",
        packing_slip_document_id=slip.id,
    )

    assert first.id == second.id
    assert db_session.query(ReceiveDraft).filter(ReceiveDraft.po_id == po.id).count() == 1


def test_a_manager_may_correct_a_pending_draft_and_the_author_keeps_the_receive(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)

    warehouse_repository.update_receive_draft(db_session, draft.id, _lines(li, 5), MANAGER, actor_is_manager=True)
    db_session.flush()
    db_session.refresh(draft)

    assert draft.line_items[0].quantity_received == 5
    assert draft.created_by_name == AUTHOR_NAME, "correcting a count must not reassign who received it"


def test_a_stranger_cannot_edit_somebody_elses_draft(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.update_receive_draft(
            db_session, draft.id, _lines(li, 5), "u_someone_else", actor_is_manager=False
        )

    assert excinfo.value.code == "CONFLICT"


def test_rejecting_returns_the_draft_to_its_author_with_the_reason(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)

    warehouse_repository.reject_receive_draft(db_session, draft.id, "Count is short a box", MANAGER, MANAGER_NAME)
    db_session.flush()

    assert draft.status == ReceiveDraftStatus.REJECTED
    assert draft.reviewed_by_name == MANAGER_NAME
    assert draft.rejection_reason == "Count is short a box"
    raised = _notifications(db_session, project.id, NotificationType.RECEIVE_DRAFT_REJECTED)
    assert len(raised) == 1
    assert raised[0].recipient_role == AUTHOR, "a rejection is owed to the person who has to act on it"
    assert "Count is short a box" in raised[0].message


def test_a_rejection_needs_a_reason(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.reject_receive_draft(db_session, draft.id, "   ", MANAGER, MANAGER_NAME)

    assert excinfo.value.field == "reason"


def test_the_author_resubmits_a_rejected_draft_and_a_reviewer_does_not(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)
    warehouse_repository.reject_receive_draft(db_session, draft.id, "recount", MANAGER, MANAGER_NAME)
    db_session.flush()

    with pytest.raises(AppError):
        warehouse_repository.resubmit_receive_draft(db_session, draft.id, MANAGER)

    warehouse_repository.resubmit_receive_draft(db_session, draft.id, AUTHOR)
    db_session.flush()

    assert draft.status == ReceiveDraftStatus.PENDING_APPROVAL
    assert draft.rejection_reason is None
    assert draft.reviewed_by_name is None


def test_deleting_is_open_to_the_author_and_a_manager_but_not_after_approval(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    stranger_draft = _draft(db_session, po, li, 1)
    with pytest.raises(AppError):
        warehouse_repository.delete_receive_draft(db_session, stranger_draft.id, "u_nobody", actor_is_manager=False)
    warehouse_repository.delete_receive_draft(db_session, stranger_draft.id, AUTHOR, actor_is_manager=False)
    db_session.flush()

    manager_deleted = _draft(db_session, po, li, 1)
    warehouse_repository.delete_receive_draft(db_session, manager_deleted.id, MANAGER, actor_is_manager=True)
    db_session.flush()

    approved = _draft(db_session, po, li, 1)
    warehouse_repository.mark_approved(db_session, approved.id, receive_record_id=None)
    with pytest.raises(AppError) as excinfo:
        warehouse_repository.delete_receive_draft(db_session, approved.id, AUTHOR, actor_is_manager=True)
    assert excinfo.value.code == "INVALID_STATE_TRANSITION"


# --- the approval claim ----------------------------------------------------------------------------


def test_claiming_a_draft_blocks_a_second_approver_but_lets_a_retry_resume(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)

    ctx = warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, MANAGER_NAME, "key-a")
    assert ctx.author_name == AUTHOR_NAME, "the GP receipt is posted in the counter's name, not the approver's"
    assert draft.status == ReceiveDraftStatus.APPROVING

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.claim_for_approval(db_session, draft.id, "u_other", "Other Manager", "key-b")
    assert excinfo.value.code == "CONFLICT"
    assert MANAGER_NAME in excinfo.value.message

    # The same key is the same approval, resuming after a dropped connection.
    resumed = warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, MANAGER_NAME, "key-a")
    assert resumed.po_id == po.id


def test_releasing_a_claim_puts_the_draft_back_and_only_its_own_holder_may(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)
    warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, MANAGER_NAME, "key-a")

    warehouse_repository.release_approval_claim(db_session, draft.id, "someone-elses-key")
    db_session.flush()
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.APPROVING, "a claim must not be stealable with the wrong key"

    warehouse_repository.release_approval_claim(db_session, draft.id, "key-a")
    db_session.flush()
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.PENDING_APPROVAL


def test_a_second_draft_cannot_be_claimed_when_the_first_already_spoke_for_the_pending_units(db_session):
    """The guard that keeps a GP receipt from being posted for hardware the PO no longer owes.

    Both drafts were legal when written - each was within the PO's pending quantity - and neither can
    see the other. The claim is where they meet, which is the last point before GP that refusing is
    still free.
    """
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id, ordered=5)
    first = _draft(db_session, po, li, 3)
    second = _draft(db_session, po, li, 3)

    warehouse_repository.claim_for_approval(db_session, first.id, MANAGER, MANAGER_NAME, "key-1")

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.claim_for_approval(db_session, second.id, MANAGER, MANAGER_NAME, "key-2")
    assert excinfo.value.code == "CONFLICT"
    assert "over-receive" in excinfo.value.message


def test_an_approved_draft_cannot_be_approved_again(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3)
    warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, MANAGER_NAME, "key-a")
    warehouse_repository.mark_approved(db_session, draft.id, outbox_entry_id=None)

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, MANAGER_NAME, "key-c")
    assert excinfo.value.code == "CONFLICT"


# --- approval through the resolver -------------------------------------------------------------------
#
# These drive the resolver rather than the repository, because the claim / relay / persist / release
# sequence IS the resolver's and is exactly what a repository-level test cannot see. The resolver
# opens its own sessions, so the fixtures below commit for real and tear down afterwards - the same
# rule test_gp_outbox_worker.py follows. The relay is stubbed in every one of them; nothing here
# talks to GP.


class _StubRelay:
    """Stands in for the GP relay. `fail_with` makes the call raise instead of answering."""

    def __init__(self, result=None, fail_with=None):
        self.result = result if result is not None else {"receipt_number": "RCT000123", "batch_number": "B1"}
        self.fail_with = fail_with
        self.calls = []

    async def relay_call(self, company, op, payload=None, timeout=30.0):
        self.calls.append((company, op, payload))
        if self.fail_with is not None:
            raise self.fail_with
        return self.result


class _Info:
    def __init__(self):
        # Seeded with the caller's roles, which is where `tenant_scope` reads them from (#637): a
        # Warehouse Manager with no company assigned would otherwise be refused before the approval
        # logic under test ran. ADMIN_ROLE makes the caller unscoped, which is what these are about.
        self.context = {"_auth_roles": [ADMIN_ROLE, "Warehouse Manager"]}


@pytest.fixture
def approve_env(monkeypatch):
    """Wire the resolver's Clerk edges to something deterministic - the caller is a manager."""
    monkeypatch.setattr(warehouse_module, "current_user", lambda info: {"user_id": MANAGER})
    monkeypatch.setattr(warehouse_module, "resolve_display_name", lambda user_id: MANAGER_NAME)
    monkeypatch.setattr(warehouse_module, "caller_roles", lambda ctx: ["Warehouse Manager"])


class _CommittedFixture:
    """A committed project / PO / draft, plus what is needed to clean it all up afterwards.

    `stock_item_ids_before` is the stock pool as it stood when the fixture was built. A stock-PO
    receive either creates a stock row or merges into an existing one, and only the ids that appeared
    afterwards are this test's to delete - `StockItem` carries no PO number to key on, because stock
    is fungible by design.
    """

    def __init__(self, project_id, po_id, po_number, po_line_item_id, draft_id, stock_item_ids_before):
        self.project_id = project_id
        self.po_id = po_id
        self.po_number = po_number
        self.po_line_item_id = po_line_item_id
        self.draft_id = draft_id
        self.stock_item_ids_before = stock_item_ids_before


@pytest.fixture
def committed(_migrate_database):
    """Build a draft that a resolver in another session can see, and remove it all afterwards."""
    from app.database import SessionLocal

    created: list[_CommittedFixture] = []

    def _build(*, with_project=True, ordered=10, quantity=4, notes=None):
        from sqlalchemy import select

        from app.models.stock_item import StockItem

        from .inventory_fixtures import define_location

        with SessionLocal() as session:
            project = _make_project(session) if with_project else None
            po, li = _make_po(session, project.id if project else None, ordered=ordered)
            define_location(session)
            draft = _draft(session, po, li, quantity, notes=notes)
            fixture = _CommittedFixture(
                project.id if project else None,
                po.id,
                po.po_number,
                li.id,
                draft.id,
                set(session.scalars(select(StockItem.id)).all()),
            )
            session.commit()
        created.append(fixture)
        return fixture

    yield _build

    _cleanup(created)


def _cleanup(fixtures) -> None:
    """Remove every row a committed fixture could have produced, dependants before their parents.

    These tests commit for real (the resolver opens its own sessions and cannot see an uncommitted
    outer transaction), so nothing else is going to roll them back.
    """
    from sqlalchemy import delete, select

    from app.database import SessionLocal
    from app.models.audit_log import InventoryAuditLog
    from app.models.gp_outbox import GpWriteOutbox
    from app.models.inventory import InventoryLocation
    from app.models.notification import Notification
    from app.models.project import Project
    from app.models.purchase_order import PODocument
    from app.models.purchase_order import POLineItem as POLineItemModel
    from app.models.purchase_order import PurchaseOrder as POModel
    from app.models.receive_draft import ReceiveDraft as DraftModel
    from app.models.receiving import ReceiveLineItem, ReceiveRecord
    from app.models.stock_item import StockItem

    with SessionLocal() as session:
        for f in fixtures:
            receive_ids = list(session.scalars(select(ReceiveRecord.id).where(ReceiveRecord.po_id == f.po_id)).all())
            # Line items go with the draft via ON DELETE CASCADE.
            session.execute(delete(DraftModel).where(DraftModel.po_id == f.po_id))
            session.execute(delete(InventoryLocation).where(InventoryLocation.po_line_item_id == f.po_line_item_id))
            session.execute(delete(ReceiveLineItem).where(ReceiveLineItem.receive_record_id.in_(receive_ids)))
            session.execute(delete(ReceiveRecord).where(ReceiveRecord.po_id == f.po_id))
            session.execute(delete(GpWriteOutbox).where(GpWriteOutbox.entity_key == f"po:{f.po_id}"))
            if f.project_id is not None:
                session.execute(delete(InventoryAuditLog).where(InventoryAuditLog.project_id == f.project_id))
                session.execute(delete(Notification).where(Notification.project_id == f.project_id))
            else:
                # A stock PO receives into the pool. StockItem carries no PO number - stock is
                # fungible - so what this test created is whatever appeared since the fixture was
                # built. A receive that MERGED into an existing row leaves no new id and is left
                # alone, which is the right call: that row is not ours to delete.
                new_stock = set(session.scalars(select(StockItem.id)).all()) - f.stock_item_ids_before
                if new_stock:
                    session.execute(delete(StockItem).where(StockItem.id.in_(new_stock)))
            session.execute(delete(POLineItemModel).where(POLineItemModel.po_id == f.po_id))
            # After the drafts, which reference the slip they were counted against (#504).
            session.execute(delete(PODocument).where(PODocument.po_id == f.po_id))
            session.execute(delete(POModel).where(POModel.id == f.po_id))
            if f.project_id is not None:
                session.execute(delete(Project).where(Project.id == f.project_id))
        session.commit()


def _approve(draft_id, key=None):
    from app.schemas.inputs import ApproveReceiveDraftInput

    return asyncio.run(
        warehouse_module.WarehouseMutations().approve_receive_draft(
            _Info(), ApproveReceiveDraftInput(draft_id=str(draft_id), idempotency_key=key or str(uuid.uuid4()))
        )
    )


def _read_draft(draft_id) -> ReceiveDraft:
    from app.database import SessionLocal

    with SessionLocal() as session:
        return session.get(ReceiveDraft, draft_id)


def test_approving_posts_the_gp_receipt_in_the_counters_name(committed, monkeypatch, approve_env):
    f = committed()
    relay = _StubRelay()
    monkeypatch.setattr(warehouse_module, "relay_gateway", relay)

    result = _approve(f.draft_id)

    assert result.queued is False
    assert result.receive_record.receipt_number == "RCT000123"
    assert result.receive_record.received_by == AUTHOR_NAME, (
        "the receive records who counted the hardware; the approver is on the draft's review fields"
    )
    assert result.draft.status.value == "APPROVED"
    assert result.draft.receive_record_id == result.receive_record.id
    assert relay.calls[0][1] == "create_receipt"


def test_approving_while_the_relay_is_down_queues_the_receipt_and_still_closes_the_draft(
    committed, monkeypatch, approve_env
):
    """A draft left approvable after its receipt was queued would enqueue a SECOND one."""
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    f = committed()
    monkeypatch.setattr(
        warehouse_module,
        "relay_gateway",
        _StubRelay(fail_with=RelayUnavailableError("no relay", dispatched=False)),
    )

    result = _approve(f.draft_id)

    assert result.queued is True
    assert result.receive_record is None
    assert result.draft.status.value == "APPROVED"
    assert result.draft.outbox_entry_id is not None
    assert result.draft.receive_record_id is None, "nothing is in inventory until the outbox drains"

    with SessionLocal() as session:
        row = session.get(GpWriteOutbox, uuid.UUID(str(result.draft.outbox_entry_id)))
    assert row.persist_context["receive_draft_id"] == str(f.draft_id)
    assert row.persist_context["received_by"] == AUTHOR_NAME, (
        "the queued receipt must post in the counter's name too, not the approver's"
    )


def test_a_failure_before_the_relay_call_releases_the_claim(committed, monkeypatch, approve_env):
    """Otherwise a validation error parks the draft in APPROVING, where nobody can see it and only a
    retry with the same key can clear it."""
    from app.database import SessionLocal
    from app.models.purchase_order import PurchaseOrder as POModel

    f = committed()
    # Close the PO underneath the draft: approval's re-validation refuses it, pre-GP.
    with SessionLocal() as session:
        session.get(POModel, f.po_id).status = POStatus.CLOSED
        session.commit()

    relay = _StubRelay()
    monkeypatch.setattr(warehouse_module, "relay_gateway", relay)

    with pytest.raises(AppError):
        _approve(f.draft_id)

    assert _read_draft(f.draft_id).status == ReceiveDraftStatus.PENDING_APPROVAL
    assert relay.calls == [], "nothing should have reached GP"


def test_an_econnect_refusal_puts_the_draft_back_in_the_queue(committed, monkeypatch, approve_env):
    """GP said no, which means GP did not commit - so the draft belongs back where somebody can act
    on it once the cause is fixed (#425's broken job being the usual one).

    Leaving it claimed would be the worst of both: nothing in GP, and a draft nobody can approve,
    reject, edit or delete, whose quantities also block every later draft on the same PO line.
    """
    from app.errors import RelayCallError

    f = committed()
    relay = _StubRelay(fail_with=RelayCallError("eConnect 4612 Invalid Account Index", detail={"error": "x"}))
    monkeypatch.setattr(warehouse_module, "relay_gateway", relay)

    with pytest.raises(AppError):
        _approve(f.draft_id)

    assert _read_draft(f.draft_id).status == ReceiveDraftStatus.PENDING_APPROVAL
    assert len(relay.calls) == 1, "the refusal has to come from GP, not from skipping the call"


def test_an_ambiguous_relay_failure_keeps_the_claim_and_the_key_that_resumes_it(committed, monkeypatch, approve_env):
    """A timeout or a dispatched disconnect means GP MAY hold the receipt. Releasing would let a
    fresh approval post a second one, so the draft stays claimed - and the key it is claimed under is
    on the row, which is what makes the retry a resume rather than a new approval."""
    from app.errors import RelayTimeoutError

    f = committed()
    monkeypatch.setattr(warehouse_module, "relay_gateway", _StubRelay(fail_with=RelayTimeoutError()))

    key = str(uuid.uuid4())
    with pytest.raises(AppError):
        _approve(f.draft_id, key=key)

    parked = _read_draft(f.draft_id)
    assert parked.status == ReceiveDraftStatus.APPROVING
    assert parked.approval_idempotency_key == key


def test_a_resumed_approval_does_not_re_validate_what_gp_has_already_run(committed, monkeypatch, approve_env):
    """The window that could post a SECOND GP receipt.

    GP posted under this key and only the Nexus persist is outstanding. If the resume re-ran the
    eligibility check and another receive had landed against the line in between, the refusal would
    release the claim - and the next approval, carrying a fresh key, would find an empty ledger and
    post again for hardware GP already booked.
    """
    from app.services import gp_idempotency

    f = committed()
    key = str(uuid.uuid4())
    gp_idempotency.record_relay_result(key, "create_receive", {"receipt_number": "RCT000777"})
    # Close the PO so any re-validation would refuse. The relay must also never be called again.
    relay = _StubRelay()
    monkeypatch.setattr(warehouse_module, "relay_gateway", relay)

    result = _approve(f.draft_id, key=key)

    assert relay.calls == [], "GP already ran under this key; calling again is the duplicate receipt"
    assert result.receive_record.receipt_number == "RCT000777"
    assert result.draft.status.value == "APPROVED"


def test_a_stock_po_draft_works_end_to_end(committed, monkeypatch, approve_env):
    """A project-less PO routes to the stock pool. Drafts apply to it and approve unchanged."""
    f = committed(with_project=False, quantity=2)
    monkeypatch.setattr(warehouse_module, "relay_gateway", _StubRelay())

    result = _approve(f.draft_id)

    assert result.queued is False
    assert result.draft.status.value == "APPROVED"


def test_a_manager_approves_a_project_draft_with_no_decision_in_sight(committed, monkeypatch, approve_env):
    """The keep-or-ship decision workflow is gone: a counted project receive is approved by a
    Warehouse Manager directly, the GP receipt posts, and the units book. No creator step gates it."""
    f = committed(with_project=True, quantity=4)
    monkeypatch.setattr(warehouse_module, "relay_gateway", _StubRelay())

    result = _approve(f.draft_id)

    assert result.queued is False
    assert result.draft.status.value == "APPROVED"
    assert result.receive_record is not None


# --- the packing slip requirement (#504) -------------------------------------------------------
# A draft is a count made against a piece of paper that came off the truck. Nothing recorded which
# piece of paper, so a disputed count had nothing to check against.


def test_a_draft_without_a_packing_slip_is_refused(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    with pytest.raises(ValidationError) as excinfo:
        warehouse_repository.create_receive_draft(
            db_session, po.id, _lines(li, 3), AUTHOR, AUTHOR_NAME, packing_slip_document_id=None
        )

    assert excinfo.value.field == "packing_slip_document_id"


def test_a_slip_from_another_po_is_refused(db_session):
    """Otherwise the link records somebody else's delivery."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    other_po, _ = _make_po(db_session, project.id)
    foreign = _packing_slip(db_session, other_po)

    with pytest.raises(ValidationError):
        warehouse_repository.create_receive_draft(
            db_session, po.id, _lines(li, 3), AUTHOR, AUTHOR_NAME, packing_slip_document_id=foreign.id
        )


def test_a_document_that_is_not_a_packing_slip_is_refused(db_session):
    import uuid as _uuid

    from app.models.enums import PODocumentType
    from app.models.purchase_order import PODocument

    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    wrong_type = PODocument(
        id=_uuid.uuid4(),
        po_id=po.id,
        file_name="ack.pdf",
        content_type="application/pdf",
        file_size=12,
        document_type=PODocumentType.VENDOR_ACKNOWLEDGEMENT,
        s3_key=f"po-documents/{po.id}/ack.pdf",
    )
    db_session.add(wrong_type)
    db_session.flush()

    with pytest.raises(ValidationError):
        warehouse_repository.create_receive_draft(
            db_session, po.id, _lines(li, 3), AUTHOR, AUTHOR_NAME, packing_slip_document_id=wrong_type.id
        )


def test_the_slip_is_pinned_to_the_draft(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    slip = _packing_slip(db_session, po)

    draft = warehouse_repository.create_receive_draft(
        db_session, po.id, _lines(li, 3), AUTHOR, AUTHOR_NAME, packing_slip_document_id=slip.id
    )

    assert draft.packing_slip_document_id == slip.id


# --- the counter's remark (#632) ----------------------------------------------------------------
# What the person counting wants the approver to know ("box crushed", "short 2 per slip"). Nexus-only
# - it never reaches GP - and it has to survive the draft, so it is copied onto the ReceiveRecord at
# approval. Otherwise the one piece of context about a disputed delivery dies with the draft row.


def test_a_draft_carries_the_counters_remark_stripped(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    draft = _draft(db_session, po, li, 3, notes="  box crushed on the pallet  ")

    assert draft.notes == "box crushed on the pallet"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_remark_is_stored_as_null(db_session, blank):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    draft = _draft(db_session, po, li, 3, notes=blank)

    assert draft.notes is None


def test_an_over_long_remark_is_a_named_validation_error(db_session):
    """Text column, but unbounded free text on a row every approver reads is worth a named refusal
    rather than a wall of prose."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    with pytest.raises(ValidationError) as excinfo:
        _draft(db_session, po, li, 3, notes="x" * 2001)

    assert excinfo.value.field == "notes"


def test_editing_leaves_the_remark_alone_unless_it_is_sent(db_session):
    """Same reading as warehouse_id: None means "not being changed", an empty string clears it. A
    manager correcting quantities must not silently wipe what the counter wrote."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, 3, notes="short 2 per slip")

    warehouse_repository.update_receive_draft(db_session, draft.id, _lines(li, 5), MANAGER, actor_is_manager=True)
    db_session.flush()
    assert draft.notes == "short 2 per slip"

    warehouse_repository.update_receive_draft(
        db_session, draft.id, _lines(li, 5), MANAGER, actor_is_manager=True, notes="  recounted, all present  "
    )
    db_session.flush()
    assert draft.notes == "recounted, all present"

    warehouse_repository.update_receive_draft(
        db_session, draft.id, _lines(li, 5), MANAGER, actor_is_manager=True, notes=""
    )
    db_session.flush()
    assert draft.notes is None


def test_a_receive_record_stores_the_remark_it_was_given(db_session):
    """The persist half: create_receive is the single path both a live approval and a drained outbox
    row go through, so the column is written there."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    record = warehouse_repository.create_receive(
        db_session,
        po.id,
        AUTHOR_NAME,
        [{"po_line_item_id": li.id, "quantity_received": 2, "locations": []}],
        notes="box crushed on the pallet",
    )

    assert record.notes == "box crushed on the pallet"


def test_a_receive_record_with_no_remark_stores_null(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    record = warehouse_repository.create_receive(
        db_session,
        po.id,
        AUTHOR_NAME,
        [{"po_line_item_id": li.id, "quantity_received": 2, "locations": []}],
    )

    assert record.notes is None


def test_approving_copies_the_drafts_remark_onto_the_receive(committed, monkeypatch, approve_env):
    """End to end through the resolver: the remark is read off the draft inside the persist
    transaction, which is the one place that covers a live approval AND a queued receipt draining."""
    f = committed(notes="box crushed on the pallet")
    monkeypatch.setattr(warehouse_module, "relay_gateway", _StubRelay())

    result = _approve(f.draft_id)

    assert result.receive_record.notes == "box crushed on the pallet"
    assert result.draft.notes == "box crushed on the pallet"
