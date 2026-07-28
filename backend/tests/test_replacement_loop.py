"""The deficiency replacement loop and the shipping deficiency guard (#341).

Since #340 a unit found defective at the bench is condemned on the spot: back to inventory flagged
deficient, PR-REPL replacement line minted immediately. Nothing ever brought the replacement back -
`complete_pull_request` looked for ShopAssemblyOpenings hanging off the PR-REPL pull, found none
(nothing hangs off a replacement PR), and completed as a silent no-op.

Covered here: the arrival restoring the leaf's expectation on a leaf still on the bench, the floor
that keeps an over-delivery from breaching the progress constraint, the completed-leaf case that has
to move the unit into `replacement_pending_quantity` rather than corrupt the completion invariant,
installing that unit onto the finished leaf (both when the product already has an
OpeningItemHardware row and when the line was entirely deficient at completion and has none), the
shipping guard's warn-and-confirm, and the shipped-leaf case that must be notified and stay
queryable rather than stranded.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    NotificationType,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.notification import Notification
from app.models.opening_item import OpeningItemHardware
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull

HINGE = ("HINGE", "HG-R1")
LOCK = ("LOCK", "LK-R1")


# --- fixtures ----------------------------------------------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category, code, quantity=0):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
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
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _make_pulled_opening(session, project_id, *, request_number, items, leaf=1, assigned_user="user_1"):
    """A COMPLETED SHOP_ASSEMBLY pull request with one PULLED, assigned, untouched opening."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=request_number,
        project_id=project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
        completed_at=datetime.utcnow(),
    )
    session.add(pr)
    session.flush()

    opening = ShopAssemblyOpening(
        id=uuid.uuid4(),
        pull_request_id=pr.id,
        opening_id=uuid.uuid4(),
        opening_number="R01",
        leaf=leaf,
        pull_status=PullStatus.PULLED,
        assigned_to="assembler" if assigned_user else None,
        assigned_to_user_id=assigned_user,
        assembly_status=AssemblyStatus.PENDING,
    )
    session.add(opening)
    session.flush()

    sao_items = {}
    # `items` entries are (category, code, owed) or (category, code, owed, allocated). Omitting the
    # fourth means fully allocated - the ordinary case, and the only one that existed before partial
    # allocation. A test that wants a short line says so explicitly.
    for category, code, qty, *rest in items:
        allocated = rest[0] if rest else qty
        sao_item = ShopAssemblyOpeningItem(
            id=uuid.uuid4(),
            shop_assembly_opening_id=opening.id,
            hardware_category=category,
            product_code=code,
            quantity=qty,
            allocated_quantity=allocated,
        )
        session.add(sao_item)
        sao_items[code] = sao_item
    session.flush()
    return opening, sao_items


def _flag_deficient(session, opening, sao_item, quantity, *, reason="Bent"):
    """Run the real deficiency path so the PR-REPL pull and its stamped line exist for real."""
    shop_assembly_repository.record_assembly_progress(
        session,
        opening.id,
        [
            shop_assembly_repository.AssemblyProgressUpdate(
                shop_assembly_opening_item_id=sao_item.id,
                flag_deficient_quantity=quantity,
                deficient_reason=reason,
            )
        ],
        performed_by="ada",
    )
    session.flush()


def _repl_pull_for(session, sao_item) -> PullRequest:
    """The PR-REPL pull request holding the replacement line for this checklist item."""
    line = session.scalars(select(PullRequestItem).where(PullRequestItem.sa_opening_item_id == sao_item.id)).first()
    assert line is not None, "report_deficiency_at_assembly should have minted a stamped PR-REPL line"
    return session.get(PullRequest, line.pull_request_id)


def _work_the_pull(session, pr, *, status=PullRequestStatus.IN_PROGRESS):
    pr.status = status
    session.flush()
    return pr


def _complete(session, opening, sao_items):
    """Install everything not already condemned, then finish the leaf for real."""
    updates = [
        shop_assembly_repository.AssemblyProgressUpdate(
            shop_assembly_opening_item_id=item.id,
            # What arrived, minus what was condemned. Short units were never pulled, so there is
            # nothing on the cart for them and completion excuses them.
            installed_quantity=item.allocated_quantity - item.deficient_quantity,
        )
        for item in sao_items.values()
    ]
    shop_assembly_repository.record_assembly_progress(session, opening.id, updates, performed_by="ada")
    session.flush()
    return shop_assembly_repository.complete_opening(session, opening.id, "A", "1", "B", completed_by="ada")


