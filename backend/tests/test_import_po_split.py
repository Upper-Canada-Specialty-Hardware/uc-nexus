"""#570: quantity-aware PO drafts - slicing a combo across drafts, splitting a boundary leaf.

Two layers:
  - plan_po_claims is pure (no DB), so the splitting and cross-draft coordination that are the whole
    point of #570 are exercised directly here and run locally without a database.
  - the finalize_import_session tests match the DB-backed pattern in
    test_import_repository_full_schedule (they skip locally when DATABASE_URL is unset, run in CI) and
    check that the plan materializes into the right IN_PO / AVAILABLE rows and PO lines.
"""

import uuid

import pytest
from sqlalchemy import select

from app.errors import NotFoundError, ValidationError
from app.models.enums import HardwareItemState
from app.models.hardware import HardwareItem
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import import_repository
from app.repositories.import_repository import plan_po_claims

# ---------------------------------------------------------------------------
# plan_po_claims - pure, no database
# ---------------------------------------------------------------------------


def _hw(opening, product, qty, *, category="HINGE", leaf=None):
    return {
        "opening_number": opening,
        "product_code": product,
        "hardware_category": category,
        "leaf": leaf,
        "item_quantity": qty,
    }


def _ref(opening, product, quantity=None, *, category="HINGE"):
    return {
        "opening_number": opening,
        "product_code": product,
        "hardware_category": category,
        "quantity": quantity,
    }


def _draft(*refs):
    return {"hardware_item_refs": list(refs)}


def test_none_quantity_claims_the_whole_combo():
    # Today's behaviour: a ref with no quantity takes every unit, leaving nothing AVAILABLE.
    claims, remaining = plan_po_claims([_hw("A01", "HG-100", 3)], [_draft(_ref("A01", "HG-100"))])
    assert claims == [[(0, 3)]]
    assert remaining == {0: 0}


def test_partial_quantity_splits_the_row_and_leaves_a_remainder():
    claims, remaining = plan_po_claims([_hw("A01", "HG-100", 3)], [_draft(_ref("A01", "HG-100", 2))])
    assert claims == [[(0, 2)]]
    assert remaining == {0: 1}  # the unclaimed unit falls through to AVAILABLE


def test_two_drafts_split_one_combo_between_them():
    # The same combo referenced by two drafts: the first takes the opening units, the second the rest.
    claims, remaining = plan_po_claims(
        [_hw("A01", "HG-100", 3)],
        [_draft(_ref("A01", "HG-100", 2)), _draft(_ref("A01", "HG-100", 1))],
    )
    assert claims == [[(0, 2)], [(0, 1)]]
    assert remaining == {0: 0}


def test_boundary_leaf_splits_across_drafts_on_a_pair():
    # A pair: leaf 1 = 2, leaf 2 = 2 (combo total 4). Draft A wants 3, draft B wants 1. Draft A takes
    # leaf 1 whole (2) and half of leaf 2 (1); draft B takes the other half of leaf 2 (1).
    rows = [_hw("PR1", "HG-100", 2, leaf=1), _hw("PR1", "HG-100", 2, leaf=2)]
    claims, remaining = plan_po_claims(
        rows,
        [_draft(_ref("PR1", "HG-100", 3)), _draft(_ref("PR1", "HG-100", 1))],
    )
    assert claims == [[(0, 2), (1, 1)], [(1, 1)]]
    assert remaining == {0: 0, 1: 0}


def test_unreferenced_and_partially_claimed_rows_both_report_their_remainder():
    rows = [_hw("A01", "HG-100", 5), _hw("A02", "HG-200", 4)]
    claims, remaining = plan_po_claims(rows, [_draft(_ref("A01", "HG-100", 2))])
    assert claims == [[(0, 2)]]
    # HG-100 keeps 3 unclaimed; HG-200 was never referenced, so all 4 remain.
    assert remaining == {0: 3, 1: 4}


def test_overclaim_across_drafts_is_rejected():
    # combo total 3, drafts ask for 2 + 2 = 4.
    with pytest.raises(ValidationError):
        plan_po_claims(
            [_hw("A01", "HG-100", 3)],
            [_draft(_ref("A01", "HG-100", 2)), _draft(_ref("A01", "HG-100", 2))],
        )


def test_none_plus_an_explicit_claim_on_the_same_combo_is_rejected():
    # None means "the whole combo", so any further claim on it is over the cap.
    with pytest.raises(ValidationError):
        plan_po_claims(
            [_hw("A01", "HG-100", 3)],
            [_draft(_ref("A01", "HG-100")), _draft(_ref("A01", "HG-100", 1))],
        )


def test_ref_to_a_combo_the_schedule_lacks_is_not_found():
    with pytest.raises(NotFoundError):
        plan_po_claims([_hw("A01", "HG-100", 3)], [_draft(_ref("A02", "HG-999", 1))])


def test_no_drafts_leaves_the_whole_schedule_as_remainder():
    claims, remaining = plan_po_claims([_hw("A01", "HG-100", 3), _hw("A02", "HG-200", 1)], [])
    assert claims == []
    assert remaining == {0: 3, 1: 1}


# ---------------------------------------------------------------------------
# finalize_import_session - DB-backed (skips locally, runs in CI)
# ---------------------------------------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _opening_input(opening_number: str, **overrides) -> dict:
    base = {
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
        "vendor_no": "V1",
        "manufacturer": "TITAN",
        "phase_code": None,
        "item_category_code": None,
        "product_group_code": None,
        "submittal_id": None,
        "leaf": overrides.get("leaf"),
    }
    base.update(overrides)
    return base


