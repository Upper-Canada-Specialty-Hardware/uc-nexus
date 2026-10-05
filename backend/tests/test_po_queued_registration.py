"""A PO whose GP registration is queued, and the smaller PO edit rules beside it (#1156).

While the relay is down a registration waits on the outbox and the PO stays a Draft. The Draft check
alone then let a second registration queue under a fresh key (two GP POs on drain), and let a cancel
drop a PO that the queue went on to create in GP. Never touches GP: the relay call is stubbed."""

import asyncio
import uuid
from decimal import Decimal

import pytest

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import PODocument, POLineItem, PurchaseOrder
from app.repositories import gp_outbox_repository, po_repository
from app.services import gp_outbox_worker


def _project(session, company="TUBC") -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test", company=company)
    session.add(p)
    session.flush()
    return p


def _po(session, *, status=POStatus.DRAFT, project=None, company="TUBC") -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id if project else None,
        status=status,
        company=company,
    )
    session.add(po)
    session.flush()
    return po


def _queue_registration(session, po_id, key=None, status="PENDING"):
    row = gp_outbox_repository.enqueue(
        session,
        idempotency_key=key or str(uuid.uuid4()),
        op="register_po_in_gp",
        relay_op="create_po",
        company="TUBC",
        payload={"header": {}},
        persist_context={"po_id": str(po_id)},
        entity_key=f"po:{po_id}",
        label="Register PO in GP",
    )
    row.status = status
    session.flush()
    return row


# --- #1165 / #1166: a queued registration ---


def test_queued_registration_is_found_for_pending_and_in_flight_only(db_session):
    po = _po(db_session)
    assert gp_outbox_repository.queued_po_registration(db_session, po.id) is None

    row = _queue_registration(db_session, po.id, status="IN_FLIGHT")
    assert gp_outbox_repository.queued_po_registration(db_session, po.id).id == row.id

    row.status = "FAILED"
    db_session.flush()
    assert gp_outbox_repository.queued_po_registration(db_session, po.id) is None


def test_the_same_attempts_key_is_not_a_second_registration(db_session):
    po = _po(db_session)
    _queue_registration(db_session, po.id, key="k-1")
    assert gp_outbox_repository.queued_po_registration(db_session, po.id, exclude_key="k-1") is None
    assert gp_outbox_repository.queued_po_registration(db_session, po.id, exclude_key="k-2") is not None


def test_a_draft_whose_registration_is_queued_cannot_be_cancelled(db_session):
    po = _po(db_session)
    _queue_registration(db_session, po.id)
    with pytest.raises(InvalidStateTransitionError, match="queued"):
        po_repository.cancel_po(db_session, po.id)
    assert po.status == POStatus.DRAFT
    assert po.deleted_at is None


def test_a_draft_with_no_queued_registration_still_cancels(db_session):
    po = _po(db_session)
    _queue_registration(db_session, po.id, status="FAILED")
    assert po_repository.cancel_po(db_session, po.id).status == POStatus.CANCELLED


def _committed_po_with_queued_registration(status=POStatus.DRAFT, deleted=False):
    from datetime import datetime

    from app.database import SessionLocal

    with SessionLocal() as session:
        po = _po(session, status=status)
        if deleted:
            po.deleted_at = datetime.utcnow()
        row = _queue_registration(session, po.id, status="IN_FLIGHT")  # as the worker's claim leaves it
        session.commit()
        return po.id, row.id


def _cleanup(po_id, row_id):
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    with SessionLocal() as session:
        for model, pk in ((GpWriteOutbox, row_id), (PurchaseOrder, po_id)):
            obj = session.get(model, pk)
            if obj is not None:
                session.delete(obj)
        session.commit()


