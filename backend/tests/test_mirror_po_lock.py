"""A GP PO sync pass reads the PO under its lock, so a receipt that commits mid-pass is kept (#1484).

The mirror used to find the PO and its lines unlocked, then decide received from that copy. A receipt
for the last units committing in between left the pass holding the pre-receipt count: the in-flight
check saw the draft already APPROVED, the floor was the stale value, and the update wrote GP's count over
the committed one. (The write only happens when GP's count differs from the stale copy - the ORM skips
an unchanged value - so GP here reports 8: a batch half posted, between Nexus's 6 and 10.) These run two
real sessions on separate connections, the receipt holding its transaction open while the pass arrives.
"""

import threading
import time
import uuid

import pytest

from app.database import SessionLocal
from app.models.audit_log import InventoryAuditLog
from app.models.enums import POStatus
from app.models.inventory import InventoryLocation
from app.models.notification import Notification, NotificationRead
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveLineItem, ReceiveRecord
from app.models.warehouse import Warehouse
from app.repositories import gp_po_sync_repository as sync_repo
from app.repositories import warehouse as warehouse_repository

# A company of its own, so the committed rows here never show up in another test's company-wide read.
COMPANY = f"M{uuid.uuid4().hex[:5].upper()}"


def _gp_po(po_number: str, job: str, received: int) -> dict:
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
                "job": job,
                "line_status": 2,
                "cost_code": None,
            }
        ],
    }


@pytest.fixture
def mirrored_po(_migrate_database):
    """A mirrored PO for 10, with 6 received in both systems, on a project with a primary warehouse."""
    job = f"J{uuid.uuid4().hex[:6]}"
    po_number = f"PO{uuid.uuid4().hex[:6]}"
    with SessionLocal() as s:
        project = Project(id=uuid.uuid4(), project_id=job, description="Mirror lock", company=COMPANY)
        s.add(project)
        s.add(
            Warehouse(
                id=uuid.uuid4(),
                company=COMPANY,
                name=f"Main {uuid.uuid4().hex[:6]}",
                code=uuid.uuid4().hex[:8],
                is_primary=True,
                is_active=True,
            )
        )
        s.flush()
        sync_repo.upsert_mirrored_po(s, COMPANY, _gp_po(po_number, job, 6), {job: project.id})
        s.commit()
        po = s.query(PurchaseOrder).filter(PurchaseOrder.po_number == po_number).one()
        assert po.status == POStatus.PARTIALLY_RECEIVED
        ctx = {
            "po_id": po.id,
            "line_id": po.line_items[0].id,
            "po_number": po_number,
            "job": job,
            "project_id": project.id,
        }
    yield ctx
    # Committed through real sessions, so removed by hand: other tests count receipts and inventory
    # across the whole database.
    with SessionLocal() as s:
        record_ids = [r.id for r in s.query(ReceiveRecord).filter(ReceiveRecord.po_id == ctx["po_id"])]
        s.query(InventoryLocation).filter(InventoryLocation.project_id == ctx["project_id"]).delete()
        s.query(InventoryAuditLog).filter(InventoryAuditLog.project_id == ctx["project_id"]).delete()
        notes = [n.id for n in s.query(Notification).filter(Notification.project_id == ctx["project_id"])]
        if notes:
            s.query(NotificationRead).filter(NotificationRead.notification_id.in_(notes)).delete()
            s.query(Notification).filter(Notification.id.in_(notes)).delete()
        if record_ids:
            s.query(ReceiveLineItem).filter(ReceiveLineItem.receive_record_id.in_(record_ids)).delete()
            s.query(ReceiveRecord).filter(ReceiveRecord.id.in_(record_ids)).delete()
        s.query(POLineItem).filter(POLineItem.po_id == ctx["po_id"]).delete()
        s.query(PurchaseOrder).filter(PurchaseOrder.id == ctx["po_id"]).delete()
        s.query(Warehouse).filter(Warehouse.company == COMPANY).delete()
        s.query(Project).filter(Project.id == ctx["project_id"]).delete()
        s.commit()


def _receive_last_units(ctx: dict, *, hold: float, errors: list) -> None:
    """Receive the last 4 units and keep the transaction open for `hold` seconds before committing."""
    try:
        with SessionLocal() as s:
            warehouse_repository.create_receive(
                s, ctx["po_id"], "Wendy", [{"po_line_item_id": ctx["line_id"], "quantity_received": 4, "locations": []}]
            )
            s.flush()
            time.sleep(hold)  # the sync pass arrives while this receipt is uncommitted
            s.commit()
    except BaseException as e:  # noqa: BLE001 - the test reports whatever the race raised
        errors.append(e)


def _mirror_pass(ctx: dict, *, start_after: float, errors: list) -> None:
    """A sync pass for the same PO, with GP reporting 8 - neither the stale 6 nor the receipt's 10."""
    time.sleep(start_after)
    try:
        with SessionLocal() as s:
            sync_repo.upsert_mirrored_po(
                s, COMPANY, _gp_po(ctx["po_number"], ctx["job"], 8), {ctx["job"]: ctx["project_id"]}
            )
            s.commit()
    except BaseException as e:  # noqa: BLE001
        errors.append(e)


def test_a_sync_pass_keeps_a_receipt_that_commits_while_it_reads_the_po(mirrored_po):
    errors: list = []
    threads = [
        threading.Thread(target=_receive_last_units, args=(mirrored_po,), kwargs={"hold": 1.0, "errors": errors}),
        threading.Thread(target=_mirror_pass, args=(mirrored_po,), kwargs={"start_after": 0.3, "errors": errors}),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)

    assert errors == []
    with SessionLocal() as s:
        line = s.get(POLineItem, mirrored_po["line_id"])
        po = s.get(PurchaseOrder, mirrored_po["po_id"])
        # The receipt's 4 stay on the line, and the PO it closed stays closed.
        assert line.received_quantity == 10
        assert po.status == POStatus.CLOSED