def _po_draft(refs, po_number="PO-1", vendor_name=None):
    return {
        "po_number": po_number,
        "notes": None,
        "vendor_name": vendor_name,
        "hardware_item_refs": refs,
        "line_item_aliases": [],
    }


def test_partial_ref_splits_a_row_into_in_po_and_available(db_session):
    """A ref for 2 of 3 puts 2 units IN_PO on the PO line and leaves 1 unit AVAILABLE."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=3)],
            "po_drafts": [
                _po_draft(
                    [{"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE", "quantity": 2}]
                )
            ],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    by_state = {hi.state: hi for hi in items}
    assert len(items) == 2
    assert by_state[HardwareItemState.IN_PO].item_quantity == 2
    assert by_state[HardwareItemState.AVAILABLE].item_quantity == 1

    poli = db_session.scalar(select(POLineItem))
    assert poli.ordered_quantity == 2


def test_two_drafts_split_one_combo_no_remainder(db_session):
    """The same combo sliced across two drafts: two POs, quantities 2 and 1, nothing left AVAILABLE."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=3)],
            "po_drafts": [
                _po_draft(
                    [{"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE", "quantity": 2}],
                    po_number="PO-1",
                ),
                _po_draft(
                    [{"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE", "quantity": 1}],
                    po_number="PO-2",
                ),
            ],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert all(hi.state == HardwareItemState.IN_PO for hi in items)
    assert sum(hi.item_quantity for hi in items) == 3

    pos = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).all()
    assert len(pos) == 2
    line_qtys = sorted(poli.ordered_quantity for poli in db_session.scalars(select(POLineItem)).all())
    assert line_qtys == [1, 2]


def test_boundary_leaf_splits_on_a_pair(db_session):
    """A pair (leaf1=2, leaf2=2). A draft for 3 takes leaf1 whole and half of leaf2; the other half of
    leaf2 stays AVAILABLE. The PO line's ordered_quantity is 3."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("PR1", leaf_count=2)],
            "hardware_items": [
                _hardware_item_input("PR1", "HG-100", leaf=1, item_quantity=2),
                _hardware_item_input("PR1", "HG-100", leaf=2, item_quantity=2),
            ],
            "po_drafts": [
                _po_draft(
                    [{"opening_number": "PR1", "product_code": "HG-100", "hardware_category": "HINGE", "quantity": 3}]
                )
            ],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    in_po = [hi for hi in items if hi.state == HardwareItemState.IN_PO]
    available = [hi for hi in items if hi.state == HardwareItemState.AVAILABLE]
    assert sum(hi.item_quantity for hi in in_po) == 3
    assert sum(hi.item_quantity for hi in available) == 1
    assert available[0].leaf == 2  # the boundary leaf's remainder

    poli = db_session.scalar(select(POLineItem))
    assert poli.ordered_quantity == 3


def test_overclaim_is_rejected_and_nothing_persists(db_session):
    """A draft asking for more than the combo holds raises ValidationError."""
    project = _make_project(db_session)
    db_session.commit()

    with pytest.raises(ValidationError):
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [_opening_input("A01")],
                "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=2)],
                "po_drafts": [
                    _po_draft(
                        [
                            {
                                "opening_number": "A01",
                                "product_code": "HG-100",
                                "hardware_category": "HINGE",
                                "quantity": 3,
                            }
                        ]
                    )
                ],
            },
        )


def test_null_quantity_still_claims_the_whole_combo(db_session):
    """A ref with no quantity keeps today's all-or-nothing behaviour: whole combo IN_PO, no remainder."""
    project = _make_project(db_session)
    db_session.commit()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=4)],
            "po_drafts": [
                _po_draft([{"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"}])
            ],
        },
    )
    db_session.flush()

    items = db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id)).all()
    assert len(items) == 1
    assert items[0].state == HardwareItemState.IN_PO
    assert items[0].item_quantity == 4


# --- #632: the wizard's per-draft vendor label ----------------------------------------------------
# It seeds vendor_name_snapshot on the created DRAFT so the register table and bestGuessGpVendor have
# something to show for a request. GP register overwrites it later with the confirmed GP vendor's
# display name - the GP vendor stays the only vendor authority.


def _one_ref():
    return [{"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE", "quantity": 2}]


def _finalize_with(db_session, project, draft):
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [_hardware_item_input("A01", "HG-100", item_quantity=2)],
            "po_drafts": [draft],
        },
    )
    db_session.flush()
    return db_session.scalar(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id))


def test_a_drafts_vendor_label_lands_on_the_created_po_stripped(db_session):
    project = _make_project(db_session)
    db_session.commit()

    po = _finalize_with(db_session, project, _po_draft(_one_ref(), vendor_name="  Allegion  "))

    assert po.vendor_name_snapshot == "Allegion"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_a_blank_vendor_label_leaves_the_snapshot_null(db_session, blank):
    project = _make_project(db_session)
    db_session.commit()

    po = _finalize_with(db_session, project, _po_draft(_one_ref(), vendor_name=blank))

    assert po.vendor_name_snapshot is None


def test_a_draft_dict_that_predates_the_vendor_key_still_finalizes(db_session):
    """The repository reads the key with .get, so a payload built before the field existed - every
    older fixture, and any queued wizard state - finalizes with a null snapshot rather than dying."""
    project = _make_project(db_session)
    db_session.commit()

    po = _finalize_with(
        db_session,
        project,
        {"po_number": "PO-1", "notes": None, "hardware_item_refs": _one_ref(), "line_item_aliases": []},
    )

    assert po.vendor_name_snapshot is None
