"""A landed shipment asks the person who ordered it where it should go.

Three properties carry the feature:

* The question is raised INSIDE the receive persist, not by the resolver. There are two routes into
  that persist - an online approval and the outbox worker draining a receipt queued while the relay
  was down - and a decision minted in the resolver would exist only for the first.
* Who it is addressed to is read off a column, never resolved through Clerk. That call would sit
  inside the transaction of a GP receipt that has already posted, and a Clerk outage would then roll
  back something GP holds. The read side does the resolving instead, for one caller at a time.
* POs raised before that column existed still reach somebody: the read falls back to matching the
  PO's GP buyer against the CALLER's own gpBuyerId, which is a filter on the caller rather than a
  search across users.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.errors import AppError
from app.models.enums import NotificationType, POStatus, ReceiveDecisionChoice, ReceiveDecisionStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receive_decision import ReceiveDecision
from app.repositories import warehouse as warehouse_repository

CREATOR = "u_creator"
CREATOR_NAME = "Paula Purchasing"
STRANGER = "u_stranger"


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_po(session, project_id, *, created_by=CREATOR, buyer_id=None, ordered=10):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        created_by_user_id=created_by,
        buyer_id=buyer_id,
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


def _receive(session, po, li, quantity=3):
    """Book a receive the way an approved draft does, straight through the persist path."""
    record = warehouse_repository.create_receive(
        session,
        po.id,
        "Wendy Warehouse",
        [
            {
                "po_line_item_id": li.id,
                "quantity_received": quantity,
                "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": quantity}],
            }
        ],
        receipt_number="RCT000999",
    )
    session.flush()
    return record


def _decision_for(session, receive_record):
    return session.scalars(
        select(ReceiveDecision).where(ReceiveDecision.receive_record_id == receive_record.id)
    ).first()


def test_booking_a_receive_raises_the_question_for_the_pos_originator(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    record = _receive(db_session, po, li, 3)

    decision = _decision_for(db_session, record)
    assert decision is not None
    assert decision.status == ReceiveDecisionStatus.PENDING
    assert decision.target_user_id == CREATOR
    assert decision.project_id == project.id
    assert decision.decision is None


def test_the_originator_is_told_personally(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    _receive(db_session, po, li, 3)

    raised = [
        n
        for n in db_session.query(Notification).filter(Notification.project_id == project.id).all()
        if n.type == NotificationType.RECEIVE_DECISION_REQUIRED
    ]
    assert len(raised) == 1
    assert raised[0].recipient_role == CREATOR, "the question is addressed to a person, not an audience"
    assert po.po_number in raised[0].message


def test_a_po_with_no_recorded_originator_raises_the_question_but_addresses_nobody(db_session):
    """Every PO from before the column existed. An un-addressed notification would say nothing about
    who has to act, so it is skipped - the pending-decisions read, with its buyer fallback, is what
    reaches the right person instead."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id, created_by=None, buyer_id="BUYER1")

    record = _receive(db_session, po, li, 3)

    decision = _decision_for(db_session, record)
    assert decision is not None
    assert decision.target_user_id is None
    assert not [
        n
        for n in db_session.query(Notification).filter(Notification.project_id == project.id).all()
        if n.type == NotificationType.RECEIVE_DECISION_REQUIRED
    ]


def test_a_stock_po_asks_nothing(db_session):
    """ "Which project's inventory does this stay in" is not a question you can ask without a project."""
    po, li = _make_po(db_session, None)

    record = _receive(db_session, po, li, 2)

    assert _decision_for(db_session, record) is None


def test_the_pending_read_finds_both_the_stamped_target_and_the_buyer_fallback(db_session):
    project = _make_project(db_session)
    stamped_po, stamped_li = _make_po(db_session, project.id, created_by=CREATOR)
    legacy_po, legacy_li = _make_po(db_session, project.id, created_by=None, buyer_id="paula ")
    other_po, other_li = _make_po(db_session, project.id, created_by=STRANGER)
    _receive(db_session, stamped_po, stamped_li, 1)
    _receive(db_session, legacy_po, legacy_li, 1)
    _receive(db_session, other_po, other_li, 1)

    # The GP BUYERID is char(15), so the fallback matches the way _assert_buyer_identity does -
    # trimmed and case-insensitive - rather than on an exact byte match.
    rows = warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, "PAULA")

    assert {po.id for _d, po, _rr, _draft in rows} == {stamped_po.id, legacy_po.id}


def test_without_a_gp_buyer_identity_only_the_stamped_decisions_are_owed(db_session):
    project = _make_project(db_session)
    stamped_po, stamped_li = _make_po(db_session, project.id, created_by=CREATOR)
    legacy_po, legacy_li = _make_po(db_session, project.id, created_by=None, buyer_id="PAULA")
    _receive(db_session, stamped_po, stamped_li, 1)
    _receive(db_session, legacy_po, legacy_li, 1)

    rows = warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, None)

    assert {po.id for _d, po, _rr, _draft in rows} == {stamped_po.id}


