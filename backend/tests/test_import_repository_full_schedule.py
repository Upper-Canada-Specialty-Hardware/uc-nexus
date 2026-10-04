"""Tests for full-schedule persistence and replace-schedule override semantics."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import (
    Classification,
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
from app.repositories import warehouse as warehouse_repository
from tests.shop_assembly_helpers import with_schedule


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
        company="TUBC",
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


def _po_draft(*refs: dict) -> dict:
    return {"po_number": None, "notes": None, "hardware_item_refs": list(refs), "line_item_aliases": []}


def _ref(opening_number: str, product_code: str, quantity: int | None = None) -> dict:
    ref = {"opening_number": opening_number, "product_code": product_code, "hardware_category": "HINGE"}
    if quantity is not None:
        ref["quantity"] = quantity
    return ref


def _rows(session, project_id) -> dict[tuple[str, str, HardwareItemState], int]:
    """(opening, product, state) -> summed item_quantity for the project's hardware rows."""
    out: dict[tuple[str, str, HardwareItemState], int] = {}
    stmt = (
        select(Opening.opening_number, HardwareItem.product_code, HardwareItem.state, HardwareItem.item_quantity)
        .join(Opening, HardwareItem.opening_id == Opening.id)
        .where(HardwareItem.project_id == project_id)
    )
    for number, code, state, qty in session.execute(stmt).all():
        out[(number, code, state)] = out.get((number, code, state), 0) + qty
    return out


def _status(session, project_id, product_code: str) -> dict:
    rows = warehouse_repository.get_hardware_status_by_product(session, [project_id])
    return next(r for r in rows if r["product_code"] == product_code)


