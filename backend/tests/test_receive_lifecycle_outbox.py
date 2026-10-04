"""#1298 / #1300: a queued receipt's end state reaches its draft, and the GP sync waits for it.

A receive approval queued while the relay was down links its draft to the outbox row and leaves the
draft APPROVED. When that row ends without GP ever taking the receipt (cancelled, refused by GP, or out
of attempts before it was sent), the draft goes back to awaiting approval, its author is told, and the
old row can no longer be replayed underneath a fresh approval. A row that may have reached GP
(ambiguous, or the ledger holds a relay result) keeps its draft for a person to reconcile.

The GP PO sync holds received_quantity where Nexus has it while a receipt is between GP and its
persist, so the persist's own += does not count it twice."""

import uuid
from decimal import Decimal

import pytest

from app.errors import AppError
from app.models.enums import NotificationType, POStatus, ReceiveDraftStatus
from app.models.gp_write import GpWriteIdempotency
from app.models.notification import Notification
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receive_draft import ReceiveDraft
from app.repositories import gp_outbox_repository
from app.repositories import gp_po_sync_repository as sync_repo
from app.repositories import warehouse as warehouse_repository

AUTHOR = "u_author"
MANAGER = "u_manager"


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"J{uuid.uuid4().hex[:6]}", description="Job", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _po(session, project_id, *, ordered=10):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=POStatus.GP_REGISTERED,
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


def _draft(session, po, li, quantity, status=ReceiveDraftStatus.PENDING_APPROVAL) -> ReceiveDraft:
    from app.models.receive_draft import ReceiveDraftLineItem

    draft = ReceiveDraft(
        id=uuid.uuid4(),
        po_id=po.id,
        status=status,
        created_by_user_id=AUTHOR,
        created_by_name="Ann Author",
    )
    session.add(draft)
    session.flush()
    session.add(
        ReceiveDraftLineItem(
            id=uuid.uuid4(),
            receive_draft_id=draft.id,
            po_line_item_id=li.id,
            hardware_category=li.hardware_category,
            product_code=li.product_code,
            quantity_received=quantity,
            locations=[{"aisle": "A", "row": "1", "bay": "1", "quantity": quantity}],
        )
    )
    session.flush()
    session.refresh(draft)
    return draft


def _queued_approval(session, po, li, quantity) -> tuple[ReceiveDraft, object]:
    """A draft approved while the relay was down: APPROVED, linked to a PENDING create_receive row."""
    draft = _draft(session, po, li, quantity)
    key = f"approve-{uuid.uuid4().hex}"
    draft.reviewed_by_user_id = MANAGER
    draft.reviewed_by_name = "Manny Manager"
    draft.approval_idempotency_key = key
    row = gp_outbox_repository.enqueue(
        session,
        idempotency_key=key,
        op="create_receive",
        relay_op="create_receipt",
        company="TEST",
        payload={},
        persist_context={"po_id": str(po.id), "receive_draft_id": str(draft.id), "line_items_data": []},
        entity_key=f"po:{po.id}",
        label=f"Receipt for {po.po_number}",
        project_id=po.project_id,
    )
    warehouse_repository.mark_approved(session, draft.id, outbox_entry_id=row.id)
    return draft, row


def _told_author(session, project_id) -> list[Notification]:
    return [
        n
        for n in session.query(Notification).filter(Notification.project_id == project_id).all()
        if n.type == NotificationType.RECEIVE_DRAFT_REJECTED and n.recipient_user_id == AUTHOR
    ]


# --- #1298 ---------------------------------------------------------------------------------------


def test_cancelling_a_queued_receipt_sends_its_draft_back_for_review(db_session):
    project = _project(db_session)
    po, li = _po(db_session, project.id)
    draft, row = _queued_approval(db_session, po, li, 4)

    gp_outbox_repository.cancel_entry(db_session, row.id)
    db_session.refresh(draft)

    assert draft.status == ReceiveDraftStatus.PENDING_APPROVAL
    assert draft.approved_outbox_entry_id is None
    assert draft.approval_idempotency_key is None
    assert draft.reviewed_by_user_id is None
    assert "cancelled" in (draft.rejection_reason or "")
    assert _told_author(db_session, project.id), "the author is told the receive came back"

    # And it can be approved again: nothing is left claiming the line.
    ctx = warehouse_repository.claim_for_approval(db_session, draft.id, MANAGER, "Manny Manager", "fresh-key")
    assert ctx.po_id == po.id


