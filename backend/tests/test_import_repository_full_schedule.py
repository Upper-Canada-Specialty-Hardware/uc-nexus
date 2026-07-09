"""Tests for full-schedule persistence and replace-schedule override semantics."""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.enums import (
    HardwareItemState,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.hardware import HardwareItem
from app.models.opening_item import OpeningItem
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import PurchaseOrder
from app.models.shop_assembly import (
    ShopAssemblyOpening,
)
from app.models.vendor import Vendor
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository


def _make_project(session, project_id: str = "PROJ-001") -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=f"{project_id}-{uuid.uuid4().hex[:6]}",
        description="Test",
    )
    session.add(p)
    session.flush()
    return p


def _make_vendor(session, name: str = "Acme") -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}")
    session.add(v)
    session.flush()
    return v


def _opening_input(opening_number: str, **overrides) -> dict:
    base = {
        "opening_number": opening_number,
        "building": overrides.get("building", "B1"),
        "floor": overrides.get("floor", "F1"),
        "location": overrides.get("location", "Lobby"),
        "location_to": None,
        "location_from": None,
        "hand": None,
        "width": None,
        "length": None,
        "door_thickness": None,
        "jamb_thickness": None,
        "door_type": None,
        "frame_type": None,
        "interior_exterior": None,
        "keying": None,
        "heading_no": None,
        "single_pair": None,
        "assignment_multiplier": None,
    }
    base.update(overrides)
    return base


def _hardware_item_input(opening_number: str, product_code: str, **overrides) -> dict:
    base = {
        "opening_number": opening_number,
        "product_code": product_code,
        "hardware_category": overrides.get("hardware_category", "HINGE"),
        "item_quantity": overrides.get("item_quantity", 1),
        "unit_cost": overrides.get("unit_cost", 10.0),
        "unit_price": None,
        "list_price": None,
        "vendor_discount": None,
        "markup_pct": None,
        "vendor_no": overrides.get("vendor_no", "V1"),
        "phase_code": None,
        "item_category_code": None,
        "product_group_code": None,
        "submittal_id": None,
    }
    base.update(overrides)
    return base


def test_persists_full_schedule_as_available_when_no_pos(db_session):
    """Items with no PO drafts should all be persisted as AVAILABLE."""
    project = _make_project(db_session)
    db_session.commit()

    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A01", "HG-200"),
                _hardware_item_input("A02", "HG-100"),
            ],
        },
    )
    db_session.flush()
    assert result["project"].id == project.id

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(items) == 3
    assert all(hi.state == HardwareItemState.AVAILABLE for hi in items)
    assert all(hi.po_line_item_id is None for hi in items)


def test_persists_full_schedule_with_mixed_po_and_available(db_session):
    """Items in PO drafts become IN_PO; remaining items become AVAILABLE."""
    project = _make_project(db_session)
    vendor = _make_vendor(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A01", "HG-200"),
                _hardware_item_input("A02", "HG-100"),
            ],
            "po_drafts": [
                {
                    "po_number": "PO-1",
                    "vendor_id": str(vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [],
                },
            ],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    by_key = {(hi.product_code, hi.state): hi for hi in items}
    assert len(items) == 3
    assert ("HG-100", HardwareItemState.IN_PO) in by_key
    assert ("HG-200", HardwareItemState.AVAILABLE) in by_key
    # The second A02/HG-100 entry should be AVAILABLE
    available_hg100 = [hi for hi in items if hi.product_code == "HG-100" and hi.state == HardwareItemState.AVAILABLE]
    assert len(available_hg100) == 1


def test_resume_does_not_duplicate_in_po_items(db_session):
    """Re-running finalize with same input must not create duplicate AVAILABLE rows for items already IN_PO."""
    project = _make_project(db_session)
    vendor = _make_vendor(db_session)
    db_session.commit()

    base_input = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [_hardware_item_input("A01", "HG-100")],
        "po_drafts": [
            {
                "po_number": "PO-1",
                "vendor_id": str(vendor.id),
                "notes": None,
                "hardware_item_refs": [
                    {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                ],
                "line_item_aliases": [],
            },
        ],
    }
    import_repository.finalize_import_session(db_session, base_input)
    db_session.flush()

    # Re-run without po_drafts (simulating "Start from latest" then closing wizard)
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100")],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(items) == 1
    assert items[0].state == HardwareItemState.IN_PO


def test_replace_schedule_wipes_all_hardware_items(db_session):
    """replace_schedule=True wipes all HardwareItems including IN_PO, then recreates from new input."""
    project = _make_project(db_session)
    vendor = _make_vendor(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A02", "HG-200"),
            ],
            "po_drafts": [
                {
                    "po_number": "PO-1",
                    "vendor_id": str(vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [],
                },
            ],
        },
    )
    db_session.flush()

    # PO and its line items should exist
    po_count_before = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).all()
    assert len(po_count_before) == 1

    # Re-upload a different schedule with replace_schedule=True
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A03")],
            "hardware_items": [_hardware_item_input("A03", "HG-999")],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(items) == 1
    assert items[0].product_code == "HG-999"
    assert items[0].state == HardwareItemState.AVAILABLE

    # PO is preserved (downstream aggregate untouched)
    po_count_after = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).all()
    assert len(po_count_after) == 1

    # Openings missing from new XML are deleted
    openings = db_session.scalars(select(Opening).where(Opening.project_id == project.id)).all()
    opening_numbers = {o.opening_number for o in openings}
    assert opening_numbers == {"A03"}


