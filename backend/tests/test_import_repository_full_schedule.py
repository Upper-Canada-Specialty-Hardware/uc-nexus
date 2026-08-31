"""Tests for full-schedule persistence and replace-schedule override semantics."""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.enums import (
    HardwareItemState,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shop_assembly import ShopAssemblyRequestItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, warehouse_admin_repository


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
    db_session.commit()

    base_input = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [_hardware_item_input("A01", "HG-100")],
        "po_drafts": [
            {
                "po_number": "PO-1",
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


def test_shop_assembly_request_created_pending(db_session):
    """finalize raises a PENDING ShopAssemblyRequest (#646): NO PullRequest, NO reservation and NO
    availability gate - flat lines hanging off the request with their opening tag captured, plus one
    opening row per opening for the manager to work."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    db_session.commit()

    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01", building="B1", floor="F2", location="Lobby")],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {
                    "opening_number": "A01",
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "quantity": 2,
                },
            ],
        },
    )
    db_session.flush()

    # A PENDING shop-assembly request is created, no approval, no PullRequest.
    # #493: the number is minted server-side, so the request is read off the result rather than
    # looked up by the number the caller asked for - which is now ignored.
    sar = result["shop_assembly_request"]
    assert sar is not None
    assert sar.request_number.endswith("-001")
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sar.created_by == "Hardware Schedule Import"
    assert sar.project_id == project.id
    assert result["shop_assembly_request"].id == sar.id

    # No PullRequest exists yet - one is minted per batch, and no batch has been dispatched.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None
    assert sar.batches == []

    # The request holds flat lines, each tagged with its opening, and an opening row per opening.
    lines = db_session.scalars(
        select(ShopAssemblyRequestItem).where(ShopAssemblyRequestItem.shop_assembly_request_id == sar.id)
    ).all()
    assert len(lines) == 1
    assert lines[0].opening_number == "A01"
    assert lines[0].product_code == "HG-100"
    assert lines[0].requested_quantity == 2
    assert [(o.opening_number, o.status) for o in sar.openings] == [("A01", ShopAssemblyOpeningStatus.PENDING)]


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


def test_get_project_openings_returns_trimmed_rows_and_counts(db_session):
    """get_project_openings returns just the picker's opening fields plus the opening and hardware-item
    counts (#608 review) - a grouped COUNT for the items, never the materialized rows the full schedule
    read builds."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [
                _opening_input("A01", building="B1", floor="F1", door_type="HM", frame_type="HM", keying="K1"),
                _opening_input("A02", building="B2", floor="F2"),
            ],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A01", "HG-200"),
                _hardware_item_input("A02", "HG-100"),
            ],
        },
    )
    db_session.flush()

    data = import_repository.get_project_openings(db_session, project.id)
    assert data["opening_count"] == 2
    assert data["hardware_item_count"] == 3

    rows = {r["opening_number"]: r for r in data["openings"]}
    assert set(rows) == {"A01", "A02"}
    a01 = rows["A01"]
    assert a01["building"] == "B1"
    assert a01["floor"] == "F1"
    assert a01["door_type"] == "HM"
    assert a01["frame_type"] == "HM"
    assert a01["keying"] == "K1"
    # Only the picker's fields - none of the dimensional/heading detail the full Opening carries.
    assert set(a01) == {
        "opening_number",
        "building",
        "floor",
        "location",
        "hand",
        "door_type",
        "frame_type",
        "interior_exterior",
        "keying",
        "leaf_count",
    }


def test_get_project_openings_empty_for_project_without_schedule(db_session):
    project = _make_project(db_session)
    db_session.commit()
    data = import_repository.get_project_openings(db_session, project.id)
    assert data == {"openings": [], "opening_count": 0, "hardware_item_count": 0}


# ---------------------------------------------------------------------------
# Schedule source filename (#627)
# ---------------------------------------------------------------------------


def test_schedule_filename_written_on_fresh_parse(db_session):
    """A finalize carrying a source file name stamps it on the project."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100")],
            "schedule_filename": "contracterp-74.xml",
        },
    )
    db_session.flush()

    refreshed = db_session.get(Project, project.id)
    assert refreshed.schedule_filename == "contracterp-74.xml"


def test_schedule_filename_preserved_when_finalize_sends_none(db_session):
    """A hydrate-from-persisted finalize sends no file name; the stored one survives untouched."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100")],
            "schedule_filename": "first.xml",
        },
    )
    db_session.flush()

    # No schedule_filename key at all: same as a hydrate run, which passes None.
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100")],
            "schedule_filename": None,
        },
    )
    db_session.flush()

    refreshed = db_session.get(Project, project.id)
    assert refreshed.schedule_filename == "first.xml"


def test_schedule_filename_exposed_on_schedule_query(db_session):
    """The persisted file name is carried on the project the schedule query returns."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100")],
            "schedule_filename": "sched.xml",
        },
    )
    db_session.flush()

    schedule = import_repository.get_project_hardware_schedule(db_session, project.id)
    assert schedule is not None
    assert schedule["project"].schedule_filename == "sched.xml"


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
