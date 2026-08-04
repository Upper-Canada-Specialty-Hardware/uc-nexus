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

from app.models.enums import (
    Classification,
    HardwareItemState,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ShipmentStatus,
    ShippingOutRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.opening_item import OpeningItem, OpeningItemHardware
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
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


# --- What the opening has already been sent ------------------------------------------------------
# `owed` is the schedule, and the schedule does not shrink when hardware goes out the door. Without
# these, an opening whose site hardware shipped last month is offered in full again, and the only
# thing between that and a second set leaving the building is project-wide availability - which
# belongs to the whole job, not to this opening.


def _slip(session, project, *, opening_number="101", code="HG-100", cat="HINGE", qty=1):
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="tester",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
    )
    session.add(slip)
    session.flush()
    session.add(
        PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=slip.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=opening_number,
            hardware_category=cat,
            product_code=code,
            quantity=qty,
        )
    )
    session.flush()
    return slip


def _pull(session, project, *, status, opening_number="101", code="HG-100", cat="HINGE", qty=1):
    pull = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=status,
        requested_by="tester",
    )
    session.add(pull)
    session.flush()
    session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pull.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=opening_number,
            hardware_category=cat,
            product_code=code,
            requested_quantity=qty,
        )
    )
    session.flush()
    return pull


def _request(session, project, *, status, opening_number="101", code="HG-100", cat="HINGE", qty=1):
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=status,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    session.add(
        ShippingOutRequestItem(
            id=uuid.uuid4(),
            shipping_out_request_id=req.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=opening_number,
            hardware_category=cat,
            product_code=code,
            requested_quantity=qty,
        )
    )
    session.flush()
    return req


def _site_opening(session, project, *, qty, leaf_count=1):
    opening = _opening(session, project, leaf_count=leaf_count)
    for leaf in range(1, leaf_count + 1):
        _hardware(session, project, opening, leaf=leaf, qty=qty, classification=Classification.SITE_HARDWARE)
    return opening


def test_hardware_already_shipped_is_not_offered_again(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=2)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=2)
    _slip(db_session, project, qty=2)

    line = _line(_coverage(db_session, project)[0])
    assert (line["owed_quantity"], line["spoken_for_quantity"], line["suggested_quantity"]) == (2, 2, 0)


def test_a_partial_shipment_leaves_only_the_remainder_on_offer(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=5)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=2)
    _slip(db_session, project, qty=2)

    line = _line(_coverage(db_session, project)[0])
    assert (line["spoken_for_quantity"], line["suggested_quantity"]) == (2, 3)


def test_units_pulled_but_not_yet_loaded_are_not_offered_twice(db_session):
    # A completed pull moved the stock to the staging floor. It is not on a slip yet, and it is also
    # not free to promise a second time.
    project = _project(db_session)
    _site_opening(db_session, project, qty=4)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=3)

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 1


def test_a_shipped_unit_is_counted_once_not_twice(db_session):
    # The pull fulfilled it and the slip then consumed it. Counting both would read as 4 of 4 owed
    # already gone when only 2 ever moved.
    project = _project(db_session)
    _site_opening(db_session, project, qty=4)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=2)
    _slip(db_session, project, qty=2)

    assert _line(_coverage(db_session, project)[0])["spoken_for_quantity"] == 2


def test_a_pull_still_being_picked_counts_as_spoken_for(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=4)
    _pull(db_session, project, status=PullRequestStatus.IN_PROGRESS, qty=3)

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 1


def test_a_pending_request_counts_but_an_accepted_one_is_left_to_its_pull(db_session):
    # The accept copies the request's lines onto a pull, so counting both would double the claim.
    project = _project(db_session)
    _site_opening(db_session, project, qty=4)
    _request(db_session, project, status=ShippingOutRequestStatus.PENDING, qty=2)
    _request(db_session, project, status=ShippingOutRequestStatus.APPROVED, qty=2)
    _pull(db_session, project, status=PullRequestStatus.PENDING, qty=2)

    assert _line(_coverage(db_session, project)[0])["spoken_for_quantity"] == 4


def test_a_cancelled_pull_gives_the_units_back(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=3)
    _pull(db_session, project, status=PullRequestStatus.CANCELLED, qty=3)

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 3


def test_a_rejected_request_gives_the_units_back(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=3)
    _request(db_session, project, status=ShippingOutRequestStatus.REJECTED, qty=3)

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 3


def test_a_shop_assembly_pull_is_not_a_shipment(db_session):
    # Hardware pulled to the bench was fitted onto the leaf. That is `installed`, and counting it
    # here as well would net the same units off twice.
    project = _project(db_session)
    _site_opening(db_session, project, qty=3)
    pull = _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=3)
    pull.source = PullRequestSource.SHOP_ASSEMBLY
    db_session.flush()

    assert _line(_coverage(db_session, project)[0])["suggested_quantity"] == 3


def test_what_one_opening_sent_does_not_cover_another(db_session):
    project = _project(db_session)
    _site_opening(db_session, project, qty=2)
    other = _opening(db_session, project, number="102", leaf_count=1)
    _hardware(db_session, project, other, leaf=1, qty=2, classification=Classification.SITE_HARDWARE)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, opening_number="101", qty=2)

    rows = {row["opening_number"]: row for row in _coverage(db_session, project, ["101", "102"])}
    assert _line(rows["101"])["suggested_quantity"] == 0
    assert _line(rows["102"])["suggested_quantity"] == 2


def test_leaves_share_one_openings_sent_units_rather_than_each_paying_them(db_session):
    # A loose line carries an opening and never a leaf, so what went out is only ever known per
    # opening. Charging every leaf the whole history would zero a pair that has sent one leaf worth.
    project = _project(db_session)
    _site_opening(db_session, project, qty=1, leaf_count=2)
    _pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=1)

    rows = _coverage(db_session, project)
    assert [_line(row)["suggested_quantity"] for row in rows] == [0, 1]
