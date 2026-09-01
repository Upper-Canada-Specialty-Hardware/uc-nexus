"""backOrderedItems names the vendor the way every other PO view does (#474).

A GP-registered PO carries its vendor as `vendor_name_snapshot` - the GP vendor picked live at push
time - and that is now the only vendor a PO has (#509). The back-order query used to select
`Vendor.name` off an outer join to the local vendors table, so the Back-Ordered Items grid showed a
blank vendor for the very PO that POs Awaiting Receipt named correctly on the same page.
"""

import uuid
from decimal import Decimal

from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import warehouse as warehouse_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _make_back_ordered_po(session, project_id, *, vendor_name_snapshot=None):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        vendor_name_snapshot=vendor_name_snapshot,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category="HINGE",
            product_code="HG-100",
            ordered_quantity=10,
            received_quantity=0,
            unit_cost=Decimal("1.00"),
            gp_line_ord=1,
        )
    )
    session.flush()
    return po


def _vendor_shown_for(session, po, project_id):
    rows = warehouse_repository.get_back_ordered_items(session, project_id)
    matches = [r for r in rows if r["po_line_item"].po_id == po.id]
    assert matches, f"expected a back-ordered row for {po.po_number}"
    return matches[0]["vendor_name"]


def test_gp_snapshot_names_the_vendor(db_session):
    """The regression: the grid showed nothing at all for a PO carrying only the snapshot."""
    project = _make_project(db_session)
    po = _make_back_ordered_po(db_session, project.id, vendor_name_snapshot="GALLERY SPECIALTY HARDWARE LTD")

    assert _vendor_shown_for(db_session, po, project.id) == "GALLERY SPECIALTY HARDWARE LTD"


def test_a_po_with_no_snapshot_names_no_vendor(db_session):
    """A DRAFT that was marked ordered without ever being pushed to GP has no vendor to name, and
    says so rather than inventing one (#509 - there is no local vendor row to fall back to)."""
    project = _make_project(db_session)
    po = _make_back_ordered_po(db_session, project.id)

    assert _vendor_shown_for(db_session, po, project.id) is None