def test_a_gp_refusal_sends_the_draft_back_and_the_old_row_cannot_be_replayed(db_session):
    project = _project(db_session)
    po, li = _po(db_session, project.id)
    draft, row = _queued_approval(db_session, po, li, 4)

    gp_outbox_repository.mark_failed(db_session, row, kind="gp_rejected", error="PO line is closed")
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.PENDING_APPROVAL
    assert "PO line is closed" in (draft.rejection_reason or "")

    with pytest.raises(AppError) as excinfo:
        gp_outbox_repository.retry_entry(db_session, row.id)
    assert excinfo.value.code == "CONFLICT"


@pytest.mark.parametrize("kind", ["ambiguous", "persist_failed"])
def test_a_failure_that_may_have_reached_gp_keeps_the_draft(db_session, kind):
    project = _project(db_session)
    po, li = _po(db_session, project.id)
    draft, row = _queued_approval(db_session, po, li, 4)

    gp_outbox_repository.mark_failed(db_session, row, kind=kind, error="link dropped")
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.APPROVED
    assert draft.approved_outbox_entry_id == row.id

    # Cancelling it afterwards does not release it either: GP may hold the receipt.
    gp_outbox_repository.cancel_entry(db_session, row.id)
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.APPROVED


def test_a_ledger_relay_result_means_gp_took_it_so_the_draft_stays(db_session):
    project = _project(db_session)
    po, li = _po(db_session, project.id)
    draft, row = _queued_approval(db_session, po, li, 4)
    db_session.add(
        GpWriteIdempotency(key=row.idempotency_key, op="create_receive", relay_result={"receipt_number": "R1"})
    )
    db_session.flush()

    gp_outbox_repository.mark_failed(db_session, row, kind="exhausted", error="persist kept failing")
    db_session.refresh(draft)
    assert draft.status == ReceiveDraftStatus.APPROVED


def test_a_stuck_draft_from_before_the_fix_no_longer_blocks_a_new_receive(db_session):
    """A queued approval cancelled before drafts were released stays APPROVED; its units must not
    count as in flight against the line any more."""
    project = _project(db_session)
    po, li = _po(db_session, project.id, ordered=10)
    _stuck, row = _queued_approval(db_session, po, li, 8)
    row.status = "CANCELLED"  # as an old cancel left it, with no release
    db_session.flush()

    fresh = _draft(db_session, po, li, 8)
    ctx = warehouse_repository.claim_for_approval(db_session, fresh.id, MANAGER, "Manny Manager", "k2")
    assert ctx.po_id == po.id


def test_a_live_queued_receipt_still_counts_as_in_flight(db_session):
    project = _project(db_session)
    po, li = _po(db_session, project.id, ordered=10)
    _queued_approval(db_session, po, li, 8)

    fresh = _draft(db_session, po, li, 8)
    with pytest.raises(AppError) as excinfo:
        warehouse_repository.claim_for_approval(db_session, fresh.id, MANAGER, "Manny Manager", "k3")
    assert excinfo.value.code == "CONFLICT"


# --- #1300 ---------------------------------------------------------------------------------------

COMPANY = "TEST"


def _gp_po(po_number, received):
    return {
        "po_number": po_number,
        "gp_status": 2,
        "vendor_id": "V1",
        "vendor_name": "Acme",
        "doc_date": "2026-01-05",
        "modified_at": "2026-01-06T09:00:00",
        "source_table": "work",
        "lines": [
            {
                "ord": 16384,
                "item": "HINGE",
                "itemdesc": "HG-100",
                "qty": 10,
                "qty_cancelled": 0,
                "received": received,
                "unit_cost": 1,
                "job": "",
                "line_status": 2,
                "cost_code": None,
            }
        ],
    }


def _mirrored(session):
    """A PO the mirror already knows, with 2 received in both systems."""
    po_number = f"PO{uuid.uuid4().hex[:6]}"
    sync_repo.upsert_mirrored_po(session, COMPANY, _gp_po(po_number, 2), {})
    session.flush()
    po = session.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).one()
    return po_number, po, po.line_items[0]


def test_the_sync_does_not_raise_received_while_a_draft_is_mid_approval(db_session):
    po_number, po, li = _mirrored(db_session)
    _draft(db_session, po, li, 4, status=ReceiveDraftStatus.APPROVING)

    # GP already shows the 4 being approved; the persist will add them itself.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number, 6), {})
    db_session.flush()
    db_session.refresh(li)
    assert li.received_quantity == 2


