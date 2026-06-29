"""Vendor sync + PO GP-sync fields (uc nexus <-> relay, schema + api changes)."""

import uuid

from app.models.enums import POStatus
from app.models.vendor import Vendor
from app.repositories import po_repository, vendor_repository


def _make_vendor(session, name: str) -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=name)
    session.add(v)
    session.flush()
    return v


def _line_item() -> dict:
    return {
        "hardware_category": "HINGE",
        "product_code": "AB123",
        "ordered_quantity": 1,
        "unit_cost": 12.50,
        "classification": None,
        "order_as": "ML2010",
    }


def test_sync_gp_vendors_matches_by_name_case_insensitive(db_session):
    v = _make_vendor(db_session, f"Ingersoll-{uuid.uuid4().hex[:6]}")
    result = vendor_repository.sync_gp_vendors(db_session, [{"gp_vendor_id": "ING100", "vendor_name": v.name.upper()}])
    db_session.refresh(v)
    assert v.gp_vendor_id == "ING100"
    assert result["matched"] == [v.name]
    assert result["unmatched_gp"] == []


def test_sync_gp_vendors_reports_unmatched(db_session):
    result = vendor_repository.sync_gp_vendors(
        db_session, [{"gp_vendor_id": "ZZZ999", "vendor_name": f"NoSuchVendor-{uuid.uuid4().hex[:6]}"}]
    )
    assert result["matched"] == []
    assert len(result["unmatched_gp"]) == 1


def test_create_po_stores_cost_code(db_session):
    v = _make_vendor(db_session, f"Acme-{uuid.uuid4().hex[:6]}")
    po = po_repository.create_po(db_session, line_items=[_line_item()], vendor_id=v.id, cost_code="  210-200-2  ")
    db_session.refresh(po)
    assert po.cost_code == "210-200-2"


def test_create_po_with_gp_fields_lands_gp_registered(db_session):
    # A GP-first create stamps GP's number + company and advances to GP_REGISTERED in one commit,
    # so there is no numberless DRAFT window (the old create + record_po_gp_sync two-call shape).
    v = _make_vendor(db_session, f"Acme-{uuid.uuid4().hex[:6]}")
    po = po_repository.create_po(
        db_session, line_items=[_line_item()], vendor_id=v.id, po_number="  PO123456 ", gp_company="TUBC"
    )
    db_session.refresh(po)
    assert po.po_number == "PO123456"
    assert po.gp_company == "TUBC"
    assert po.status == POStatus.GP_REGISTERED
    assert po.ordered_at is not None


def test_create_po_without_gp_fields_stays_draft(db_session):
    v = _make_vendor(db_session, f"Acme-{uuid.uuid4().hex[:6]}")
    po = po_repository.create_po(db_session, line_items=[_line_item()], vendor_id=v.id)
    db_session.refresh(po)
    assert po.po_number is None
    assert po.gp_company is None
    assert po.status == POStatus.DRAFT
