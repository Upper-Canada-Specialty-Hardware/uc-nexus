"""Upsert rules for the GP PO mirror (gp-owned-po mirror). DB-backed (db_session): convergence onto a
Nexus row without touching the overlay, GP-authoritative received qty, project matching, gp_line_ord
line matching, and the status-past-registration rule that preserves VENDOR_CONFIRMED."""

import uuid
from decimal import Decimal

import pytest

from app.models.enums import POOrigin, POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import gp_po_sync_repository as sync_repo

COMPANY = "TUBC"


def _line(ord_, item, qty, received=0, cancelled=0, unit_cost=10, job="J1"):
    return {
        "ord": ord_,
        "item": item,
        "itemdesc": f"{item} description",
        "qty": qty,
        "qty_cancelled": cancelled,
        "received": received,
        "unit_cost": unit_cost,
        "job": job,
        "line_status": 2,
    }


def _po(po_number, lines, *, source="work", vendor_id="V1", vendor_name="Acme", doc_date="2026-01-05"):
    return {
        "po_number": po_number,
        "gp_status": 2,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "doc_date": doc_date,
        "modified_at": "2026-01-06T09:00:00",
        "source_table": source,
        "lines": lines,
    }


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id="J1", description="Job One")
    db_session.add(p)
    db_session.flush()
    return p


def _project_map(db_session):
    from sqlalchemy import select

    return {job: pid for job, pid in db_session.execute(select(Project.project_id, Project.id)).all()}


def _get(db_session, po_number):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    return (
        db_session.scalars(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.line_items))
            .where(PurchaseOrder.gp_company == COMPANY, PurchaseOrder.po_number == po_number)
        )
        .unique()
        .first()
    )


def test_creates_gp_origin_po_matched_to_project(db_session, project):
    action = sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO100", [_line(16384, "IT1", 5, received=2)]), _project_map(db_session)
    )
    db_session.flush()
    assert action == "created"
    row = _get(db_session, "PO100")
    assert row.origin == POOrigin.GP
    assert row.request_number is None
    assert row.project_id == project.id
    assert row.status == POStatus.PARTIALLY_RECEIVED
    assert row.vendor_name_snapshot == "Acme"
    assert len(row.line_items) == 1
    line = row.line_items[0]
    assert line.gp_line_ord == 16384
    assert line.ordered_quantity == 5
    assert line.received_quantity == 2


def test_jobless_po_has_no_project(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO101", [_line(16384, "IT1", 3, job=None)]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO101").project_id is None


def test_disagreeing_jobs_go_to_stock(db_session, project):
    lines = [_line(16384, "IT1", 3, job="J1"), _line(32768, "IT2", 2, job="J2")]
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO102", lines), _project_map(db_session))
    db_session.flush()
    assert _get(db_session, "PO102").project_id is None


def test_received_qty_is_authoritative_on_reupsert(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO103", [_line(16384, "IT1", 5, received=1)]), pm)
    db_session.flush()
    first = _get(db_session, "PO103")
    first_line_id = first.line_items[0].id
    # A receipt posts inside GP; the next pass reports 4 received.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO103", [_line(16384, "IT1", 5, received=4)]), pm)
    db_session.flush()
    row = _get(db_session, "PO103")
    assert len(row.line_items) == 1
    assert row.line_items[0].id == first_line_id  # matched by gp_line_ord, not duplicated
    assert row.line_items[0].received_quantity == 4
    assert row.status == POStatus.PARTIALLY_RECEIVED


def test_converges_into_nexus_row_without_touching_overlay(db_session, project):
    # A Nexus-registered PO already exists for this (company, po_number), with overlay fields set.
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO200",
        request_number="PO-REQ-042",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        project_id=project.id,
        status=POStatus.VENDOR_CONFIRMED,
        cost_code="210-200-2",
        notes="hand-typed note",
        vendor_quote_number="Q-999",
    )
    db_session.add(nexus)
    db_session.flush()
    nexus_line = POLineItem(
        id=uuid.uuid4(),
        po_id=nexus.id,
        gp_line_ord=16384,
        hardware_category="HINGE",  # nexus schedule category
        product_code="HG-100",
        ordered_quantity=5,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
    )
    db_session.add(nexus_line)
    db_session.flush()

    # The mirror pass sees the same PO in GP with one receipt, still below full receipt.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO200", [_line(16384, "GP-ITEM", 5, received=2)]), _project_map(db_session)
    )
    db_session.flush()

    row = _get(db_session, "PO200")
    assert row.origin == POOrigin.NEXUS  # origin never flips
    # Nexus-only overlay untouched.
    assert row.request_number == "PO-REQ-042"
    assert row.cost_code == "210-200-2"
    assert row.notes == "hand-typed note"
    assert row.vendor_quote_number == "Q-999"
    # GP-owned facts converge: received is authoritative, status moves to partial.
    assert row.status == POStatus.PARTIALLY_RECEIVED
    assert row.line_items[0].received_quantity == 2
    # A Nexus line keeps its schedule categorization (not overwritten with the GP item).
    assert row.line_items[0].hardware_category == "HINGE"
    assert row.line_items[0].product_code == "HG-100"


def test_status_below_registration_preserves_vendor_confirmed(db_session, project):
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO201",
        request_number="PO-REQ-050",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        project_id=project.id,
        status=POStatus.VENDOR_CONFIRMED,
    )
    db_session.add(nexus)
    db_session.flush()
    # GP reports the PO with nothing received yet -> derived stage is GP_REGISTERED (baseline).
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO201", [_line(16384, "GP-ITEM", 5, received=0)]), _project_map(db_session)
    )
    db_session.flush()
    # The sync must not stomp the Nexus overlay status back down to GP_REGISTERED.
    assert _get(db_session, "PO201").status == POStatus.VENDOR_CONFIRMED


def test_gp_origin_project_repoints_but_nexus_does_not(db_session, project):
    # A second project the PO's job could match.
    other = Project(id=uuid.uuid4(), project_id="J9", description="Job Nine")
    db_session.add(other)
    db_session.flush()

    # GP-origin row: project follows the job match on every pass.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO300", [_line(16384, "IT1", 2, job="J1")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO300").project_id == project.id
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO300", [_line(16384, "IT1", 2, job="J9")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO300").project_id == other.id
