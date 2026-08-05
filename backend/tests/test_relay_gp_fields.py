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


# --- #509: registering in GP is the only way a PO becomes GP_REGISTERED --------------------------


def test_no_mutation_can_fake_a_gp_registered_po(db_session):
    """`markPoAsOrdered` is gone (#509). It flipped a DRAFT to GP_REGISTERED without ever contacting
    GP, gated only on the local vendor link - so its rule was "you may fabricate a GP-registered PO
    provided you attach an invented vendor", which is the thing this change removes. It had no
    frontend caller either: nothing reachable by clicking could produce that state, so it was a
    seeding backdoor rather than a real path.

    GP_REGISTERED now comes from exactly two places, both of which carry a real PM00200 vendor:
    `register_po_in_gp` after the relay push, and `create_po`'s GP-first branch for callers already
    holding a GP result."""
    assert not hasattr(po_repository, "mark_po_as_ordered")

    draft = po_repository.create_po(db_session, line_items=[_line_item()])
    po_repository.update_po(db_session, draft.id, po_number="PO777001")
    db_session.flush()
    db_session.refresh(draft)
    # A PO number alone never advances the status - only a GP round trip does.
    assert draft.status == POStatus.DRAFT
    assert draft.gp_vendor_id is None
