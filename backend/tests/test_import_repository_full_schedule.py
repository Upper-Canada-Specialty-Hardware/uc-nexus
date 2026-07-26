"""Tests for full-schedule persistence and replace-schedule override semantics."""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.enums import (
    HardwareItemState,
    OpeningItemState,
    PullRequestStatus,
    PullStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItem
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shop_assembly import (
    ShopAssemblyOpening,
    ShopAssemblyRequest,
)
from app.models.stock_item import StockItem
from app.models.vendor import Vendor
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository


def _seed_inventory(session, project_id, *, hardware_category="HINGE", product_code="HG-100", quantity=10):
    """Put available inventory in the project so the #224 gate-1 sufficiency check passes."""
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=si.id,
        warehouse_id=warehouse_id,
        hardware_category=hardware_category,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


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
        "manufacturer": overrides.get("manufacturer", "TITAN"),
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
        row="01",
        bay="B1",
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


def test_shop_assembly_request_created_pending(db_session):
    """finalize mints a PENDING ShopAssemblyRequest (#293): NO PullRequest yet, openings hang off the
    SAR via shop_assembly_request_id with pull_request_id NULL, items + snapshot identity captured.
    Creation gates on available inventory and reserves it (#342), so the stock has to be there."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    db_session.commit()

    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B1", floor="F2", location="Lobby")],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
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

    # A PENDING shop-assembly request is created, no approval, no PullRequest.
    sar = db_session.scalar(select(ShopAssemblyRequest).where(ShopAssemblyRequest.request_number == req_number))
    assert sar is not None
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sar.created_by == "Hardware Schedule Import"
    assert sar.project_id == project.id
    assert result["shop_assembly_request"].id == sar.id

    # No PullRequest exists yet - it is minted only at accept.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number)) is None

    # The opening hangs off the SAR (not a PR) with pull_request_id NULL and snapshot identity.
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id))
    assert sao is not None
    assert sao.pull_request_id is None
    assert sao.opening_number == "A01"
    assert sao.building == "B1"
    assert sao.floor == "F2"
    assert sao.location == "Lobby"
    assert len(sao.items) == 1
    assert sao.items[0].product_code == "HG-100"
    assert sao.items[0].quantity == 2


def test_sar_queries_work_after_opening_deleted(db_session):
    """get_assemble_list / get_my_work must work even when the source Opening row was deleted."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, product_code="HG-100", quantity=1)  # #224 gate 1
    db_session.commit()

    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()

    # Accept the request (#293) so it mints the shop-assembly PR and repoints the opening at it.
    shop_assembly_repository.accept_shop_assembly_request(db_session, result["shop_assembly_request"].id, "acceptor")
    db_session.flush()

    # Complete the pull so the opening shows up in assemble_list (assigned_to needs setting for my_work)
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    pr.status = PullRequestStatus.COMPLETED
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id))
    sao.pull_status = PullStatus.PULLED
    # my_work keys on the stable user id (#324); assigned_to is the display name.
    sao.assigned_to_user_id = "tester"
    sao.assigned_to = "Tester Name"
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


def _pulled_opening(db_session, project, opening_number="A01"):
    """Drive one shop-assembly opening to a PULLED, unassigned, PENDING state and return its row."""
    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input(opening_number)],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
            "shop_assembly_openings": [
                {
                    "opening_number": opening_number,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, result["shop_assembly_request"].id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    pr.status = PullRequestStatus.COMPLETED
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id))
    sao.pull_status = PullStatus.PULLED
    db_session.flush()
    return sao


def test_assign_and_my_work_key_on_stable_user_id(db_session):
    """#324: assignment stores the stable user id + display name; my_work filters on the user id,
    NOT the display name - the exact mismatch that broke the e2e when assigning by raw id."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, product_code="HG-100", quantity=1)
    db_session.commit()

    sao = _pulled_opening(db_session, project)

    shop_assembly_repository.assign_openings(
        db_session, [sao.id], assigned_to_user_id="user_clerk_123", assigned_to_name="Jane Doe"
    )
    db_session.flush()
    db_session.refresh(sao)
    assert sao.assigned_to_user_id == "user_clerk_123"
    assert sao.assigned_to == "Jane Doe"

    # my_work resolves by the stable id...
    assert len(shop_assembly_repository.get_my_work(db_session, "user_clerk_123")) == 1
    # ...and NOT by the display name (the pre-#324 key).
    assert shop_assembly_repository.get_my_work(db_session, "Jane Doe") == []

    # Returning it to the pool clears both fields, so it drops off my_work.
    shop_assembly_repository.remove_opening_from_user(db_session, sao.id)
    db_session.flush()
    db_session.refresh(sao)
    assert sao.assigned_to_user_id is None
    assert sao.assigned_to is None
    assert shop_assembly_repository.get_my_work(db_session, "user_clerk_123") == []


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


def test_manufacturer_persists_and_round_trips(db_session):
    """Manufacturer flows finalize input -> HardwareItem row -> schedule query, and a null
    manufacturer round-trips as None (blank) rather than erroring."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100", manufacturer="TITAN"),
                _hardware_item_input("A02", "HG-200", manufacturer=None),
            ],
        },
    )
    db_session.flush()

    # Persisted onto the HardwareItem rows
    rows = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    by_product = {hi.product_code: hi for hi in rows}
    assert by_product["HG-100"].manufacturer == "TITAN"
    assert by_product["HG-200"].manufacturer is None

    # Round-trips through the schedule hydration path
    schedule = import_repository.get_project_hardware_schedule(db_session, project.id)
    mfr_by_product = {hi["product_code"]: hi["manufacturer"] for hi in schedule["hardware_items"]}
    assert mfr_by_product["HG-100"] == "TITAN"
    assert mfr_by_product["HG-200"] is None