# --- 1. arrival restores the leaf's expectation --------------------------------------------------


def test_repl_completion_restores_expectation_on_an_in_progress_leaf(db_session):
    """The whole point: the freed unit goes back to being remaining work, and the leaf cannot be
    called finished until somebody actually fits it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R1", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]

    _flag_deficient(db_session, opening, item, 2)
    assert item.deficient_quantity == 2
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    assert item.deficient_quantity == 0
    # Nothing pending: on an unfinished leaf the unit is just remaining work again.
    assert item.replacement_pending_quantity == 0
    assert item.quantity - item.installed_quantity - item.deficient_quantity == 4

    # And completion is still blocked on it.
    with pytest.raises(ValidationError):
        shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)


def test_repl_completion_writes_an_audit_row(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R1A", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    events = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.entity_id == opening.id,
                InventoryAuditLog.action == AuditAction.REPLACEMENT_RECEIVED,
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].entity_type == AuditEntityType.SHOP_ASSEMBLY_OPENING
    assert events[0].detail["restoredQuantity"] == 2
    assert events[0].detail["deficientQuantity"] == 0
    assert events[0].detail["assemblyStatus"] == AssemblyStatus.IN_PROGRESS.value


def test_over_delivery_floors_at_what_is_outstanding(db_session):
    """A line asking for more than is still deficient - a duplicate line, or a hand-edited pull -
    must not drive the counter negative or breach the progress check constraint."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R2", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)

    repl = _repl_pull_for(db_session, item)
    # Second stamped line for the same checklist item, so the pull "delivers" 4 against 1 outstanding.
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=repl.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=opening.opening_number,
            leaf=opening.leaf,
            sa_opening_item_id=item.id,
            hardware_category=HINGE[0],
            product_code=HINGE[1],
            requested_quantity=3,
        )
    )
    db_session.flush()

    _work_the_pull(db_session, repl)
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    assert item.deficient_quantity == 0
    assert item.replacement_pending_quantity == 0
    assert item.installed_quantity == 0


def test_a_second_completed_repl_pull_restores_nothing_extra(db_session):
    """Idempotence at the outer edge: replaying a completion cannot mint expectation from nothing."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R3", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()
    assert item.deficient_quantity == 0

    repl.status = PullRequestStatus.IN_PROGRESS
    db_session.flush()
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()
    assert item.deficient_quantity == 0
    assert item.replacement_pending_quantity == 0


# --- 2. the completed leaf ----------------------------------------------------------------------


def test_completed_leaf_gets_pending_replacement_not_a_broken_invariant(db_session):
    """The design problem: lowering deficient_quantity on a finished leaf would make it read as
    un-dispositioned. The unit moves into replacement_pending instead, so the three counts still
    sum to exactly quantity and the leaf stays legitimately complete."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R4", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)
    _complete(db_session, opening, sao)
    assert opening.assembly_status == AssemblyStatus.COMPLETED
    assert (item.installed_quantity, item.deficient_quantity) == (3, 1)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    assert item.deficient_quantity == 0
    assert item.replacement_pending_quantity == 1
    # Completion invariant intact: nothing is un-dispositioned.
    assert item.installed_quantity + item.deficient_quantity + item.replacement_pending_quantity == item.quantity
    assert opening.assembly_status == AssemblyStatus.COMPLETED


