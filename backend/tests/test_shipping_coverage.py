"""What the shipping-out builder is told each selected leaf still owes the site (#451).

The point of the query is that no single table answers it: the schedule knows what a leaf takes,
the assembled leaf knows what was fitted, and the purchase orders know what is still coming. These
tests pin the joins between them, and in particular the two cases the shipper gets wrong without
help - site hardware, which never goes near the bench and so is always still owed, and shop
hardware assembly had to skip.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.enums import Classification, HardwareItemState, OpeningItemState, POStatus
from app.models.hardware import HardwareItem
from app.models.opening_item import OpeningItem, OpeningItemHardware
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import shipping_coverage, warehouse_admin_repository


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _opening(session, project, number="101", leaf_count=2) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=number, leaf_count=leaf_count)
    session.add(o)
    session.flush()
    return o


def _hardware(session, project, opening, *, leaf, code="HG-100", cat="HINGE", qty=3, classification=None):
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=cat,
        product_code=code,
        leaf=leaf,
        item_quantity=qty,
        classification=classification,
        state=HardwareItemState.AVAILABLE,
    )
    session.add(hi)
    session.flush()
    return hi


def _assembled(session, project, opening, *, leaf, installed, state=OpeningItemState.IN_INVENTORY):
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=opening.opening_number,
        leaf=leaf,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=state,
    )
    session.add(oi)
    session.flush()
    for cat, code, qty in installed:
        session.add(
            OpeningItemHardware(
                id=uuid.uuid4(),
                opening_item_id=oi.id,
                hardware_category=cat,
                product_code=code,
                quantity=qty,
            )
        )
    session.flush()
    return oi


def _po_line(session, project, *, ordered, received, code="HG-100", cat="HINGE", status=POStatus.GP_REGISTERED):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=status,
    )
    session.add(po)
    session.flush()
    session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=cat,
            product_code=code,
            ordered_quantity=ordered,
            received_quantity=received,
            unit_cost=Decimal("1.00"),
        )
    )
    session.flush()
    return po


def _coverage(session, project, numbers=("101",)):
    return shipping_coverage.get_shipping_coverage(session, project.id, list(numbers))


def _line(leaf_row, code="HG-100"):
    return next(line for line in leaf_row["lines"] if line["product_code"] == code)


def test_site_hardware_is_owed_in_full_even_on_an_assembled_leaf(db_session):
    # Site hardware is installed at site, so it never goes through shop assembly. Netting it against
    # what is on the leaf would suggest 0 and quietly ship the door without its locks.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(
        db_session,
        project,
        opening,
        leaf=1,
        code="LK-9",
        cat="LOCK",
        qty=2,
        classification=Classification.SITE_HARDWARE,
    )
    _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)])

    line = _line(_coverage(db_session, project)[0], "LK-9")
    assert line["classification"] is Classification.SITE_HARDWARE
    assert (line["owed_quantity"], line["installed_quantity"], line["suggested_quantity"]) == (2, 0, 2)


def test_shop_hardware_suggests_only_what_assembly_skipped(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=4, classification=Classification.SHOP_HARDWARE)
    _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)])

    line = _line(_coverage(db_session, project)[0])
    assert (line["owed_quantity"], line["installed_quantity"], line["suggested_quantity"]) == (4, 3, 1)


def test_a_fully_assembled_shop_line_owes_nothing_loose(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)
    _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)])

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 0


def test_an_unassembled_leaf_owes_everything_and_reads_not_assembled(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)

    row = _coverage(db_session, project)[0]
    assert row["status"] == "NOT_ASSEMBLED"
    assert row["opening_item_id"] is None
    assert _line(row)["suggested_quantity"] == 3


def test_over_supplied_leaf_owes_nothing_rather_than_a_negative(db_session):
    # The schedule was revised down after the leaf was built. It is over-supplied, not owed -3.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=1, classification=Classification.SHOP_HARDWARE)
    _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 4)])

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 0


def test_hardware_on_the_leaf_that_the_schedule_no_longer_lists_still_shows(db_session):
    # It is physically on the door. Hiding the line would make the leaf look emptier than it is.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=2, classification=Classification.SHOP_HARDWARE)
    _assembled(
        db_session,
        project,
        opening,
        leaf=1,
        installed=[("HINGE", "HG-100", 2), ("CLOSER", "CL-1", 1)],
    )

    line = _line(_coverage(db_session, project)[0], "CL-1")
    assert (line["owed_quantity"], line["installed_quantity"], line["suggested_quantity"]) == (0, 1, 0)
    assert line["classification"] is None


def test_a_pair_is_two_rows_and_each_leaf_carries_its_own_state(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)
    _hardware(db_session, project, opening, leaf=2, qty=3, classification=Classification.SHOP_HARDWARE)
    _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)])

    rows = _coverage(db_session, project)
    assert [(r["leaf"], r["status"]) for r in rows] == [(1, "IN_INVENTORY"), (2, "NOT_ASSEMBLED")]
    assert _line(rows[0])["suggested_quantity"] == 0
    assert _line(rows[1])["suggested_quantity"] == 3


def test_leaves_the_schedule_never_named_still_appear_from_leaf_count(db_session):
    # leaf_count is the denominator the rest of the chain trusts. A pair whose schedule only
    # attributes leaf 1 must still offer leaf 2, or half the door is invisible to the shipper.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)

    assert [r["leaf"] for r in _coverage(db_session, project)] == [1, 2]


def test_leafless_schedule_lines_fold_onto_the_lowest_leaf(db_session):
    # Otherwise those units strand on a phantom third leaf nobody can select.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _hardware(db_session, project, opening, leaf=1, qty=1, classification=Classification.SHOP_HARDWARE)
    _hardware(
        db_session,
        project,
        opening,
        leaf=None,
        code="LK-9",
        cat="LOCK",
        qty=2,
        classification=Classification.SITE_HARDWARE,
    )

    rows = _coverage(db_session, project)
    assert [r["leaf"] for r in rows] == [1, 2]
    assert _line(rows[0], "LK-9")["owed_quantity"] == 2
    assert all(line["product_code"] != "LK-9" for line in rows[1]["lines"])


def test_a_legacy_opening_with_no_leaf_data_is_one_leafless_row(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=None)
    _hardware(db_session, project, opening, leaf=None, qty=2, classification=Classification.SITE_HARDWARE)

    rows = _coverage(db_session, project)
    assert len(rows) == 1
    assert rows[0]["leaf"] is None
    assert _line(rows[0])["suggested_quantity"] == 2


def test_a_legacy_null_leaf_unit_matches_the_openings_single_leaf(db_session):
    # The schedule numbers it leaf 1, the assembled unit predates leaves. Without the fallback the
    # leaf reads NOT_ASSEMBLED while its hardware is physically bolted on.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)
    _assembled(db_session, project, opening, leaf=None, installed=[("HINGE", "HG-100", 3)])

    row = _coverage(db_session, project)[0]
    assert row["status"] == "IN_INVENTORY"
    assert _line(row)["suggested_quantity"] == 0


def test_a_live_leaf_wins_over_one_that_already_shipped(db_session):
    # The leaf was re-assembled after the first one went out. The shipper cares about the one still
    # in the building.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=3, classification=Classification.SHOP_HARDWARE)
    _assembled(
        db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)], state=OpeningItemState.SHIPPED_OUT
    )
    live = _assembled(db_session, project, opening, leaf=1, installed=[("HINGE", "HG-100", 3)])

    row = _coverage(db_session, project)[0]
    assert row["opening_item_id"] == live.id
    assert row["status"] == "IN_INVENTORY"


def test_on_order_counts_placed_pos_and_nets_off_what_arrived(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=5, classification=Classification.SITE_HARDWARE)
    _po_line(db_session, project, ordered=10, received=4)

    assert _line(_coverage(db_session, project)[0])["on_order_quantity"] == 6


def test_a_draft_po_is_not_on_the_way(db_session):
    # Nobody has ordered it. Telling a shipper to wait for it would be a lie.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=5, classification=Classification.SITE_HARDWARE)
    _po_line(db_session, project, ordered=10, received=0, status=POStatus.DRAFT)

    assert _line(_coverage(db_session, project)[0])["on_order_quantity"] == 0


def test_an_over_received_line_does_not_cancel_another_lines_backorder(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=5, classification=Classification.SITE_HARDWARE)
    _po_line(db_session, project, ordered=2, received=6)
    _po_line(db_session, project, ordered=5, received=0)

    assert _line(_coverage(db_session, project)[0])["on_order_quantity"] == 5


def test_another_projects_stock_is_never_counted(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=5, classification=Classification.SITE_HARDWARE)
    _po_line(db_session, _project(db_session), ordered=10, received=0)

    assert _line(_coverage(db_session, project)[0])["on_order_quantity"] == 0


def test_unknown_and_unselected_openings_are_simply_absent(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, number="101", leaf_count=1)
    other = _opening(db_session, project, number="102", leaf_count=1)
    _hardware(db_session, project, opening, leaf=1, qty=1, classification=Classification.SITE_HARDWARE)
    _hardware(db_session, project, other, leaf=1, qty=1, classification=Classification.SITE_HARDWARE)

    assert [r["opening_number"] for r in _coverage(db_session, project, ["101"])] == ["101"]
    assert _coverage(db_session, project, ["nope"]) == []
    assert _coverage(db_session, project, []) == []