@pytest.mark.parametrize("choice", [ReceiveDecisionChoice.KEEP_IN_INVENTORY, ReceiveDecisionChoice.SHIP_OUT])
def test_answering_records_the_choice_and_nothing_else(db_session, choice):
    """SHIP_OUT deliberately creates no shipping-out request: only the schedule knows which opening a
    fungible quantity is owed to, so the frontend deep-links into Start a Request from here."""
    from app.models.shipping_out_request import ShippingOutRequest

    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    record = _receive(db_session, po, li, 3)
    decision = _decision_for(db_session, record)

    warehouse_repository.decide_receive_decision(
        db_session, decision.id, choice, CREATOR, CREATOR_NAME, None, actor_is_admin=False
    )
    db_session.flush()

    assert decision.status == ReceiveDecisionStatus.DECIDED
    assert decision.decision == choice
    assert decision.decided_by_name == CREATOR_NAME
    assert decision.decided_at is not None
    assert db_session.query(ShippingOutRequest).filter(ShippingOutRequest.project_id == project.id).count() == 0


def test_somebody_elses_decision_is_refused_and_an_admin_may_still_clear_it(db_session):
    """The admin override is the escape hatch for the person who raised the PO having left - without
    it their decisions sit pending forever with nobody able to answer them."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    record = _receive(db_session, po, li, 3)
    decision = _decision_for(db_session, record)

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.decide_receive_decision(
            db_session,
            decision.id,
            ReceiveDecisionChoice.KEEP_IN_INVENTORY,
            STRANGER,
            "Sam Stranger",
            None,
            actor_is_admin=False,
        )
    assert excinfo.value.code == "CONFLICT"

    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.KEEP_IN_INVENTORY,
        STRANGER,
        "Sam Stranger",
        None,
        actor_is_admin=True,
    )
    assert decision.status == ReceiveDecisionStatus.DECIDED


def test_a_decision_is_answered_once(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    record = _receive(db_session, po, li, 3)
    decision = _decision_for(db_session, record)
    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.KEEP_IN_INVENTORY,
        CREATOR,
        CREATOR_NAME,
        None,
        actor_is_admin=False,
    )
    db_session.flush()

    with pytest.raises(AppError) as excinfo:
        warehouse_repository.decide_receive_decision(
            db_session,
            decision.id,
            ReceiveDecisionChoice.SHIP_OUT,
            CREATOR,
            CREATOR_NAME,
            None,
            actor_is_admin=False,
        )

    assert excinfo.value.code == "INVALID_STATE_TRANSITION"


def test_an_answered_decision_leaves_the_pending_queue(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    record = _receive(db_session, po, li, 3)
    decision = _decision_for(db_session, record)

    assert len(warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, None)) == 1

    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.SHIP_OUT,
        CREATOR,
        CREATOR_NAME,
        None,
        actor_is_admin=False,
    )
    db_session.flush()

    assert warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, None) == []


# --- the question moves to draft time (#499) ---------------------------------------------------
#
# It used to be raised only once the warehouse manager had approved, which meant the hardware was
# already booked and put away before its owner was asked whether it should have gone straight back
# out. Raising it at the count gives them the whole approval window, and lets a SHIP_OUT answer take
# the delivery out of the manager's queue entirely.


def _packing_slip(session, po):
    """#504: a draft is a count made against a piece of paper, so every one needs a slip on its PO."""
    from app.models.enums import PODocumentType
    from app.models.purchase_order import PODocument

    doc = PODocument(
        id=uuid.uuid4(),
        po_id=po.id,
        file_name="slip.pdf",
        content_type="application/pdf",
        file_size=12,
        document_type=PODocumentType.PACKING_SLIP,
        s3_key=f"po-documents/{po.id}/slip-{uuid.uuid4().hex[:8]}.pdf",
    )
    session.add(doc)
    session.flush()
    return doc


def _draft(session, po, li, quantity=3):
    return warehouse_repository.create_receive_draft(
        session,
        po.id,
        [{"po_line_item_id": li.id, "quantity_received": quantity, "locations": []}],
        "u_counter",
        "Wendy Warehouse",
        packing_slip_document_id=_packing_slip(session, po).id,
    )


def _decision_for_draft(session, draft):
    return session.scalars(select(ReceiveDecision).where(ReceiveDecision.receive_draft_id == draft.id)).first()