def test_pending_replacement_surfaces_as_work_for_the_last_assembler(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R5", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)
    leaf = _complete(db_session, opening, sao)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    work = shop_assembly_repository.get_replacement_work(db_session, assigned_to_user_id="user_1")
    assert len(work) == 1
    assert work[0].shop_assembly_opening_item_id == item.id
    assert work[0].pending_quantity == 2
    assert work[0].product_code == HINGE[1]
    assert work[0].opening_item_id == leaf.id
    assert work[0].opening_item_state == OpeningItemState.IN_INVENTORY

    # Someone else's board does not show it.
    assert shop_assembly_repository.get_replacement_work(db_session, assigned_to_user_id="user_2") == []


def test_a_manager_can_reassign_a_completed_leaf_that_has_pending_replacements(db_session):
    """ "Reassignable" rides the existing assign flow: a COMPLETED opening becomes assignable again
    exactly while it has replacement installs outstanding, and not otherwise."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R6", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)
    _complete(db_session, opening, sao)

    # Completed, nothing outstanding yet: still refused.
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob", allow_reassign=True)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob", allow_reassign=True)
    db_session.flush()
    assert opening.assigned_to_user_id == "user_2"
    assert shop_assembly_repository.get_replacement_work(db_session, assigned_to_user_id="user_2")[0].assigned_to == (
        "Bob"
    )


# --- 3. installing the replacement onto the finished leaf ---------------------------------------


def test_install_increments_the_existing_opening_item_hardware_row(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R7", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)
    leaf = _complete(db_session, opening, sao)
    oih = db_session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == leaf.id)).all()
    assert [(h.product_code, h.quantity) for h in oih] == [(HINGE[1], 3)]

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    result = shop_assembly_repository.install_replacement(db_session, item.id, 1, performed_by="ada")
    db_session.flush()

    assert result.id == leaf.id
    rows = db_session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == leaf.id)).all()
    assert [(h.product_code, h.quantity) for h in rows] == [(HINGE[1], 4)]
    assert item.replacement_pending_quantity == 0
    assert item.installed_quantity == 4
    assert item.installed_quantity + item.deficient_quantity + item.replacement_pending_quantity == item.quantity
    assert shop_assembly_repository.get_replacement_work(db_session) == []


def test_install_creates_the_row_when_the_line_had_nothing_installed(db_session):
    """#339 refuses a completion where *nothing at all* was installed, but a line that was entirely
    deficient while another line was fine contributes no OpeningItemHardware row - so the install
    has to be able to create one."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1], quantity=10)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-R8", items=[(*HINGE, 2), (*LOCK, 1)]
    )
    lock_item = sao[LOCK[1]]
    _flag_deficient(db_session, opening, lock_item, 1)
    leaf = _complete(db_session, opening, sao)

    rows = db_session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == leaf.id)).all()
    assert [(h.product_code, h.quantity) for h in rows] == [(HINGE[1], 2)]

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, lock_item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()
    shop_assembly_repository.install_replacement(db_session, lock_item.id, 1, performed_by="ada")
    db_session.flush()

    rows = db_session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == leaf.id)).all()
    assert sorted((h.product_code, h.quantity) for h in rows) == [(HINGE[1], 2), (LOCK[1], 1)]
    assert lock_item.replacement_pending_quantity == 0


def test_install_is_audited(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R9", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)
    leaf = _complete(db_session, opening, sao)
    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    shop_assembly_repository.install_replacement(db_session, item.id, 1, performed_by="ada")
    db_session.flush()

    events = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.entity_id == leaf.id,
                InventoryAuditLog.action == AuditAction.REPLACEMENT_INSTALL,
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].entity_type == AuditEntityType.OPENING_ITEM
    assert events[0].performed_by == "ada"
    assert events[0].detail["installedQuantity"] == 1
    assert events[0].detail["remainingPendingQuantity"] == 1