def test_the_sync_does_not_raise_received_while_a_receipt_is_queued(db_session):
    po_number, po, li = _mirrored(db_session)
    gp_outbox_repository.enqueue(
        db_session,
        idempotency_key=f"rcv-{uuid.uuid4().hex}",
        op="create_receive",
        relay_op="create_receipt",
        company=COMPANY,
        payload={},
        persist_context={},
        entity_key=f"po:{po.id}",
        label="Receipt",
    )

    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number, 6), {})
    db_session.flush()
    db_session.refresh(li)
    assert li.received_quantity == 2


def test_the_sync_raises_received_once_nothing_is_in_flight(db_session):
    po_number, po, li = _mirrored(db_session)
    _draft(db_session, po, li, 4, status=ReceiveDraftStatus.PENDING_APPROVAL)  # not yet claimed

    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po_number, 6), {})
    db_session.flush()
    db_session.refresh(li)
    assert li.received_quantity == 6


# --- #1436 ---------------------------------------------------------------------------------------


def _receivable(session):
    """A registered project PO with 2 of 10 received in both systems, and a shelf to receive onto."""
    from tests.inventory_fixtures import define_location

    project = _project(session)
    po, li = _po(session, project.id)
    define_location(session, aisle="A", row="1", bay="1")
    sync_repo.upsert_mirrored_po(session, COMPANY, _gp_po(po.po_number, 2), {})
    session.flush()
    session.refresh(po)
    assert po.status == POStatus.PARTIALLY_RECEIVED
    return po, li


def _persist(session, po, li, quantity):
    from app.repositories.warehouse.receiving import create_receive
    from tests.inventory_fixtures import wh_id

    create_receive(
        session,
        po.id,
        "warehouse",
        [
            {
                "po_line_item_id": li.id,
                "quantity_received": quantity,
                "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": quantity}],
            }
        ],
        warehouse_id=wh_id(session),
    )
    session.flush()


def test_the_sync_does_not_close_a_po_while_its_last_receipt_is_mid_approval(db_session):
    po, li = _receivable(db_session)
    draft = _draft(db_session, po, li, 8, status=ReceiveDraftStatus.APPROVING)

    # GP already shows all 10: the 8 being approved posted there, the Nexus persist has not run.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po.po_number, 10), {})
    db_session.flush()
    db_session.refresh(po)
    assert po.status == POStatus.PARTIALLY_RECEIVED

    # So the persist is not refused as a receipt onto a closed PO, and it closes the PO itself.
    _persist(db_session, po, li, 8)
    db_session.delete(draft)
    db_session.flush()
    db_session.refresh(po)
    db_session.refresh(li)
    assert li.received_quantity == 10
    assert po.status == POStatus.CLOSED

    # The next pass agrees with GP and leaves it closed.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po.po_number, 10), {})
    db_session.flush()
    db_session.refresh(po)
    assert po.status == POStatus.CLOSED


def test_the_sync_does_not_close_a_po_while_its_last_receipt_is_queued(db_session):
    po, li = _receivable(db_session)
    gp_outbox_repository.enqueue(
        db_session,
        idempotency_key=f"rcv-{uuid.uuid4().hex}",
        op="create_receive",
        relay_op="create_receipt",
        company=COMPANY,
        payload={},
        persist_context={},
        entity_key=f"po:{po.id}",
        label="Receipt",
    )

    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po.po_number, 10), {})
    db_session.flush()
    db_session.refresh(po)
    assert po.status == POStatus.PARTIALLY_RECEIVED

    _persist(db_session, po, li, 8)
    db_session.refresh(po)
    assert po.status == POStatus.CLOSED


def test_an_unposted_gp_count_below_nexus_does_not_reopen_a_closed_po(db_session):
    po, li = _receivable(db_session)
    _persist(db_session, po, li, 8)
    db_session.refresh(po)
    assert po.status == POStatus.CLOSED

    # GP's batch for the 8 is not posted yet, so it still reports 2; the lines keep 10 (the floor).
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po.po_number, 2), {})
    db_session.flush()
    db_session.refresh(po)
    db_session.refresh(li)
    assert li.received_quantity == 10
    assert po.status == POStatus.CLOSED


def test_the_sync_closes_a_po_gp_received_in_full_with_nothing_in_flight(db_session):
    po, li = _receivable(db_session)

    sync_repo.upsert_mirrored_po(db_session, COMPANY, _gp_po(po.po_number, 10), {})
    db_session.flush()
    db_session.refresh(po)
    db_session.refresh(li)
    assert li.received_quantity == 10
    assert po.status == POStatus.CLOSED
