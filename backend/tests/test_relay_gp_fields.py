"""PO GP-sync fields (uc nexus <-> relay, schema + api changes)."""

from app.models.enums import POStatus
from app.repositories import po_repository


def _line_item() -> dict:
    return {
        "hardware_category": "HINGE",
        "product_code": "AB123",
        "ordered_quantity": 1,
        "unit_cost": 12.50,
        "classification": None,
        "order_as": "ML2010",
    }


def test_create_po_stores_cost_code(db_session):
    po = po_repository.create_po(db_session, line_items=[_line_item()], cost_code="  210-200-2  ")
    db_session.refresh(po)
    assert po.cost_code == "210-200-2"


def test_create_po_with_gp_fields_lands_gp_registered(db_session):
    # A GP-first create stamps GP's number + company and advances to GP_REGISTERED in one commit,
    # so there is no numberless DRAFT window (the old create + record_po_gp_sync two-call shape).
    #
    # GP-registration gates on gp_vendor_id and nothing else (#200, #509): the GP vendor picked live
    # from PM00200 is the only vendor a PO has.
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item()],
        po_number="  PO123456 ",
        gp_company="TUBC",
        gp_vendor_id="GPV1",
        vendor_name_snapshot="Acme",
    )
    db_session.refresh(po)
    assert po.po_number == "PO123456"
    assert po.gp_company == "TUBC"
    assert po.status == POStatus.GP_REGISTERED
    assert po.ordered_at is not None


def test_create_po_without_gp_fields_stays_draft(db_session):
    po = po_repository.create_po(db_session, line_items=[_line_item()])
    db_session.refresh(po)
    assert po.po_number is None
    assert po.gp_company is None
    assert po.status == POStatus.DRAFT


def test_create_po_stores_gp_vendor_snapshot(db_session):
    # issue #200: the GP vendor is picked live (gpVendors) at push time, not read from a local mirror -
    # its id + name are frozen onto the PO for display.
    po = po_repository.create_po(
        db_session,
        line_items=[_line_item()],
        po_number="PO999000",
        gp_company="TUBC",
        gp_vendor_id="  GPV42  ",
        vendor_name_snapshot="  Ingersoll Hardware  ",
    )
    db_session.refresh(po)
    assert po.gp_vendor_id == "GPV42"
    assert po.vendor_name_snapshot == "Ingersoll Hardware"
    assert po.status == POStatus.GP_REGISTERED