def test_install_cannot_spend_more_than_arrived(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R10", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)
    _complete(db_session, opening, sao)
    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    with pytest.raises(ValidationError):
        shop_assembly_repository.install_replacement(db_session, item.id, 2)
    with pytest.raises(ValidationError):
        shop_assembly_repository.install_replacement(db_session, item.id, 0)


def test_install_is_refused_while_the_leaf_is_still_on_the_bench(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R11", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.install_replacement(db_session, item.id, 1)


# --- 4. the replacement arrives after the leaf shipped ------------------------------------------


def test_replacement_after_shipment_notifies_and_stays_queryable(db_session):
    """Do not strand it silently: the pending state is recorded so the unit stays visible to the
    reallocation world, and a notification says where it went wrong."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R12", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)
    leaf = _complete(db_session, opening, sao)
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    assert item.replacement_pending_quantity == 2

    notes = list(
        db_session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.REPLACEMENT_AFTER_SHIPMENT,
            )
        ).all()
    )
    assert len(notes) == 1
    assert "already shipped" in notes[0].message
    assert HINGE[1] in notes[0].message

    work = shop_assembly_repository.get_replacement_work(db_session)
    assert len(work) == 1
    assert work[0].opening_item_state == OpeningItemState.SHIPPED_OUT

    # And it cannot be quietly fitted to a leaf that has left the building.
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.install_replacement(db_session, item.id, 1)


def test_no_shipment_notification_for_a_leaf_still_in_inventory(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R13", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 1)
    _complete(db_session, opening, sao)
    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()

    assert (
        db_session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.REPLACEMENT_AFTER_SHIPMENT,
            )
        ).all()
        == []
    )


# --- 5. the shipping deficiency guard -----------------------------------------------------------


def test_awaiting_replacement_counts_condemned_and_arrived_but_unfitted(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1], quantity=10)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-R14", items=[(*HINGE, 4), (*LOCK, 2)]
    )
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    _flag_deficient(db_session, opening, sao[LOCK[1]], 1)
    leaf = _complete(db_session, opening, sao)

    # Both still condemned.
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {leaf.id: 2}

    # One replacement arrives: it is still owed to the leaf, just in a different bucket.
    repl = _work_the_pull(db_session, _repl_pull_for(db_session, sao[HINGE[1]]))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {leaf.id: 2}

    # Fitted: the leaf is finally whole and drops out of the flag entirely.
    shop_assembly_repository.install_replacement(db_session, sao[HINGE[1]].id, 1)
    db_session.flush()
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {leaf.id: 1}


def test_a_whole_leaf_is_not_flagged(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R15", items=[(*HINGE, 2)])
    leaf = _complete(db_session, opening, sao)
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {}
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, []) == {}


def _shipping_finalize(session, project, leaf, *, acknowledge=False, request_number="SOR-R1"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [
                {
                    "opening_number": leaf.opening_number,
                    "building": None,
                    "floor": None,
                    "location": None,
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
            ],
            "shipping_out_pr_drafts": [
                {
                    "request_number": request_number,
                    "requested_by": "tester",
                    "items": [
                        {
                            "item_type": "OPENING_ITEM",
                            "opening_number": leaf.opening_number,
                            "opening_item_id": str(leaf.id),
                            "leaf": leaf.leaf,
                            "hardware_category": None,
                            "product_code": None,
                            "requested_quantity": 1,
                        }
                    ],
                }
            ],
            "acknowledge_incomplete_leaves": acknowledge,
        },
    )


def test_shipping_out_creation_refuses_a_flagged_leaf_without_the_acknowledgment(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R16", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    with pytest.raises(ValidationError) as exc:
        _shipping_finalize(db_session, project, leaf)
    # The message has to name the leaves, so the decision can be made once rather than one at a time.
    assert leaf.opening_number in str(exc.value)
    assert "awaiting replacement" in str(exc.value)
    assert exc.value.code == "VALIDATION_ERROR"


def test_shipping_out_creation_accepts_a_flagged_leaf_with_the_acknowledgment(db_session):
    """Warn + confirm, never a hard block: deliberate short-shipping stays possible."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R17", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    result = _shipping_finalize(db_session, project, leaf, acknowledge=True, request_number="SOR-R2")
    db_session.flush()
    reqs = result["shipping_out_requests"]
    assert len(reqs) == 1
    assert [i.opening_item_id for i in reqs[0].items] == [leaf.id]


def test_shipping_out_creation_is_untouched_for_a_whole_leaf(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-R18", items=[(*HINGE, 2)])
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    result = _shipping_finalize(db_session, project, leaf, request_number="SOR-R3")
    db_session.flush()
    assert len(result["shipping_out_requests"]) == 1


# --- 6. replacement pull identity: one PENDING pull, then a fresh one (#345-#350 review) ---------


def _repl_pulls_for(session, sao_item) -> list[PullRequest]:
    """Every PR-REPL pull carrying a line for this checklist item, oldest first."""
    ids = list(
        session.scalars(
            select(PullRequestItem.pull_request_id).where(PullRequestItem.sa_opening_item_id == sao_item.id)
        ).all()
    )
    pulls = [session.get(PullRequest, pid) for pid in dict.fromkeys(ids)]
    return sorted(pulls, key=lambda p: p.created_at)


def test_repeated_flags_on_one_line_increment_a_single_replacement_line(db_session):
    """Two flags against the same checklist line and product are one line to pick, not two rows the
    replacement loop has to re-aggregate."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RN1", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]

    _flag_deficient(db_session, opening, item, 1)
    _flag_deficient(db_session, opening, item, 2)

    lines = list(db_session.scalars(select(PullRequestItem).where(PullRequestItem.sa_opening_item_id == item.id)).all())
    assert len(lines) == 1
    assert lines[0].requested_quantity == 3
    assert len(_repl_pulls_for(db_session, item)) == 1


def test_a_second_deficiency_after_the_replacement_completed_mints_a_new_pull(db_session):
    """The crash regression. `PR-REPL-{basis}` is unique among live pulls, so once the first
    replacement pull has completed the next deficiency on the same source pull cannot reuse its
    number - it gets `-2` instead of an IntegrityError."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RN2", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]

    _flag_deficient(db_session, opening, item, 1)
    first = _repl_pull_for(db_session, item)
    assert first.request_number == "PR-REPL-PR-SA-RN2"

    _work_the_pull(db_session, first)
    warehouse_repository.complete_pull_request(db_session, first.id)
    db_session.flush()
    assert first.status == PullRequestStatus.COMPLETED

    # The second flag must not try to write the same number again.
    _flag_deficient(db_session, opening, item, 1)
    db_session.flush()

    pulls = _repl_pulls_for(db_session, item)
    assert [p.request_number for p in pulls] == ["PR-REPL-PR-SA-RN2", "PR-REPL-PR-SA-RN2-2"]
    assert pulls[1].status == PullRequestStatus.PENDING
    # And the new pull carries its own line, at the newly flagged quantity only.
    new_lines = [line for line in pulls[1].items if line.sa_opening_item_id == item.id]
    assert [line.requested_quantity for line in new_lines] == [1]


def test_a_deficiency_during_an_approved_replacement_pull_starts_a_fresh_pull(db_session):
    """An IN_PROGRESS pull has already been deducted and sufficiency-checked line by line. Appending
    to it would deliver a unit nothing paid for - and restock one on cancel that never left."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RN3", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]

    _flag_deficient(db_session, opening, item, 1)
    first = _repl_pull_for(db_session, item)
    pick_pull(db_session, first.id, "warehouse")
    db_session.flush()
    assert first.status == PullRequestStatus.IN_PROGRESS

    _flag_deficient(db_session, opening, item, 1)
    db_session.flush()

    pulls = _repl_pulls_for(db_session, item)
    assert len(pulls) == 2
    assert pulls[1].request_number == "PR-REPL-PR-SA-RN3-2"
    assert [line.requested_quantity for line in first.items] == [1]


def test_a_long_source_number_keeps_the_suffix_and_stays_inside_varchar_50(db_session):
    """`request_number` is varchar(50). When the basis is long enough that the suffix would not fit,
    the *basis* is what gets truncated - the suffix is the part that makes the number unique."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    long_number = "PR-SA-" + "L" * 40  # 46 chars; "PR-REPL-" + this is 54
    opening, sao = _make_pulled_opening(db_session, project.id, request_number=long_number, items=[(*HINGE, 4)])
    item = sao[HINGE[1]]

    _flag_deficient(db_session, opening, item, 1)
    first = _repl_pull_for(db_session, item)
    _work_the_pull(db_session, first)
    warehouse_repository.complete_pull_request(db_session, first.id)
    db_session.flush()

    _flag_deficient(db_session, opening, item, 1)
    db_session.flush()

    numbers = [p.request_number for p in _repl_pulls_for(db_session, item)]
    assert all(len(n) <= 50 for n in numbers)
    assert numbers[0] != numbers[1]
    assert numbers[1].endswith("-2")


def test_cancelling_a_replacement_pull_restocks_exactly_what_it_deducted(db_session):
    """A multi-line PR-REPL pull, approved and then cancelled, returns precisely the units approval
    took - and nothing belonging to the deficiency flagged after it was approved."""
    project = _make_project(db_session)
    hinges = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    locks = _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1], quantity=10)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-RN4", items=[(*HINGE, 4), (*LOCK, 4)]
    )

    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    _flag_deficient(db_session, opening, sao[LOCK[1]], 1)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    assert {line.product_code for line in repl.items} == {HINGE[1], LOCK[1]}

    before_hinges, before_locks = hinges.quantity, locks.quantity
    pick_pull(db_session, repl.id, "warehouse")
    db_session.flush()
    assert hinges.quantity == before_hinges - 2
    assert locks.quantity == before_locks - 1

    # A third flag lands on a *new* pull, so it must not be restocked by this cancellation.
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    db_session.flush()
    after_third_flag = hinges.quantity

    result = warehouse_repository.cancel_pull_request(db_session, repl.id, "warehouse", reason="wrong pull")
    db_session.flush()

    assert {(r.product_code, r.quantity) for r in result.restocked} == {(HINGE[1], 2), (LOCK[1], 1)}
    assert hinges.quantity == after_third_flag + 2
    assert locks.quantity == before_locks