@pytest.mark.parametrize(
    ("status", "deleted"),
    [(POStatus.GP_REGISTERED, False), (POStatus.DRAFT, True)],
    ids=["registered-meanwhile", "cancelled-meanwhile"],
)
def test_the_worker_does_not_push_a_registration_whose_po_left_draft(_migrate_database, monkeypatch, status, deleted):
    from app.database import SessionLocal

    po_id, row_id = _committed_po_with_queued_registration(status=status, deleted=deleted)
    calls = []

    async def _call(company, op, payload=None, timeout=30.0):
        calls.append(op)
        return {"po_number": "0000999", "company": "TUBC"}

    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "relay_call", _call)
    try:
        asyncio.run(gp_outbox_worker._drain_one(row_id))
        assert calls == []  # nothing reached GP
        with SessionLocal() as session:
            row = gp_outbox_repository.get_entry(session, row_id)
            assert row.status == "CANCELLED"
            assert "nothing was sent to GP" in row.last_error or "not sent to GP" in row.last_error
    finally:
        _cleanup(po_id, row_id)


# --- #1170: updatePo and the project ---


def test_update_po_gives_a_projectless_draft_a_project_of_its_company(db_session):
    po = _po(db_session)
    project = _project(db_session)
    assert po_repository.update_po(db_session, po.id, project_id=project.id).project_id == project.id


def test_update_po_refuses_a_project_from_another_company(db_session):
    po = _po(db_session)
    other = _project(db_session, company="UBC")
    with pytest.raises(ValidationError) as e:
        po_repository.update_po(db_session, po.id, project_id=other.id)
    assert e.value.field == "project_id"


@pytest.mark.parametrize("status", [POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED])
def test_update_po_refuses_to_move_a_registered_po(db_session, status):
    a, b = _project(db_session), _project(db_session)
    po = _po(db_session, status=status, project=a)
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, project_id=b.id)
    assert po.project_id == a.id


def test_update_po_refuses_to_move_a_draft_off_its_project(db_session):
    a, b = _project(db_session), _project(db_session)
    po = _po(db_session, project=a)
    with pytest.raises(InvalidStateTransitionError):
        po_repository.update_po(db_session, po.id, project_id=b.id)
    # Re-sending the project it already has is not a move.
    assert po_repository.update_po(db_session, po.id, project_id=a.id).project_id == a.id


# --- #1172: a no-charge line ---


def _line(session, po) -> POLineItem:
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=1,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
    )
    session.add(line)
    session.flush()
    return line


def test_a_draft_line_can_be_set_to_no_charge(db_session):
    line = _line(db_session, _po(db_session))
    assert po_repository.update_line_item_unit_cost(db_session, line.id, 0).unit_cost == 0


def test_a_negative_unit_cost_is_refused(db_session):
    line = _line(db_session, _po(db_session))
    with pytest.raises(ValidationError):
        po_repository.update_line_item_unit_cost(db_session, line.id, -1)


# --- #1171: the stored file outlives a failed commit ---


def test_deleting_a_document_leaves_the_file_to_the_caller(db_session, monkeypatch):
    from app.models.enums import PODocumentType
    from app.services import storage

    def _boom(key):
        raise AssertionError("the repository must not touch storage before the commit")

    monkeypatch.setattr(storage, "delete_file", _boom)
    po = _po(db_session)
    doc = PODocument(
        id=uuid.uuid4(),
        po_id=po.id,
        file_name="quote.pdf",
        content_type="application/pdf",
        file_size=10,
        document_type=PODocumentType.MISCELLANEOUS,
        s3_key=f"po/{po.id}/quote.pdf",
    )
    db_session.add(doc)
    db_session.flush()

    assert po_repository.delete_po_document(db_session, doc.id) == f"po/{po.id}/quote.pdf"
    db_session.flush()
    assert db_session.get(PODocument, doc.id) is None


# --- #1165 / #1166 review: the check holds under the PO's row lock where the write is queued ---


def _committed_draft():
    from app.database import SessionLocal

    with SessionLocal() as session:
        po = _po(session)
        session.commit()
        return po.id


def _enqueue_registration(po_id, key):
    from app.services import gp_outbox_enqueue

    return gp_outbox_enqueue.enqueue(
        idempotency_key=key,
        op="register_po_in_gp",
        relay_op="create_po",
        company="TUBC",
        payload={"header": {}},
        persist_context={"po_id": str(po_id)},
        entity_key=f"po:{po_id}",
        label="Register PO in GP",
    )


