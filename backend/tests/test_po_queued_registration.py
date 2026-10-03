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
        row = _queue_registration(session, po.id)
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