def test_install_is_refused_while_the_leaf_is_staged_for_shipment(db_session):
    """SHIP_READY is the shipped problem one step earlier: the packing slip is built from what the
    leaf carries, so a late write here lands hardware on a slip that was picked without it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RN5", items=[(*HINGE, 4)])
    item = sao[HINGE[1]]
    _flag_deficient(db_session, opening, item, 2)
    leaf = _complete(db_session, opening, sao)

    repl = _work_the_pull(db_session, _repl_pull_for(db_session, item))
    warehouse_repository.complete_pull_request(db_session, repl.id)
    db_session.flush()
    assert item.replacement_pending_quantity == 2

    leaf.state = OpeningItemState.SHIP_READY
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError) as exc:
        shop_assembly_repository.install_replacement(db_session, item.id, 1)
    assert "staged for shipment" in str(exc.value)
    # It stays queryable rather than being silently dropped.
    work = shop_assembly_repository.get_replacement_work(db_session)
    assert [w.opening_item_state for w in work] == [OpeningItemState.SHIP_READY]


def test_awaiting_replacement_reads_only_the_latest_assembly_of_a_leaf(db_session):
    """A leaf shipped short and was re-assembled. The new unit is whole; the old work unit's
    outstanding units belong to the shipped one and must not follow the leaf into the shop again."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=20)
    first_opening, first_items = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-RN6", items=[(*HINGE, 4)]
    )
    _flag_deficient(db_session, first_opening, first_items[HINGE[1]], 1)
    shipped_leaf = _complete(db_session, first_opening, first_items)
    shipped_leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    # The same physical leaf comes back through the shop under a second pull, this time whole.
    second_opening, second_items = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-RN7", items=[(*HINGE, 4)]
    )
    second_opening.opening_id = first_opening.opening_id
    second_opening.opening_number = first_opening.opening_number
    db_session.flush()
    fresh_leaf = _complete(db_session, second_opening, second_items)
    db_session.flush()

    awaiting = shop_assembly_repository.get_awaiting_replacement_quantities(
        db_session, [shipped_leaf.id, fresh_leaf.id]
    )
    assert awaiting.get(fresh_leaf.id, 0) == 0
    assert awaiting.get(shipped_leaf.id, 0) == 1