def _cleanup_po(po_id):
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    with SessionLocal() as session:
        for row in session.query(GpWriteOutbox).filter(GpWriteOutbox.entity_key == f"po:{po_id}").all():
            session.delete(row)
        po = session.get(PurchaseOrder, po_id)
        if po is not None:
            session.delete(po)
        session.commit()


def test_a_second_tab_cannot_queue_another_registration(_migrate_database):
    po_id = _committed_draft()
    key = str(uuid.uuid4())
    try:
        first = _enqueue_registration(po_id, key)
        assert _enqueue_registration(po_id, key) == first  # the same attempt is the same entry
        with pytest.raises(InvalidStateTransitionError, match="already queued"):
            _enqueue_registration(po_id, str(uuid.uuid4()))
    finally:
        _cleanup_po(po_id)


def test_a_cancelled_po_cannot_be_queued(_migrate_database):
    from app.database import SessionLocal

    po_id = _committed_draft()
    try:
        with SessionLocal() as session:
            po_repository.cancel_po(session, po_id)
            session.commit()
        with pytest.raises(InvalidStateTransitionError, match="no longer a Draft"):
            _enqueue_registration(po_id, str(uuid.uuid4()))
    finally:
        _cleanup_po(po_id)


def test_a_cancel_and_a_queue_cannot_cross(_migrate_database):
    """The cancel holds the PO's row lock; the queue waits for it, then sees the cancelled PO."""
    import threading

    from app.database import SessionLocal

    po_id = _committed_draft()
    outcome = {}

    def _queue():
        try:
            outcome["entry"] = _enqueue_registration(po_id, str(uuid.uuid4()))
        except InvalidStateTransitionError as e:
            outcome["refused"] = str(e)

    try:
        with SessionLocal() as session:
            po_repository.cancel_po(session, po_id)  # lock taken, not yet committed
            worker = threading.Thread(target=_queue)
            worker.start()
            worker.join(timeout=1.0)
            assert worker.is_alive(), "the queue must wait on the cancel's lock"
            session.commit()
        worker.join(timeout=10.0)
        assert "refused" in outcome and "entry" not in outcome
    finally:
        _cleanup_po(po_id)


# --- #1595: a queued registration posts its snapshot, so edits it would overwrite are refused ---


def _line(session, po) -> POLineItem:
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code=f"HG-{uuid.uuid4().hex[:4]}",
        ordered_quantity=4,
        unit_cost=Decimal("12.00"),
    )
    session.add(li)
    session.flush()
    return li


def test_a_queued_drafts_line_cost_and_order_as_cannot_change(db_session):
    from app.errors import ConflictError

    po = _po(db_session)
    li = _line(db_session, po)
    _queue_registration(db_session, po.id)

    with pytest.raises(ConflictError, match="registration is queued for GP"):
        po_repository.update_line_item_unit_cost(db_session, li.id, 10.5)
    with pytest.raises(ConflictError, match="registration is queued for GP"):
        po_repository.update_line_item_order_as(db_session, li.id, "ML2010")


def test_a_queued_drafts_shipping_cost_cannot_change_but_its_notes_can(db_session):
    from app.errors import ConflictError

    po = _po(db_session)
    _queue_registration(db_session, po.id)

    with pytest.raises(ConflictError, match="registration is queued for GP"):
        po_repository.update_po(db_session, po.id, shipping_cost=85)

    saved = po_repository.update_po(db_session, po.id, notes="call before delivery", vendor_quote_number="Q-77")
    assert saved.notes == "call before delivery"
    assert saved.vendor_quote_number == "Q-77"
    # A resent unchanged value is not a change.
    po_repository.update_po(db_session, po.id, shipping_cost=None)


def test_once_the_queue_drained_the_draft_rules_apply_again(db_session):
    po = _po(db_session)
    li = _line(db_session, po)
    row = _queue_registration(db_session, po.id)
    row.status = "FAILED"
    db_session.flush()

    po_repository.update_line_item_unit_cost(db_session, li.id, 10.5)
    assert li.unit_cost == 10.5