def test_refinalize_keeps_unordered_remainder_of_partly_ordered_product(db_session):
    """#1122: a PO that took 2 of 4 units leaves an IN_PO row of 2 and an AVAILABLE row of 2. A later
    finalize from the saved schedule sends one merged row of 4 for that key; the unordered 2 must be
    persisted again, not dropped because the key already has an IN_PO row."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
            "po_drafts": [_po_draft(_ref("A01", "HG-100", quantity=2))],
        },
    )
    db_session.flush()
    assert _rows(db_session, project.id) == {
        ("A01", "HG-100", HardwareItemState.IN_PO): 2,
        ("A01", "HG-100", HardwareItemState.AVAILABLE): 2,
    }

    # Hydrate-from-persisted: the wizard sums the persisted IN_PO and AVAILABLE rows into one row of 4.
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
        },
    )
    db_session.flush()
    assert _rows(db_session, project.id) == {
        ("A01", "HG-100", HardwareItemState.IN_PO): 2,
        ("A01", "HG-100", HardwareItemState.AVAILABLE): 2,
    }
    status = _status(db_session, project.id, "HG-100")
    assert status["required_quantity"] == 4
    assert status["not_purchased"] == 2


def test_refinalize_ordering_the_remainder_leaves_nothing_available(db_session):
    """#1122: the remainder ordered on the second pass becomes IN_PO, and nothing is left AVAILABLE."""
    project = _make_project(db_session)
    db_session.commit()
    base = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
    }
    import_repository.finalize_import_session(db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100", 2))]})
    db_session.flush()
    import_repository.finalize_import_session(db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100", 2))]})
    db_session.flush()

    assert _rows(db_session, project.id) == {("A01", "HG-100", HardwareItemState.IN_PO): 4}
    assert _status(db_session, project.id, "HG-100")["not_purchased"] == 0


def test_refinalize_refuses_a_draft_claiming_units_already_ordered(db_session):
    """#1156: a stale tab offering the whole combo again cannot order units a PO already holds. 2 of
    4 are ordered, so a second draft for 3 is refused and nothing changes."""
    project = _make_project(db_session)
    db_session.commit()
    base = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
    }
    import_repository.finalize_import_session(db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100", 2))]})
    db_session.commit()

    # A savepoint, not db_session.rollback(): the fixture's session joins an outer transaction, and a
    # full rollback would take the project and the first order with it.
    project_id = project.id
    savepoint = db_session.begin_nested()
    with pytest.raises(ValidationError, match="only 2 not yet on a purchase order"):
        import_repository.finalize_import_session(
            db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100", 3))]}
        )
    savepoint.rollback()

    assert _rows(db_session, project_id) == {
        ("A01", "HG-100", HardwareItemState.IN_PO): 2,
        ("A01", "HG-100", HardwareItemState.AVAILABLE): 2,
    }


def test_refinalize_whole_combo_ref_orders_only_the_unordered_remainder(db_session):
    """#1156: a whole-combo ref (no quantity, what the wizard sends when a draft takes everything) on a
    partly-ordered product claims what is not yet ordered, not the schedule's whole requirement again."""
    project = _make_project(db_session)
    db_session.commit()
    base = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
    }
    import_repository.finalize_import_session(db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100", 1))]})
    db_session.flush()
    import_repository.finalize_import_session(db_session, {**base, "po_drafts": [_po_draft(_ref("A01", "HG-100"))]})
    db_session.flush()

    assert _rows(db_session, project.id) == {("A01", "HG-100", HardwareItemState.IN_PO): 4}
    ordered = sorted(
        db_session.scalars(
            select(POLineItem.ordered_quantity)
            .join(PurchaseOrder, POLineItem.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.project_id == project.id)
        ).all()
    )
    assert ordered == [1, 3]


def _classes(session, project_id) -> dict[tuple[str, HardwareItemState], set]:
    rows = session.scalars(select(HardwareItem).where(HardwareItem.project_id == project_id)).all()
    out: dict[tuple[str, HardwareItemState], set] = {}
    for hi in rows:
        out.setdefault((hi.product_code, hi.state), set()).add(hi.classification)
    return out


def test_classification_survives_a_po_step_cost_correction(db_session):
    """#1263: the wizard keys classifications by the parsed cost but sends rows at the corrected cost.
    The product still gets its classification, on the PO rows and the unordered remainder."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=3, unit_cost=12.5)],
            "po_drafts": [_po_draft(_ref("A01", "HG-100", 2))],
            "classifications": [
                {
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "unit_cost": 10.0,
                    "classification": "SHOP_HARDWARE",
                }
            ],
        },
    )
    db_session.flush()

    assert _classes(db_session, project.id) == {
        ("HG-100", HardwareItemState.IN_PO): {Classification.SHOP_HARDWARE},
        ("HG-100", HardwareItemState.AVAILABLE): {Classification.SHOP_HARDWARE},
    }
    assert db_session.scalar(select(POLineItem.classification)) == Classification.SHOP_HARDWARE


def test_reclassifying_a_product_updates_its_rows_already_on_a_po(db_session):
    """#1264: a later non-replace finalize that reclassifies a product applies it to the IN_PO rows an
    earlier session left, not only to the rows it writes, so the product never reads mixed."""
    project = _make_project(db_session)
    db_session.commit()
    base = {
        "project_id": str(project.id),
        "openings": [_opening_input("A01")],
        "hardware_items": [
            _hardware_item_input("A01", "HG-100", item_quantity=4),
            _hardware_item_input("A01", "HG-200", item_quantity=1),
        ],
    }

    def cls(code, value):
        return {"hardware_category": "HINGE", "product_code": code, "unit_cost": 10.0, "classification": value}

    import_repository.finalize_import_session(
        db_session,
        {
            **base,
            "po_drafts": [_po_draft(_ref("A01", "HG-100", 2))],
            "classifications": [cls("HG-100", "SITE_HARDWARE"), cls("HG-200", "SITE_HARDWARE")],
        },
    )
    db_session.flush()
    import_repository.finalize_import_session(db_session, {**base, "classifications": [cls("HG-100", "SHOP_HARDWARE")]})
    db_session.flush()

    classes = _classes(db_session, project.id)
    assert classes[("HG-100", HardwareItemState.IN_PO)] == {Classification.SHOP_HARDWARE}
    assert classes[("HG-100", HardwareItemState.AVAILABLE)] == {Classification.SHOP_HARDWARE}


def test_finalize_refuses_a_category_that_is_a_company_type_code(db_session):
    """#1343: a schedule category equal (case-insensitively) to one of the company's inventory item type
    codes is refused, naming it; nothing is written. Another company's type code does not count."""
    from app.models.inventory_item_type import InventoryItemType

    project = _make_project(db_session)
    code = f"FRAME{uuid.uuid4().hex[:4].upper()}"
    other = f"SPEC{uuid.uuid4().hex[:4].upper()}"
    db_session.add(InventoryItemType(id=uuid.uuid4(), company=project.company, code=code, name=f"Frames {code}"))
    db_session.add(InventoryItemType(id=uuid.uuid4(), company="UCSH", code=other, name=f"Specs {other}"))
    db_session.commit()

    def finalize(category):
        return import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [_opening_input("A01")],
                "hardware_items": [_hardware_item_input("A01", "FR-1", hardware_category=category)],
            },
        )

    savepoint = db_session.begin_nested()
    with pytest.raises(ValidationError, match=code) as exc:
        finalize(code.lower())
    assert exc.value.field == "hardware_items"
    savepoint.rollback()
    assert _rows(db_session, project.id) == {}

    finalize(other)
    db_session.flush()
    assert _rows(db_session, project.id) == {("A01", "FR-1", HardwareItemState.AVAILABLE): 1}