# --- 8. the replacement holds a claim of its own (#342 follow-up) --------------------------------
#
# A PR-REPL pull used to be the one pull holding nothing. Nobody can reserve for a deficiency that
# has not happened yet - true when the source request was created, and irrelevant from the moment the
# assembler finds the defect. From then on the replacement is a known, dated demand competing with
# requests created *after* it, and it lost every time: it sat PENDING while the stock it was waiting
# on was claimed by somebody else. So the claim is minted where it becomes real - at the flag.


def _replacement_reservations(session, pr_id):
    return list(
        session.scalars(
            select(InventoryReservation).where(
                InventoryReservation.source == ReservationSource.REPLACEMENT_PULL,
                InventoryReservation.pull_request_id == pr_id,
            )
        ).all()
    )


def test_flagging_reserves_free_stock_for_the_replacement(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES1", items=[(*HINGE, 4)])

    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])

    rows = _replacement_reservations(db_session, repl.id)
    assert [(r.hardware_category, r.product_code, r.quantity) for r in rows] == [(*HINGE, 2)]
    # It is the pull that holds it - there is no request behind a deficiency.
    assert rows[0].shop_assembly_request_id is None
    assert rows[0].shipping_out_request_id is None


def test_reserving_less_than_was_condemned_is_normal_not_a_failure(db_session):
    """The usual reason a replacement is needed is that there is no spare on the shelf. The pull
    takes whatever it can get and the top-up hooks close the gap later."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES2", items=[(*HINGE, 4)])

    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    assert _replacement_reservations(db_session, repl.id) == []


def test_repeated_flags_merge_into_one_reservation_row(db_session):
    """One row per combo per holder, the same rule create_reservations follows: every availability
    sum is an aggregate, and a stack of one-unit rows would only make it add them back up."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES3", items=[(*HINGE, 4)])

    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])

    rows = _replacement_reservations(db_session, repl.id)
    assert len(rows) == 1
    assert rows[0].quantity == 2