def test_submitting_a_count_raises_the_question_before_anyone_approves(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    draft = _draft(db_session, po, li)
    db_session.flush()

    decision = _decision_for_draft(db_session, draft)
    assert decision is not None
    assert decision.status == ReceiveDecisionStatus.PENDING
    assert decision.target_user_id == CREATOR
    # Nothing has reached GP, so there is no receive record to point at yet.
    assert decision.receive_record_id is None


def test_a_stock_po_draft_asks_nothing(db_session):
    """ "Which project's inventory" is not a question you can ask without a project."""
    po, li = _make_po(db_session, None)

    draft = _draft(db_session, po, li)
    db_session.flush()

    assert _decision_for_draft(db_session, draft) is None


def test_the_draft_question_is_raised_once_however_many_lines_it_covered(db_session):
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    draft = _draft(db_session, po, li)
    db_session.flush()
    # Re-running the create is what an idempotent retry does; it must not raise a second question.
    from app.repositories.warehouse.receive_decisions import create_decision_for_draft

    again = create_decision_for_draft(db_session, po, draft.id, total_quantity=3)
    db_session.flush()

    assert again.id == _decision_for_draft(db_session, draft).id
    rows = db_session.scalars(select(ReceiveDecision).where(ReceiveDecision.receive_draft_id == draft.id)).all()
    assert len(list(rows)) == 1


def test_approval_stamps_the_receive_onto_the_question_the_count_already_raised(db_session):
    """One delivery, one question. The booking fills in the record rather than asking again."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li)
    db_session.flush()
    raised = _decision_for_draft(db_session, draft)

    record = warehouse_repository.create_receive(
        db_session,
        po.id,
        "Wendy Warehouse",
        [{"po_line_item_id": li.id, "quantity_received": 3, "locations": []}],
        receipt_number="RCT000999",
        receive_draft_id=draft.id,
    )
    db_session.flush()

    all_rows = list(db_session.scalars(select(ReceiveDecision).where(ReceiveDecision.po_id == po.id)).all())
    assert len(all_rows) == 1
    assert all_rows[0].id == raised.id
    assert all_rows[0].receive_record_id == record.id
    assert all_rows[0].receive_draft_id == draft.id


def test_an_answer_given_before_approval_survives_it(db_session):
    """Approval is the manager confirming the count, not a re-opening of somebody else's question."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li)
    db_session.flush()
    decision = _decision_for_draft(db_session, draft)

    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.SHIP_OUT,
        CREATOR,
        "Paula Purchasing",
        lambda _uid: None,
        actor_is_admin=False,
    )
    db_session.flush()

    warehouse_repository.create_receive(
        db_session,
        po.id,
        "Wendy Warehouse",
        [{"po_line_item_id": li.id, "quantity_received": 3, "locations": []}],
        receipt_number="RCT000999",
        receive_draft_id=draft.id,
    )
    db_session.flush()
    db_session.refresh(decision)

    assert decision.status == ReceiveDecisionStatus.DECIDED
    assert decision.decision == ReceiveDecisionChoice.SHIP_OUT
    assert decision.decided_by_name == "Paula Purchasing"


def test_a_receive_booked_with_no_draft_still_raises_its_own_question(db_session):
    """The outbox worker draining a queued receipt reaches the booking with no draft to stamp. A
    booked receive with no question attached would strand the decision entirely."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)

    record = _receive(db_session, po, li)
    db_session.flush()

    decision = _decision_for(db_session, record)
    assert decision is not None
    assert decision.receive_draft_id is None


def test_the_pending_read_returns_draft_stage_questions_too(db_session):
    """The card is the same at both stages; only the GP receipt number is missing before approval."""
    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li, quantity=4)
    db_session.flush()

    rows = warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, None)
    matching = [r for r in rows if r[0].receive_draft_id == draft.id]
    assert len(matching) == 1
    _decision, _po, receive_record, returned_draft = matching[0]
    assert receive_record is None
    assert returned_draft.id == draft.id
    assert sum(li.quantity_received for li in returned_draft.line_items) == 4


def test_only_a_manager_or_the_ship_out_decider_may_book_a_draft(db_session):
    """The approve gate moved out of ROOT_FIELD_POLICY because it is no longer a property of the
    field alone (#499): a Warehouse Manager may book any draft, and the PO creator who answered
    SHIP_OUT may book that one. The check is against the decision row, never against the client."""
    from app.schemas.warehouse import _may_book_draft

    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li)
    db_session.flush()
    decision = _decision_for_draft(db_session, draft)

    # Undecided: the creator has said nothing, so the manager's queue is still the only way in.
    assert not _may_book_draft(decision, CREATOR, is_manager=False)

    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.SHIP_OUT,
        CREATOR,
        "Paula Purchasing",
        lambda _uid: None,
        actor_is_admin=False,
    )
    db_session.flush()

    # The decider may now book it, and nobody else may on their behalf.
    assert _may_book_draft(decision, CREATOR, is_manager=False)
    assert not _may_book_draft(decision, "u_someone_else", is_manager=False)

    # A manager always may, whatever the answer is - and even with no decision at all.
    assert _may_book_draft(decision, "u_someone_else", is_manager=True)
    assert _may_book_draft(None, "u_someone_else", is_manager=True)


def test_keeping_it_does_not_let_the_decider_book_it(db_session):
    """KEEP says this belongs in the warehouse's care, so the manager's approval is exactly the step
    that still applies."""
    from app.schemas.warehouse import _may_book_draft

    project = _make_project(db_session)
    po, li = _make_po(db_session, project.id)
    draft = _draft(db_session, po, li)
    db_session.flush()
    decision = _decision_for_draft(db_session, draft)

    warehouse_repository.decide_receive_decision(
        db_session,
        decision.id,
        ReceiveDecisionChoice.KEEP_IN_INVENTORY,
        CREATOR,
        "Paula Purchasing",
        lambda _uid: None,
        actor_is_admin=False,
    )
    db_session.flush()

    assert not _may_book_draft(decision, CREATOR, is_manager=False)
