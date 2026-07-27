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
)
from app.models.inventory import InventoryLocation
from app.models.notification import Notification
from app.models.opening_item import OpeningItemHardware
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository

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
    for category, code, qty in items:
        sao_item = ShopAssemblyOpeningItem(
            id=uuid.uuid4(),
            shop_assembly_opening_id=opening.id,
            hardware_category=category,
            product_code=code,
            quantity=qty,
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
            installed_quantity=item.quantity - item.deficient_quantity,
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
