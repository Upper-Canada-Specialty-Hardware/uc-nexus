"""backOrderedItems names the vendor the way every other PO view does (#474).

A GP-registered PO carries its vendor as `vendor_name_snapshot` - the GP vendor picked live at push
time - and has no Nexus vendor row at all, which is the normal case now. The back-order query
selected only `Vendor.name` off its outer join, so the Back-Ordered Items grid showed a blank vendor
for the very PO that POs Awaiting Receipt named correctly on the same page. The read is now the same
coalesce `po_to_type` and the receiving history use: the snapshot first, the local vendor row only
for POs old enough to predate that column.
"""

import uuid
from decimal import Decimal

from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.vendor import Vendor
from app.repositories import warehouse as warehouse_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_back_ordered_po(session, project_id, *, vendor_id=None, vendor_name_snapshot=None):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        vendor_id=vendor_id,
        vendor_name_snapshot=vendor_name_snapshot,
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


def test_gp_snapshot_names_the_vendor_without_a_local_row(db_session):
    """The regression: a GP-registered PO has no Nexus vendor row, only the snapshot, and the grid
    showed nothing at all for it."""
    project = _make_project(db_session)
    po = _make_back_ordered_po(db_session, project.id, vendor_name_snapshot="GALLERY SPECIALTY HARDWARE LTD")

    assert _vendor_shown_for(db_session, po, project.id) == "GALLERY SPECIALTY HARDWARE LTD"


def test_a_pre_snapshot_po_still_falls_back_to_its_local_vendor_row(db_session):
    """POs old enough to predate the snapshot column keep being named off the joined vendor row."""
    project = _make_project(db_session)
    vendor = Vendor(id=uuid.uuid4(), name="Acme Doors")
    db_session.add(vendor)
    db_session.flush()
    po = _make_back_ordered_po(db_session, project.id, vendor_id=vendor.id)

    assert _vendor_shown_for(db_session, po, project.id) == "Acme Doors"


def test_the_snapshot_wins_over_the_local_row(db_session):
    """Same precedence as po_to_type: what was pushed to GP is what the PO is named by."""
    project = _make_project(db_session)
    vendor = Vendor(id=uuid.uuid4(), name="Stale Local Name")
    db_session.add(vendor)
    db_session.flush()
    po = _make_back_ordered_po(db_session, project.id, vendor_id=vendor.id, vendor_name_snapshot="GP VENDOR LTD")

    assert _vendor_shown_for(db_session, po, project.id) == "GP VENDOR LTD"
