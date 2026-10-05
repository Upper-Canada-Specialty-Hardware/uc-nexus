"""A queued PO registration is not pushed once its draft has changed (#1599).

A registration's payload is the draft as it stood when the registration was built, and the save after GP
answers writes those lines, costs and project back. #1595 refuses edits while the registration is pending
or in flight; this covers what that cannot see - an edit made while a failed registration waits for its
retry, and one made during the relay attempt that ended in queueing it. Never touches GP: the relay call
is stubbed."""

import asyncio
import uuid
from decimal import Decimal

from app.models.enums import NotificationType, POStatus
from app.models.notification import Notification
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import gp_outbox_repository, po_repository
from app.services import gp_outbox_worker

CHANGED = "changed after its registration was queued"


def _queued(*, row_status="IN_FLIGHT", with_digest=True):
    """A committed draft with one line on a project, and its registration queued with the draft's digest."""
    from app.database import SessionLocal

    with SessionLocal() as session:
        project = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="T", company="TUBC")
        session.add(project)
        session.flush()
        po = PurchaseOrder(
            id=uuid.uuid4(),
            request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
            project_id=project.id,
            status=POStatus.DRAFT,
            company="TUBC",
        )
        session.add(po)
        session.flush()
        line = POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category="HINGE",
            product_code="HG-100",
            ordered_quantity=4,
            received_quantity=0,
            unit_cost=Decimal("12.00"),
        )
        session.add(line)
        session.flush()
        context = {"po_id": str(po.id)}
        if with_digest:
            context["registration_digest"] = po_repository.registration_digest(session, po.id)
        row = gp_outbox_repository.enqueue(
            session,
            idempotency_key=str(uuid.uuid4()),
            op="register_po_in_gp",
            relay_op="create_po",
            company="TUBC",
            payload={"header": {}},
            persist_context=context,
            entity_key=f"po:{po.id}",
            label="Register PO in GP",
            project_id=project.id,
        )
        row.status = row_status
        session.commit()
        return po.id, line.id, row.id


def _set_line_cost(line_id, cost: str) -> None:
    from app.database import SessionLocal

    with SessionLocal() as session:
        session.get(POLineItem, line_id).unit_cost = Decimal(cost)
        session.commit()


def _relay(monkeypatch, calls):
    async def _call(company, op, payload=None, timeout=30.0):
        calls.append(op)
        return {"po_number": "PO0000901", "company": "TUBC"}

    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "relay_call", _call)
    monkeypatch.setattr(gp_outbox_worker.relay_gateway, "_features", frozenset({"create_po_idempotency"}))
    monkeypatch.setitem(gp_outbox_worker._HANDLERS, "register_po_in_gp", lambda *a: None)

    async def _read_back(company, po_id):
        return "PO0000901"

    monkeypatch.setattr(gp_outbox_worker.gp_processing, "run_gp_processing", _read_back)


def _row(row_id):
    from app.database import SessionLocal

    with SessionLocal() as session:
        row = gp_outbox_repository.get_entry(session, row_id)
        return row.status, row.last_error, row.failure_kind


def _failure_notices(po_id) -> int:
    from app.database import SessionLocal

    with SessionLocal() as session:
        project_id = session.get(PurchaseOrder, po_id).project_id
        return (
            session.query(Notification)
            .filter(
                Notification.project_id == project_id,
                Notification.type == NotificationType.GP_WRITE_FAILED,
            )
            .count()
        )


def _cleanup(po_id, row_id):
    from app.database import SessionLocal
    from app.models.gp_outbox import GpWriteOutbox

    with SessionLocal() as session:
        row = session.get(GpWriteOutbox, row_id)
        if row is not None:
            session.delete(row)
        for line in session.query(POLineItem).filter(POLineItem.po_id == po_id).all():
            session.delete(line)
        po = session.get(PurchaseOrder, po_id)
        project_id = po.project_id if po is not None else None
        if po is not None:
            session.delete(po)
        if project_id is not None:
            session.query(Notification).filter(Notification.project_id == project_id).delete()
            session.flush()
            project = session.get(Project, project_id)
            if project is not None:
                session.delete(project)
        session.commit()


def test_a_registration_whose_draft_changed_is_not_pushed(_migrate_database, monkeypatch):
    po_id, line_id, row_id = _queued()
    calls: list = []
    _relay(monkeypatch, calls)
    try:
        _set_line_cost(line_id, "10.50")

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert calls == []  # nothing reached GP
        # Still a draft that wants registering: held as FAILED (on the held-registrations panel) and
        # announced, not closed quietly as a cancelled PO's is.
        status, error, kind = _row(row_id)
        assert status == "FAILED" and kind == "po_changed"
        assert CHANGED in error and "register it again" in error
        assert _failure_notices(po_id) == 1
    finally:
        _cleanup(po_id, row_id)


def test_an_unchanged_draft_is_still_pushed(_migrate_database, monkeypatch):
    po_id, _line_id, row_id = _queued()
    calls: list = []
    _relay(monkeypatch, calls)
    try:
        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert calls == ["create_po"]
        assert _row(row_id)[0] == "SUCCEEDED"
    finally:
        _cleanup(po_id, row_id)


def test_a_failed_registration_retried_after_an_edit_is_not_pushed(_migrate_database, monkeypatch):
    from app.database import SessionLocal

    po_id, line_id, row_id = _queued(row_status="FAILED")
    calls: list = []
    _relay(monkeypatch, calls)
    try:
        # A failed registration does not hold the draft, so the buyer can change it before a retry.
        _set_line_cost(line_id, "10.50")
        with SessionLocal() as session:
            assert gp_outbox_repository.retry_entry(session, row_id) is not None
            gp_outbox_repository.get_entry(session, row_id).status = "IN_FLIGHT"  # as the worker's claim
            session.commit()

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert calls == []
        status, error, _kind = _row(row_id)
        assert status == "FAILED" and CHANGED in error
    finally:
        _cleanup(po_id, row_id)


def test_a_registration_queued_before_the_digest_still_drains(_migrate_database, monkeypatch):
    po_id, line_id, row_id = _queued(with_digest=False)
    calls: list = []
    _relay(monkeypatch, calls)
    try:
        _set_line_cost(line_id, "10.50")

        asyncio.run(gp_outbox_worker._drain_one(row_id))

        assert calls == ["create_po"]
    finally:
        _cleanup(po_id, row_id)


def test_the_digest_ignores_how_money_is_written(db_session):
    """12, 12.00 and 12.00000 are one price - a resave that only changes the scale is not a change."""
    po = PurchaseOrder(id=uuid.uuid4(), request_number="PO-REQ-DIG", status=POStatus.DRAFT, company="TUBC")
    db_session.add(po)
    db_session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=4,
        received_quantity=0,
        unit_cost=Decimal("12.00"),
    )
    db_session.add(line)
    db_session.flush()
    before = po_repository.registration_digest(db_session, po.id)

    line.unit_cost = Decimal("12.00000")
    db_session.flush()
    assert po_repository.registration_digest(db_session, po.id) == before

    line.order_as = "ML2010"
    db_session.flush()
    assert po_repository.registration_digest(db_session, po.id) != before