def test_replace_schedule_keeps_ordered_hardware(db_session):
    """#1123: replace_schedule rebuilds the unordered rows from the new input, but ordered (IN_PO) rows
    are kept with their PO line. A matching row in the new schedule only adds the unordered remainder,
    and openings the new schedule dropped are deleted unless they still hold ordered hardware."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100", item_quantity=2),
                _hardware_item_input("A02", "HG-200"),
            ],
            "po_drafts": [_po_draft(_ref("A01", "HG-100"))],
        },
    )
    db_session.flush()
    in_po_before = db_session.scalars(
        select(HardwareItem).where(HardwareItem.project_id == project.id, HardwareItem.state == HardwareItemState.IN_PO)
    ).all()
    line_ids_before = {hi.po_line_item_id for hi in in_po_before}

    # The new schedule still has A01/HG-100 (now 5 needed), drops A02, adds A03.
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A03")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100", item_quantity=5),
                _hardware_item_input("A03", "HG-999"),
            ],
            "replace_schedule": True,
        },
    )
    db_session.flush()

    assert _rows(db_session, project.id) == {
        ("A01", "HG-100", HardwareItemState.IN_PO): 2,
        ("A01", "HG-100", HardwareItemState.AVAILABLE): 3,
        ("A03", "HG-999", HardwareItemState.AVAILABLE): 1,
    }
    in_po_after = db_session.scalars(
        select(HardwareItem).where(HardwareItem.project_id == project.id, HardwareItem.state == HardwareItemState.IN_PO)
    ).all()
    assert {hi.po_line_item_id for hi in in_po_after} == line_ids_before

    # PO is preserved (downstream aggregate untouched)
    pos = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).all()
    assert len(pos) == 1

    # A02 held nothing ordered and is gone from the new XML, so it is deleted.
    openings = db_session.scalars(select(Opening).where(Opening.project_id == project.id)).all()
    assert {o.opening_number for o in openings} == {"A01", "A03"}

    status = _status(db_session, project.id, "HG-100")
    assert status["required_quantity"] == 5
    assert status["not_purchased"] == 3


def test_replace_schedule_keeps_ordered_hardware_the_new_schedule_dropped(db_session):
    """#1123 ruling: a new schedule does not undo an order. Ordered hardware with no match in the new
    schedule stays IN_PO on its opening, and the opening stays for it. Hardware Status never counts
    it as not purchased, and the per-opening reconcile still sees it as ordered, not NOT_COVERED."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=3)],
            "po_drafts": [_po_draft(_ref("A01", "HG-100"))],
        },
    )
    db_session.flush()

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

    assert _rows(db_session, project.id) == {
        ("A01", "HG-100", HardwareItemState.IN_PO): 3,
        ("A03", "HG-999", HardwareItemState.AVAILABLE): 1,
    }
    openings = db_session.scalars(select(Opening).where(Opening.project_id == project.id)).all()
    assert {o.opening_number for o in openings} == {"A01", "A03"}

    status = _status(db_session, project.id, "HG-100")
    assert status["not_purchased"] == 0
    assert status["po_drafted"] == 3

    recon = import_repository.reconcile_schedule(
        db_session,
        project.id,
        [{"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity_needed": 3}],
    )
    assert all(r["status"] != "NOT_COVERED" for r in recon)
    assert sum(r["quantity"] for r in recon) == 3