def test_replace_schedule_preserves_inventory(db_session):
    """An OpeningItem in inventory survives a replace_schedule that removes its source opening."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B1", floor="F2", location="Lobby")],
            "hardware_items": [],
        },
    )
    db_session.flush()
    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))

    # Simulate an OpeningItem in inventory for A01
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=a01.id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
        opening_number="A01",
        building="B1",
        floor="F2",
        location="Lobby",
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=OpeningItemState.IN_INVENTORY,
        aisle="A1",
        bay="B1",
        bin="01",
    )
    db_session.add(oi)
    db_session.flush()

    # Re-upload a schedule without A01
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A02")],
            "hardware_items": [],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    # Opening row is gone
    assert db_session.scalar(select(Opening).where(Opening.id == a01.id)) is None

    # OpeningItem still exists, with full snapshot
    refreshed_oi = db_session.scalar(select(OpeningItem).where(OpeningItem.id == oi.id))
    assert refreshed_oi is not None
    assert refreshed_oi.opening_number == "A01"
    assert refreshed_oi.building == "B1"
    assert refreshed_oi.floor == "F2"
    assert refreshed_oi.location == "Lobby"
    assert refreshed_oi.aisle == "A1"
    assert refreshed_oi.quantity == 1


def test_shop_assembly_pr_created_directly(db_session):
    """finalize mints the shop-assembly PR directly (#222): no SAR row, a PENDING SHOP_ASSEMBLY PR,
    LOOSE PR items per opening item, and openings that hang off the PR with snapshot identity."""
    project = _make_project(db_session)
    db_session.commit()

    pr_number = f"SA-{uuid.uuid4().hex[:6]}"
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B1", floor="F2", location="Lobby")],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": pr_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "items": [
                        {"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2},
                    ],
                },
            ],
        },
    )
    db_session.flush()

    # A shop-assembly PR is created directly, no approval gate.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == pr_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHOP_ASSEMBLY
    assert pr.status == PullRequestStatus.PENDING
    assert pr.project_id == project.id

    # Each opening item is mirrored as a LOOSE PR item.
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].item_type == PullRequestItemType.LOOSE
    assert pr_items[0].opening_number == "A01"
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2

    # The opening hangs off the PR (not a SAR) and carries snapshot identity.
    sao = db_session.scalar(
        select(ShopAssemblyOpening)
        .join(PullRequest, ShopAssemblyOpening.pull_request_id == PullRequest.id)
        .where(PullRequest.request_number == pr_number)
    )
    assert sao is not None
    assert sao.shop_assembly_request_id is None
    assert sao.opening_number == "A01"
    assert sao.building == "B1"
    assert sao.floor == "F2"
    assert sao.location == "Lobby"


def test_sar_queries_work_after_opening_deleted(db_session):
    """get_assemble_list / get_my_work must work even when the source Opening row was deleted."""
    project = _make_project(db_session)
    db_session.commit()

    pr_number = f"SA-{uuid.uuid4().hex[:6]}"
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": pr_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()

    # Complete the pull so the opening shows up in assemble_list (assigned_to needs setting for my_work)
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == pr_number))
    pr.status = PullRequestStatus.COMPLETED
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id))
    sao.pull_status = PullStatus.PULLED
    sao.assigned_to = "tester"
    db_session.flush()

    # Re-upload removing A01
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A02")],
            "hardware_items": [],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    # Opening A01 is deleted
    assert (
        db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))
        is None
    )

    # Both repository functions should still return the SAR opening with snapshot data
    assemble_rows = shop_assembly_repository.get_assemble_list(db_session, project.id)
    assert len(assemble_rows) == 1
    assert assemble_rows[0].opening_number == "A01"

    my_work_rows = shop_assembly_repository.get_my_work(db_session, "tester")
    assert len(my_work_rows) == 1
    assert my_work_rows[0].opening_number == "A01"


def test_existing_openings_updated_on_replace(db_session):
    """replace_schedule refreshes existing opening field values from the new XML."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B1", floor="F1", door_type="HM")],
            "hardware_items": [],
        },
    )
    db_session.flush()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B2", floor="F3", door_type="WD")],
            "hardware_items": [],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))
    assert a01.building == "B2"
    assert a01.floor == "F3"
    assert a01.door_type == "WD"


def test_get_project_hardware_schedule_returns_all_items(db_session):
    """get_project_hardware_schedule must return the full persisted set (including AVAILABLE)."""
    project = _make_project(db_session)
    vendor = _make_vendor(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A02", "HG-200"),
                _hardware_item_input("A02", "HG-300"),
            ],
            "po_drafts": [
                {
                    "po_number": "PO-1",
                    "vendor_id": str(vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [],
                },
            ],
        },
    )
    db_session.flush()

    schedule = import_repository.get_project_hardware_schedule(db_session, project.id)
    assert schedule is not None
    opening_numbers = {o.opening_number for o in schedule["openings"]}
    assert opening_numbers == {"A01", "A02"}

    hw_items = schedule["hardware_items"]
    assert len(hw_items) == 3
    product_codes = {hi["product_code"] for hi in hw_items}
    assert product_codes == {"HG-100", "HG-200", "HG-300"}