def test_the_claim_makes_the_stock_unavailable_to_everyone_else(db_session):
    """Which is the whole point: a request created after the defect can no longer take the units the
    replacement is waiting on."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=3)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES4", items=[(*HINGE, 4)])

    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    db_session.flush()

    check = warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [(*HINGE, 3)], reservation_aware=True
    )
    assert not check.sufficient
    assert check.shortfalls[0].reserved == 2


def test_the_replacement_pull_is_its_own_reservation_holder(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES5", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 1)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])

    assert warehouse_repository.find_reservation_holder(db_session, repl) == (
        ReservationSource.REPLACEMENT_PULL,
        repl.id,
    )


def test_picking_a_covered_replacement_spends_its_claim(db_session):
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES6", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    db_session.flush()

    result = pick_pull(db_session, repl.id, "warehouse")

    assert (result.outcome, result.shortfalls) == ("PICKED", [])
    # The claim became the deduction: the two condemned units returned to the row, and two good ones
    # left it, so the row is back where it started with the condemned pair still flagged.
    assert (il.quantity, il.deficient_quantity) == (5, 2)
    assert _replacement_reservations(db_session, repl.id) == []


def test_a_partly_reserved_replacement_picks_short_and_asks_the_po_to_backfill(db_session):
    """Holding a claim is not the same as being covered. The PO loop is unchanged; what changed in
    #367 is that the pull is picked short rather than left blocked at PENDING."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES7", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    db_session.flush()

    result = pick_pull(db_session, repl.id, "warehouse")
    pr = result.pull_request

    assert result.outcome == "SHORT"
    assert pr.status == PullRequestStatus.IN_PROGRESS
    assert pr.picked_at is None
    assert result.notification is not None
    assert result.shortfalls[0].short == 2
    # A partly-covered replacement is the EXPECTED shortfall population, so it must not be recorded
    # as an inventory integrity error - flagging every one of them is how a real one gets missed.
    integrity = [
        row
        for row in db_session.scalars(
            select(InventoryAuditLog).where(InventoryAuditLog.action == AuditAction.PULL_DEDUCTION)
        ).all()
        if (row.detail or {}).get("integrityError")
    ]
    assert integrity == []


def test_a_receive_claims_the_arriving_stock_for_the_waiting_replacement(db_session):
    """Top up FIRST, then announce. Announcing without claiming would leave the units free until
    somebody got round to approving, and a request created in between could take them - the pull
    would be announced as coverable and then come up short, which is the loop this ends."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES8", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    assert _replacement_reservations(db_session, repl.id) == []

    il.quantity += 2  # the backfill lands
    db_session.flush()
    raised = warehouse_repository.notify_unblocked_replacement_pulls(db_session, project.id, {HINGE})
    db_session.flush()

    assert [r.quantity for r in _replacement_reservations(db_session, repl.id)] == [2]
    # And the announcement still fires - the pull own fresh claim is excluded from the coverability
    # check, without which it would read as insufficient forever.
    assert len(raised) == 1
    assert raised[0].type == NotificationType.PULL_UNBLOCKED


def test_a_receive_that_only_narrows_the_gap_claims_it_but_says_nothing(db_session):
    """Claiming is unconditional - every unit that lands is one the replacement should hold - but the
    announcement is reserved for a pull the warehouse can actually act on."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES9", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 3)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])

    il.quantity += 1
    db_session.flush()
    raised = warehouse_repository.notify_unblocked_replacement_pulls(db_session, project.id, {HINGE})
    db_session.flush()

    assert [r.quantity for r in _replacement_reservations(db_session, repl.id)] == [1]
    assert raised == []