def test_shop_assembly_request_created_pending(db_session):
    """finalize raises a PENDING ShopAssemblyRequest (#646): NO PullRequest, NO reservation and NO
    availability gate - flat lines hanging off the request with their opening tag captured, plus one
    opening row per opening for the manager to work."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    db_session.commit()

    result = import_repository.finalize_import_session(
        db_session,
        with_schedule(
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
            }
        ),
        created_by="Dana Planner",
    )
    db_session.flush()

    # A PENDING shop-assembly request is created, no approval, no PullRequest.
    # #493: the number is minted server-side, so the request is read off the result rather than
    # looked up by the number the caller asked for - which is now ignored.
    sar = result["shop_assembly_request"]
    assert sar is not None
    assert sar.request_number.endswith("-001")
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    # #859: the person who finalized is the requester, not the import.
    assert sar.created_by == "Dana Planner"
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


# ---- #1412: By Others exclusions survive every finalize that does not send them ----


def _exclusions(session, project_id) -> set[tuple[str, str]]:
    from app.models.project_excluded_item import ProjectExcludedItem

    rows = session.scalars(select(ProjectExcludedItem).where(ProjectExcludedItem.project_id == project_id)).all()
    return {(r.hardware_category, r.product_code) for r in rows}


def _project_with_schedule_and_exclusion(session) -> Project:
    from app.models.project_excluded_item import ProjectExcludedItem

    project = _make_project(session)
    session.commit()
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100"), _hardware_item_input("A01", "HG-200")],
        },
    )
    session.add(
        ProjectExcludedItem(id=uuid.uuid4(), project_id=project.id, hardware_category="HINGE", product_code="HG-200")
    )
    session.flush()
    return project


def test_a_schedule_replace_keeps_the_by_others_exclusions(db_session):
    project = _project_with_schedule_and_exclusion(db_session)

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100"), _hardware_item_input("A01", "HG-200")],
            "replace_schedule": True,
            "excluded_items": None,
        },
    )
    db_session.flush()

    assert _exclusions(db_session, project.id) == {("HINGE", "HG-200")}


def test_a_shop_assembly_request_keeps_the_by_others_exclusions(db_session):
    project = _project_with_schedule_and_exclusion(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    db_session.flush()

    import_repository.finalize_import_session(
        db_session,
        with_schedule(
            {
                "project_id": str(project.id),
                "openings": [_opening_input("A01")],
                "hardware_items": [],
                "include_shop_assembly_request": True,
                "shop_assembly_items": [
                    {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1},
                ],
            }
        ),
        created_by="Dana Planner",
    )
    db_session.flush()

    assert _exclusions(db_session, project.id) == {("HINGE", "HG-200")}


def test_a_po_import_with_an_empty_list_clears_the_exclusions(db_session):
    # Every By Others product moved back to UCSH in the wizard: an explicit [] is that answer.
    project = _project_with_schedule_and_exclusion(db_session)

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100"), _hardware_item_input("A01", "HG-200")],
            "excluded_items": [],
        },
    )
    db_session.flush()

    assert _exclusions(db_session, project.id) == set()


def test_a_po_import_with_a_list_replaces_the_exclusions(db_session):
    project = _project_with_schedule_and_exclusion(db_session)

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100"), _hardware_item_input("A01", "HG-200")],
            "excluded_items": [{"hardware_category": "HINGE", "product_code": "HG-100"}],
        },
    )
    db_session.flush()

    assert _exclusions(db_session, project.id) == {("HINGE", "HG-100")}
