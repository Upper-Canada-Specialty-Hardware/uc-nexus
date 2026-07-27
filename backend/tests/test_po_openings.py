"""Which openings a PO's hardware was bought for (#302): po_repository.get_po_openings.

The PO carries only fungible (category, product) lines; the link back to a door survives on
HardwareItem.po_line_item_id, which the import stamps. These pin the grouping and the ordering,
because the UI renders consecutive rows without a second pass.
"""

import uuid

from sqlalchemy import select

from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import PurchaseOrder
from app.models.vendor import Vendor
from app.repositories import import_repository, po_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _opening_input(opening_number: str) -> dict:
    return {
        "opening_number": opening_number,
        "building": "B1",
        "floor": "F1",
        "location": "Lobby",
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


def _hw(opening_number: str, product_code: str, qty: int = 1) -> dict:
    return {
        "opening_number": opening_number,
        "product_code": product_code,
        "hardware_category": "HINGE",
        "item_quantity": qty,
        "unit_cost": 10.0,
        "unit_price": None,
        "list_price": None,
        "vendor_discount": None,
        "markup_pct": None,
        "vendor_no": "V1",
        "phase_code": None,
        "item_category_code": None,
        "product_group_code": None,
        "submittal_id": None,
    }


def _import_po(session, project: Project) -> PurchaseOrder:
    vendor = Vendor(id=uuid.uuid4(), name=f"V-{uuid.uuid4().hex[:6]}")
    session.add(vendor)
    session.flush()
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hw("A01", "HG-100", 3),
                _hw("A02", "HG-200", 6),
            ],
            "po_drafts": [
                {
                    "po_number": None,
                    "vendor_id": str(vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                        {"opening_number": "A02", "product_code": "HG-200", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [],
                }
            ],
        },
    )
    session.flush()
    po = session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).first()
    assert po is not None
    return po


def test_groups_the_pos_hardware_by_opening(db_session):
    project = _make_project(db_session)
    po = _import_po(db_session, project)

    rows = po_repository.get_po_openings(db_session, po.id)

    assert [r["opening_number"] for r in rows] == ["A01", "A02"]
    assert rows[0]["items"] == [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3}]
    assert rows[1]["items"] == [{"hardware_category": "HINGE", "product_code": "HG-200", "quantity": 6}]
    assert rows[0]["building"] == "B1"
    assert rows[0]["floor"] == "F1"
    assert rows[0]["location"] == "Lobby"


def test_splits_an_opening_by_leaf_and_sorts_the_frame_first(db_session):
    # An opening's two leaves are separate rows (#311), and a frame - leaf null - sorts ahead of them
    # rather than wherever the database happens to put nulls.
    project = _make_project(db_session)
    po = _import_po(db_session, project)
    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    a01 = next(i for i in items if i.product_code == "HG-100")
    a01.leaf = 2

    frame = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=a01.opening_id,
        hardware_category="FRAME",
        product_code="FR-001",
        leaf=None,
        item_quantity=1,
        state=a01.state,
        po_line_item_id=a01.po_line_item_id,
    )
    db_session.add(frame)
    db_session.flush()

    rows = po_repository.get_po_openings(db_session, po.id)
    a01_rows = [r for r in rows if r["opening_number"] == "A01"]

    assert [r["leaf"] for r in a01_rows] == [None, 2]
    assert a01_rows[0]["items"][0]["product_code"] == "FR-001"


def test_sums_repeated_hardware_within_one_opening_and_leaf(db_session):
    project = _make_project(db_session)
    po = _import_po(db_session, project)
    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    a01 = next(i for i in items if i.product_code == "HG-100")

    db_session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=a01.opening_id,
            hardware_category="HINGE",
            product_code="HG-100",
            leaf=a01.leaf,
            item_quantity=4,
            state=a01.state,
            po_line_item_id=a01.po_line_item_id,
        )
    )
    db_session.flush()

    rows = po_repository.get_po_openings(db_session, po.id)
    a01_row = next(r for r in rows if r["opening_number"] == "A01")

    # One line, 3 + 4 - not two rows the UI would have to add up itself.
    assert a01_row["items"] == [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 7}]


def test_a_po_with_no_hardware_behind_it_returns_nothing(db_session):
    # A manually created stock PO has no hardware schedule, so the section renders nothing at all.
    po = po_repository.create_po(
        db_session,
        line_items=[
            {
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": None,
            }
        ],
        project_id=None,
    )
    assert po_repository.get_po_openings(db_session, po.id) == []


def test_ignores_openings_belonging_to_a_different_po(db_session):
    project_a = _make_project(db_session)
    project_b = _make_project(db_session)
    po_a = _import_po(db_session, project_a)
    _import_po(db_session, project_b)

    rows = po_repository.get_po_openings(db_session, po_a.id)

    assert {r["opening_number"] for r in rows} == {"A01", "A02"}
    assert all(
        db_session.get(Opening, uuid.UUID(str(o.id))) is not None
        for o in db_session.scalars(select(Opening).where(Opening.project_id == project_a.id))
    )
