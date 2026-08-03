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

    assert {po.id for _d, po, _rr in rows} == {stamped_po.id, legacy_po.id}


def test_without_a_gp_buyer_identity_only_the_stamped_decisions_are_owed(db_session):
    project = _make_project(db_session)
    stamped_po, stamped_li = _make_po(db_session, project.id, created_by=CREATOR)
    legacy_po, legacy_li = _make_po(db_session, project.id, created_by=None, buyer_id="PAULA")
    _receive(db_session, stamped_po, stamped_li, 1)
    _receive(db_session, legacy_po, legacy_li, 1)

    rows = warehouse_repository.get_pending_decisions_for_user(db_session, CREATOR, None)

    assert {po.id for _d, po, _rr in rows} == {stamped_po.id}


@pytest.mark.parametrize("choice", [ReceiveDecisionChoice.KEEP_IN_INVENTORY, ReceiveDecisionChoice.SHIP_OUT])
def test_answering_records_the_choice_and_nothing_else(db_session, choice):
    """SHIP_OUT deliberately creates no shipping-out request: only the schedule knows which opening a
    fungible quantity is owed to, so the frontend deep-links into Start a Task from here."""
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