# ---------------------------------------------------------------------------
# Door-leaf awareness (#311)
# ---------------------------------------------------------------------------


def test_leaf_persisted_per_leaf_for_pair(db_session):
    """A pair's leaf-1 and leaf-2 rows for the same product persist as two HardwareItems, not one;
    opening.leaf_count is stamped and the leaf round-trips through the schedule query."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [
                _hardware_item_input("PR1", "HG-100", leaf=1, item_quantity=1),
                _hardware_item_input("PR1", "HG-100", leaf=2, item_quantity=1),
            ],
        },
    )
    db_session.flush()

    rows = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(rows) == 2
    assert {hi.leaf for hi in rows} == {1, 2}

    opening = db_session.scalar(
        select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "PR1")
    )
    assert opening.leaf_count == 2

    schedule = import_repository.get_project_hardware_schedule(db_session, project.id)
    assert {hi["leaf"] for hi in schedule["hardware_items"]} == {1, 2}


def test_leaf_po_ref_attaches_both_leaf_rows_to_one_line(db_session):
    """A leaf-agnostic PO ref claims every leaf row for the combo: both leaf HardwareItems land
    IN_PO on one PO line, whose ordered_quantity sums across the leaves."""
    project = _make_project(db_session)
    vendor = _make_vendor(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [
                _hardware_item_input("PR1", "HG-100", leaf=1, item_quantity=2),
                _hardware_item_input("PR1", "HG-100", leaf=2, item_quantity=3),
            ],
            "po_drafts": [
                {
                    "po_number": "PO-1",
                    "vendor_id": str(vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "PR1", "product_code": "HG-100", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [],
                },
            ],
        },
    )
    db_session.flush()

    rows = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(rows) == 2
    assert all(hi.state == HardwareItemState.IN_PO for hi in rows)
    assert {hi.leaf for hi in rows} == {1, 2}

    line_item_ids = {hi.po_line_item_id for hi in rows}
    assert len(line_item_ids) == 1  # both leaves roll into one PO line
    poli = db_session.scalar(select(POLineItem).where(POLineItem.id == next(iter(line_item_ids))))
    assert poli.ordered_quantity == 5  # 2 (leaf 1) + 3 (leaf 2)


def test_sar_created_per_leaf(db_session):
    """A pair produces one ShopAssemblyOpening per door leaf, each stamped with its leaf."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    db_session.commit()

    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "PR1",
                    "leaf": 1,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
                {
                    "opening_number": "PR1",
                    "leaf": 2,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()

    saos = db_session.scalars(select(ShopAssemblyOpening).where(ShopAssemblyOpening.opening_number == "PR1")).all()
    assert len(saos) == 2
    assert {sao.leaf for sao in saos} == {1, 2}


def test_find_already_assembled_openings_is_per_leaf(db_session):
    """Assembling Leaf 1 must not block sending Leaf 2: the guard keys on (opening_id, leaf)."""
    project = _make_project(db_session)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="PR1")
    db_session.add(opening)
    db_session.flush()

    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    db_session.add(
        OpeningItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            warehouse_id=warehouse_id,
            opening_number="PR1",
            leaf=1,
            quantity=1,
            assembly_completed_at=datetime.utcnow(),
            state=OpeningItemState.IN_INVENTORY,
        )
    )
    db_session.flush()

    specs = [("PR1", opening.id, 1), ("PR1", opening.id, 2)]
    result = shop_assembly_repository.find_already_assembled_openings(db_session, project.id, specs)
    assert result == [("PR1", 1)]  # leaf 1 blocked, leaf 2 free


def test_accept_stamps_leaf_on_pull_items(db_session):
    """accept mints one LOOSE PullRequestItem per leaf, each stamped from ShopAssemblyOpening.leaf."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, product_code="HG-100", quantity=2)
    db_session.commit()

    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "PR1",
                    "leaf": 1,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
                {
                    "opening_number": "PR1",
                    "leaf": 2,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, result["shop_assembly_request"].id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(items) == 2
    assert {i.leaf for i in items} == {1, 2}


def test_complete_opening_stamps_leaf(db_session):
    """complete_opening stamps the assembled OpeningItem's leaf from the ShopAssemblyOpening (#311)."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, product_code="HG-100", quantity=1)
    db_session.commit()

    req_number = f"SA-{uuid.uuid4().hex[:6]}"
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": req_number,
            "shop_assembly_openings": [
                {
                    "opening_number": "PR1",
                    "leaf": 2,
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
                },
            ],
        },
    )
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, result["shop_assembly_request"].id, "acceptor")
    db_session.flush()

    # Drive the opening to a completable state: PR pulled+completed, opening assigned.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    pr.status = PullRequestStatus.COMPLETED
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id))
    sao.pull_status = PullStatus.PULLED
    sao.assigned_to = "tester"
    # Every unit has to be dispositioned before completion is allowed (#340).
    for item in sao.items:
        item.installed_quantity = item.quantity
    db_session.flush()

    opening_item = shop_assembly_repository.complete_opening(db_session, sao.id, "A", "1", "1", completed_by="tester")
    db_session.flush()
    assert opening_item.leaf == 2
