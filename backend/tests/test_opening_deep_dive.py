"""Where every unit of an opening's hardware is, for the admin Opening Status page.

The page's whole claim is that the buckets it shows PARTITION the schedule: every unit an opening is
owed lands in exactly one of them, so the row totals mean something and nothing is counted twice.
Most of what is pinned here is that invariant surviving each step of the lifecycle, plus the two
things the previous implementation got wrong - openings that merely share a number across projects,
and hardware that is not on a purchase order at all reading as though it were drafted.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.enums import (
    AssemblyStatus,
    Classification,
    HardwareItemState,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
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
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.repositories import opening_deep_dive, warehouse_admin_repository

CAT = "HINGE"
CODE = "HG-100"


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _opening(session, project, number="101", leaf_count=1) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=number, leaf_count=leaf_count)
    session.add(o)
    session.flush()
    return o


def _hardware(session, project, opening, *, leaf=1, code=CODE, cat=CAT, qty=4, po_line=None, classification=None):
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=cat,
        product_code=code,
        leaf=leaf,
        item_quantity=qty,
        classification=classification,
        state=HardwareItemState.IN_PO if po_line is not None else HardwareItemState.AVAILABLE,
        po_line_item_id=po_line.id if po_line is not None else None,
    )
    session.add(hi)
    session.flush()
    return hi


def _po(session, project, *, status=POStatus.GP_REGISTERED, ordered=4, received=0, code=CODE, cat=CAT, deleted=False):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=status,
        deleted_at=datetime.utcnow() if deleted else None,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category=cat,
        product_code=code,
        ordered_quantity=ordered,
        received_quantity=received,
        unit_cost=Decimal("1.00"),
    )
    session.add(line)
    session.flush()
    return po, line


def _assembled(session, project, opening, *, leaf=1, installed=((CAT, CODE, 4),), state=OpeningItemState.IN_INVENTORY):
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


def _assembly_work_unit(
    session,
    project,
    opening,
    *,
    leaf=1,
    allocated=4,
    quantity=None,
    assembly_status=AssemblyStatus.PENDING,
    pull_status=PullRequestStatus.IN_PROGRESS,
    detached=False,
):
    """A live shop-assembly work unit holding `allocated` units of the default product.

    `detached=True` nulls pull_request_id, which is what cancelling a pull does - the hardware went
    back on the shelf, so the opening is owed it again.
    """
    pull = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=pull_status,
        requested_by="tester",
    )
    session.add(pull)
    session.flush()
    sao = ShopAssemblyOpening(
        id=uuid.uuid4(),
        pull_request_id=None if detached else pull.id,
        opening_id=opening.id,
        opening_number=opening.opening_number,
        leaf=leaf,
        pull_status=PullStatus.NOT_PULLED,
        assembly_status=assembly_status,
    )
    session.add(sao)
    session.flush()
    session.add(
        ShopAssemblyOpeningItem(
            id=uuid.uuid4(),
            shop_assembly_opening_id=sao.id,
            hardware_category=CAT,
            product_code=CODE,
            quantity=allocated if quantity is None else quantity,
            allocated_quantity=allocated,
        )
    )
    session.flush()
    return sao


def _slip(session, project, *, opening_number="101", qty=2, code=CODE, cat=CAT):
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


def _shipping_pull(session, project, *, status, opening_number="101", qty=2):
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
            hardware_category=CAT,
            product_code=CODE,
            requested_quantity=qty,
        )
    )
    session.flush()
    return pull


def _shipping_request(session, project, *, opening_number="101", leaf=1, opening_item=None):
    """A PENDING shipping-out request claiming one assembled leaf."""
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=ShippingOutRequestStatus.PENDING,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    session.add(
        ShippingOutRequestItem(
            id=uuid.uuid4(),
            shipping_out_request_id=req.id,
            item_type=PullRequestItemType.OPENING_ITEM,
            opening_number=opening_number,
            opening_item_id=opening_item.id if opening_item is not None else None,
            leaf=leaf,
            requested_quantity=1,
        )
    )
    session.flush()
    return req


def _dive(session, project, number="101"):
    return opening_deep_dive.get_opening_deep_dive(session, project.id, number)


def _line(dive, *, leaf=1, code=CODE):
    return next(line for line in dive.lines if line.leaf == leaf and line.product_code == code)


def _buckets(line) -> dict:
    return {
        "shipped_on_leaf": line.shipped_on_leaf,
        "shipped_loose": line.shipped_loose,
        "staged": line.staged,
        "pulled_for_shipping": line.pulled_for_shipping,
        "assembled_in_inventory": line.assembled_in_inventory,
        "pulled_for_assembly": line.pulled_for_assembly,
        "ordered": line.ordered,
        "po_drafted": line.po_drafted,
        "not_purchased": line.not_purchased,
    }


def _assert_partitions(dive):
    """The invariant the whole page rests on: every owed unit is accounted for by exactly one bucket.

    Equality rather than `>=` in these tests because none of them over-assemble a leaf; the one case
    that legitimately exceeds `owed_quantity` asserts its own numbers.
    """
    for line in dive.lines:
        assert sum(_buckets(line).values()) == line.owed_quantity, line
        assert all(value >= 0 for value in _buckets(line).values()), line


# --- procurement buckets -------------------------------------------------------------------------


def test_hardware_on_no_purchase_order_reads_not_purchased(db_session):
    # The bug this replaces: the old else-branch called this "PO Drafted", so "nobody has bought it"
    # and "it is on a draft" were the same chip.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _hardware(db_session, project, opening, qty=4)

    dive = _dive(db_session, project)
    assert _buckets(_line(dive))["not_purchased"] == 4
    _assert_partitions(dive)


def test_draft_and_placed_purchase_orders_read_apart(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, draft_line = _po(db_session, project, status=POStatus.DRAFT, ordered=2)
    _, placed_line = _po(db_session, project, status=POStatus.GP_REGISTERED, ordered=3)
    _hardware(db_session, project, opening, qty=2, po_line=draft_line)
    _hardware(db_session, project, opening, qty=3, po_line=placed_line)

    line = _line(_dive(db_session, project))
    assert (line.owed_quantity, line.po_drafted, line.ordered) == (5, 2, 3)


def test_a_cancelled_purchase_order_releases_its_hardware_to_not_purchased(db_session):
    # Cancelling soft-deletes the PO, and a dead PO cannot own hardware.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, status=POStatus.CANCELLED, deleted=True)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)

    assert _buckets(_line(_dive(db_session, project)))["not_purchased"] == 4


def test_a_closed_purchase_order_still_reads_ordered_with_its_fill_carried(db_session):
    # Receiving is fungible, so "received" is never a per-opening state. The line's fill rides along
    # as context instead.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, status=POStatus.CLOSED, ordered=100, received=40)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)

    line = _line(_dive(db_session, project))
    assert line.ordered == 4
    assert [(ref.ordered_quantity, ref.received_quantity) for ref in line.po_lines] == [(100, 40)]


def test_a_product_split_across_two_purchase_orders_keeps_both_references(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, first = _po(db_session, project, ordered=10, received=10)
    _, second = _po(db_session, project, ordered=5, received=0)
    _hardware(db_session, project, opening, qty=2, po_line=first)
    _hardware(db_session, project, opening, qty=3, po_line=second)

    line = _line(_dive(db_session, project))
    assert line.ordered == 5
    assert sorted((ref.ordered_quantity, ref.received_quantity) for ref in line.po_lines) == [(5, 0), (10, 10)]


# --- the fulfilment partition --------------------------------------------------------------------


def test_units_on_the_bench_leave_the_ordered_bucket(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembly_work_unit(db_session, project, opening, allocated=3)

    dive = _dive(db_session, project)
    buckets = _buckets(_line(dive))
    assert (buckets["pulled_for_assembly"], buckets["ordered"]) == (3, 1)
    _assert_partitions(dive)


def test_a_cancelled_assembly_pull_gives_its_units_back(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembly_work_unit(db_session, project, opening, allocated=4, pull_status=PullRequestStatus.CANCELLED)

    buckets = _buckets(_line(_dive(db_session, project)))
    assert (buckets["pulled_for_assembly"], buckets["ordered"]) == (0, 4)


def test_a_detached_assembly_opening_gives_its_units_back(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembly_work_unit(db_session, project, opening, allocated=4, detached=True)

    assert _buckets(_line(_dive(db_session, project)))["pulled_for_assembly"] == 0


def test_a_completed_work_unit_is_counted_as_assembled_not_as_pulled(db_session):
    # The completed work unit and the OpeningItem it produced describe the same hardware. Counting
    # both would double the leaf's units and break the partition.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembly_work_unit(db_session, project, opening, allocated=4, assembly_status=AssemblyStatus.COMPLETED)
    _assembled(db_session, project, opening, installed=[(CAT, CODE, 4)])

    dive = _dive(db_session, project)
    buckets = _buckets(_line(dive))
    assert (buckets["assembled_in_inventory"], buckets["pulled_for_assembly"], buckets["ordered"]) == (4, 0, 0)
    _assert_partitions(dive)


def test_the_leaf_state_moves_the_units_through_staged_and_shipped(db_session):
    for state, bucket in (
        (OpeningItemState.IN_INVENTORY, "assembled_in_inventory"),
        (OpeningItemState.SHIP_READY, "staged"),
        (OpeningItemState.SHIPPED_OUT, "shipped_on_leaf"),
    ):
        project = _project(db_session)
        opening = _opening(db_session, project)
        _, line_item = _po(db_session, project, ordered=4)
        _hardware(db_session, project, opening, qty=4, po_line=line_item)
        _assembled(db_session, project, opening, installed=[(CAT, CODE, 4)], state=state)

        dive = _dive(db_session, project)
        assert _buckets(_line(dive))[bucket] == 4, state
        _assert_partitions(dive)


def test_hardware_installed_off_an_older_revision_is_reported_as_found(db_session):
    # owed 0, installed 3. Clamping the bucket to what the schedule owes would report 0 for hardware
    # that is physically bolted to the door, so the fulfilment buckets are never clamped.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _assembled(db_session, project, opening, installed=[("LOCK", "LK-9", 3)])

    line = _line(_dive(db_session, project), code="LK-9")
    assert (line.owed_quantity, line.assembled_in_inventory) == (0, 3)


# --- loose hardware, which never touches a leaf ---------------------------------------------------


def test_site_hardware_shipped_loose_stops_reading_as_merely_ordered(db_session):
    # The reason loose units are folded onto the leaf lines at all: site hardware never reaches an
    # OpeningItem, so without this it would read "ordered" for ever after it had physically shipped.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item, classification=Classification.SITE_HARDWARE)
    _shipping_pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=4)
    _slip(db_session, project, qty=4)

    dive = _dive(db_session, project)
    buckets = _buckets(_line(dive))
    assert (buckets["shipped_loose"], buckets["ordered"]) == (4, 0)
    assert dive.loose == []
    _assert_partitions(dive)


def test_a_live_shipping_claim_reads_as_pulled_for_shipping(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _shipping_pull(db_session, project, status=PullRequestStatus.IN_PROGRESS, qty=3)

    buckets = _buckets(_line(_dive(db_session, project)))
    assert (buckets["pulled_for_shipping"], buckets["ordered"]) == (3, 1)


def test_a_staged_pull_and_its_slip_are_not_counted_twice(db_session):
    # A shipped unit was fulfilled first, so the completed pull and the slip describe the same two
    # units. max(shipped, fulfilled) is what folds them.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _shipping_pull(db_session, project, status=PullRequestStatus.COMPLETED, qty=2)
    _slip(db_session, project, qty=2)

    dive = _dive(db_session, project)
    buckets = _buckets(_line(dive))
    assert (buckets["shipped_loose"], buckets["pulled_for_shipping"], buckets["ordered"]) == (2, 0, 2)
    _assert_partitions(dive)


def test_the_loose_budget_is_shared_across_the_leaves_of_a_pair(db_session):
    # A loose line carries an opening and never a leaf, so four shipped units of a product owed two
    # per leaf cover both leaves rather than each leaf claiming all four.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, leaf=1, qty=2, po_line=line_item)
    _hardware(db_session, project, opening, leaf=2, qty=2, po_line=line_item)
    _slip(db_session, project, qty=4)

    dive = _dive(db_session, project)
    assert _buckets(_line(dive, leaf=1))["shipped_loose"] == 2
    assert _buckets(_line(dive, leaf=2))["shipped_loose"] == 2
    _assert_partitions(dive)


def test_loose_units_no_leaf_can_account_for_are_surfaced_separately(db_session):
    # An over-ship. The units left the building, so they have to appear somewhere.
    project = _project(db_session)
    opening = _opening(db_session, project)
    _hardware(db_session, project, opening, qty=1)
    _slip(db_session, project, qty=5)

    dive = _dive(db_session, project)
    assert _buckets(_line(dive))["shipped_loose"] == 1
    assert [(row.product_code, row.shipped_loose) for row in dive.loose] == [(CODE, 4)]


# --- scoping, leaves and the list rollup ----------------------------------------------------------


def test_openings_sharing_a_number_across_projects_stay_separate(db_session):
    # The defect this page is being rebuilt for: the old rollup keyed on opening_number alone and
    # merged these two into one row.
    first = _project(db_session)
    second = _project(db_session)
    _hardware(db_session, first, _opening(db_session, first, number="101"), qty=4)
    _hardware(db_session, second, _opening(db_session, second, number="101"), qty=9, code="LK-9", cat="LOCK")

    first_rows = opening_deep_dive.get_project_opening_statuses(db_session, first.id)
    second_rows = opening_deep_dive.get_project_opening_statuses(db_session, second.id)
    assert [(row.opening_number, row.owed_units) for row in first_rows] == [("101", 4)]
    assert [(row.opening_number, row.owed_units) for row in second_rows] == [("101", 9)]


def test_leafless_schedule_lines_fold_onto_the_lowest_leaf(db_session):
    # A frame line TITAN did not attribute would otherwise strand units on a phantom third leaf.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _hardware(db_session, project, opening, leaf=None, qty=2)

    dive = _dive(db_session, project)
    assert [line.leaf for line in dive.lines] == [1]
    assert _line(dive, leaf=1).owed_quantity == 2


def test_every_expected_leaf_is_listed_even_when_nothing_is_assembled(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _hardware(db_session, project, opening, leaf=1, qty=2)
    _hardware(db_session, project, opening, leaf=2, qty=2)

    dive = _dive(db_session, project)
    assert [(leaf.leaf, leaf.status) for leaf in dive.leaves] == [(1, "NOT_ASSEMBLED"), (2, "NOT_ASSEMBLED")]


def test_a_live_shipping_request_names_the_leaf_it_holds(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _hardware(db_session, project, opening, qty=4)
    unit = _assembled(db_session, project, opening, state=OpeningItemState.SHIP_READY)
    request = _shipping_request(db_session, project, opening_item=unit)

    assert _dive(db_session, project).leaf_claims == {1: request.request_number}


def test_the_list_row_totals_are_the_sums_of_the_deep_dive_lines(db_session):
    # The row and its detail must agree by construction - they are the same partition.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _, line_item = _po(db_session, project, ordered=8)
    _hardware(db_session, project, opening, leaf=1, qty=4, po_line=line_item)
    _hardware(db_session, project, opening, leaf=2, qty=4, po_line=line_item)
    _assembled(db_session, project, opening, leaf=1, installed=[(CAT, CODE, 4)])
    _assembly_work_unit(db_session, project, opening, leaf=2, allocated=3)

    row = opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0]
    dive = _dive(db_session, project)
    assert row.owed_units == sum(line.owed_quantity for line in dive.lines) == 8
    assert row.assembled_units == 4
    assert row.pulled_units == 3
    assert row.ordered_units == 1


# --- the headline stage ---------------------------------------------------------------------------


def test_stage_is_not_started_when_nothing_has_been_bought(db_session):
    project = _project(db_session)
    _hardware(db_session, project, _opening(db_session, project), qty=4)

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "NOT_STARTED"


def test_stage_is_ordering_while_anything_is_undrafted_or_drafted(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, draft_line = _po(db_session, project, status=POStatus.DRAFT, ordered=2)
    _hardware(db_session, project, opening, qty=2, po_line=draft_line)

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "ORDERING"


def test_stage_is_assembly_once_everything_is_on_a_placed_order(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "ASSEMBLY"


def test_stage_is_shipping_once_every_leaf_is_assembled(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembled(db_session, project, opening, installed=[(CAT, CODE, 4)])

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "SHIPPING"


def test_stage_is_complete_once_every_leaf_has_shipped(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, qty=4, po_line=line_item)
    _assembled(db_session, project, opening, installed=[(CAT, CODE, 4)], state=OpeningItemState.SHIPPED_OUT)

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "COMPLETE"


def test_stage_names_the_furthest_behind_leaf_not_the_furthest_along(db_session):
    # Leaf 1 has shipped, leaf 2 was never bought. What is holding the opening up is leaf 2.
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _, line_item = _po(db_session, project, ordered=4)
    _hardware(db_session, project, opening, leaf=1, qty=4, po_line=line_item)
    _hardware(db_session, project, opening, leaf=2, qty=4)
    _assembled(db_session, project, opening, leaf=1, installed=[(CAT, CODE, 4)], state=OpeningItemState.SHIPPED_OUT)

    assert opening_deep_dive.get_project_opening_statuses(db_session, project.id)[0].stage == "ORDERING"