def test_repairing_a_condemned_unit_claims_it_for_the_replacement(db_session):
    """The other moment project availability rises. A repaired unit is exactly what the replacement
    was condemned for, so it goes to the replacement rather than to whoever asks next."""
    from app.models.enums import DeficiencyResolution
    from app.repositories import stock as stock_repository

    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES10", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    assert _replacement_reservations(db_session, repl.id) == []

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.REPAIR,
        quantity=2,
        reason_text="straightened",
        rma_reference=None,
        destock_source=None,
        reviewed_by="reviewer",
    )
    db_session.flush()

    assert [r.quantity for r in _replacement_reservations(db_session, repl.id)] == [2]


def test_discarding_a_pending_replacement_pull_releases_its_claim(db_session):
    """The pull IS the holder, so hard-deleting it without releasing would strand a claim with
    nothing left that could ever spend or release it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-RES11", items=[(*HINGE, 4)])
    _flag_deficient(db_session, opening, sao[HINGE[1]], 2)
    repl = _repl_pull_for(db_session, sao[HINGE[1]])
    repl_id = repl.id
    db_session.flush()

    warehouse_repository.discard_pending_pull_request(db_session, repl_id)
    db_session.flush()

    assert _replacement_reservations(db_session, repl_id) == []
    check = warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [(*HINGE, 5)], reservation_aware=True
    )
    assert check.sufficient


def test_two_replacements_are_topped_up_oldest_first(db_session):
    """Deterministic when two of them want the same scarce combo, and it is the queue the warehouse
    already works: the order the defects were found."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=0)
    first_opening, first_sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-RES12", items=[(*HINGE, 4)]
    )
    _flag_deficient(db_session, first_opening, first_sao[HINGE[1]], 2)
    first_repl = _repl_pull_for(db_session, first_sao[HINGE[1]])

    second_opening, second_sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-RES13", items=[(*HINGE, 4)]
    )
    _flag_deficient(db_session, second_opening, second_sao[HINGE[1]], 2)
    second_repl = _repl_pull_for(db_session, second_sao[HINGE[1]])
    db_session.flush()

    il.quantity += 3  # not enough for both
    db_session.flush()
    warehouse_repository.top_up_replacement_reservations(db_session, project.id, [HINGE])
    db_session.flush()

    assert [r.quantity for r in _replacement_reservations(db_session, first_repl.id)] == [2]
    assert [r.quantity for r in _replacement_reservations(db_session, second_repl.id)] == [1]


# --- 9. the shipping guard sees both kinds of short ----------------------------------------------


def test_leaf_shortfalls_reports_both_halves_of_one_leaf(db_session):
    """Condemned-and-unreplaced and never-pulled are counted apart because the remedies differ: a
    replacement is already in flight for one and there is nothing coming for the other."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=20)
    opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-SHORTFALL1",
        # 4 hinges owed, 3 pulled; 2 locks owed, both pulled.
        items=[(*HINGE, 4, 3), (*LOCK, 2, 2)],
    )
    _flag_deficient(db_session, opening, sao[LOCK[1]], 1)
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    shortfalls = shop_assembly_repository.get_leaf_shortfalls(db_session, [leaf.id])
    assert shortfalls[leaf.id].awaiting_replacement == 1
    assert shortfalls[leaf.id].never_pulled == 1
    assert shortfalls[leaf.id].total == 2

    # The two named readings are views of the same row.
    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {leaf.id: 1}
    assert shop_assembly_repository.get_never_pulled_quantities(db_session, [leaf.id]) == {leaf.id: 1}


def test_a_leaf_that_is_only_short_is_still_flagged(db_session):
    """Nothing was condemned, so the awaiting-replacement reading is silent - and the leaf is still
    physically missing hardware its list claims, so shipping it has to be a decision."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=20)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-SHORTFALL2", items=[(*HINGE, 4, 2)]
    )
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    assert shop_assembly_repository.get_awaiting_replacement_quantities(db_session, [leaf.id]) == {}
    shortfalls = shop_assembly_repository.get_leaf_shortfalls(db_session, [leaf.id])
    assert shortfalls[leaf.id].never_pulled == 2


def test_a_whole_leaf_reports_no_shortfall_at_all(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=20)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-SHORTFALL3", items=[(*HINGE, 4)])
    leaf = _complete(db_session, opening, sao)
    db_session.flush()

    assert shop_assembly_repository.get_leaf_shortfalls(db_session, [leaf.id]) == {}
    assert shop_assembly_repository.get_leaf_shortfalls(db_session, []) == {}
