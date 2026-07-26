"""Persisted per-item assembly progress (#340).

Assembly used to be atomic and ephemeral: the checklist lived in the browser until Mark Complete
posted it, so a leaf half-built at the end of a shift lost everything and a defect found at 9am was
invisible to the warehouse until the leaf was finished. record_assembly_progress makes the counts
durable, and completion reads them instead of taking a claim as input.

Covered here: save/resume, partial quantities per line, immediate PR-REPL mint, the disposition gate
at completion, OpeningItemHardware quantities matching what was installed rather than what was
planned, and the assignment rules that let a manager - and only a manager - hand a half-built leaf to
somebody else.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ConflictError, InvalidStateTransitionError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItemHardware
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import shop_assembly_repository, warehouse_admin_repository

HINGE = ("HINGE", "HG-P1")
LOCK = ("LOCK", "LK-P1")

Update = shop_assembly_repository.AssemblyProgressUpdate


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


def _make_pulled_opening(
    session,
    project_id,
    *,
    request_number,
    items,
    leaf=1,
    assigned_user="user_1",
    pull_status=PullStatus.PULLED,
):
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
        opening_number="A01",
        leaf=leaf,
        pull_status=pull_status,
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


# --- 1. save and resume ------------------------------------------------------------------------


def test_first_save_flips_to_in_progress_and_persists(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P1", items=[(*HINGE, 4)])
    assert opening.assembly_status == AssemblyStatus.PENDING

    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)], performed_by="ada"
    )
    db_session.flush()

    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS
    assert sao[HINGE[1]].installed_quantity == 2
    assert sao[HINGE[1]].deficient_quantity == 0


def test_progress_resumes_and_is_editable_in_both_directions(db_session):
    """installed_quantity is absolute: a second save continues the count, and a miscount can be
    walked back down while the leaf is still open."""
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P2", items=[(*HINGE, 4)])
    item_id = sao[HINGE[1]].id

    shop_assembly_repository.record_assembly_progress(db_session, opening.id, [Update(item_id, installed_quantity=2)])
    shop_assembly_repository.record_assembly_progress(db_session, opening.id, [Update(item_id, installed_quantity=3)])
    db_session.flush()
    assert sao[HINGE[1]].installed_quantity == 3

    # Correction downward.
    shop_assembly_repository.record_assembly_progress(db_session, opening.id, [Update(item_id, installed_quantity=1)])
    db_session.flush()
    assert sao[HINGE[1]].installed_quantity == 1


def test_resending_the_same_count_is_idempotent(db_session):
    """A retried save must not double-count - which is the whole reason installed is absolute."""
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P3", items=[(*HINGE, 4)])
    item_id = sao[HINGE[1]].id

    for _ in range(3):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(item_id, installed_quantity=2)]
        )
    db_session.flush()
    assert sao[HINGE[1]].installed_quantity == 2

    # Only the first save was a change, so only it wrote an audit row.
    events = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.entity_id == opening.id,
                InventoryAuditLog.action == AuditAction.INSTALL_PROGRESS,
            )
        ).all()
    )
    assert len(events) == 1
    assert events[0].entity_type == AuditEntityType.SHOP_ASSEMBLY_OPENING
    assert events[0].detail["installedQuantity"] == 2
    assert events[0].detail["remainingQuantity"] == 2


# --- 2. partial quantities per line ------------------------------------------------------------


def test_partial_quantities_are_tracked_per_line(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P4", items=[(*HINGE, 8), (*LOCK, 2)]
    )

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            Update(sao[HINGE[1]].id, installed_quantity=5),
            Update(sao[LOCK[1]].id, installed_quantity=1),
        ],
    )
    db_session.flush()

    assert sao[HINGE[1]].installed_quantity == 5
    assert sao[LOCK[1]].installed_quantity == 1


def test_installed_plus_deficient_cannot_exceed_the_pulled_quantity(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1])
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P5", items=[(*HINGE, 4)])
    item_id = sao[HINGE[1]].id

    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(item_id, installed_quantity=5)]
        )

    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(item_id, flag_deficient_quantity=2, deficient_reason="bent")]
    )
    db_session.flush()
    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(item_id, installed_quantity=3)]
        )


def test_negative_installed_quantity_is_refused(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P6", items=[(*HINGE, 4)])
    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=-1)]
        )


def test_one_line_twice_in_a_single_save_is_refused(db_session):
    """Two absolute values for one line in one call would be order-dependent - refuse it."""
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P7", items=[(*HINGE, 4)])
    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session,
            opening.id,
            [
                Update(sao[HINGE[1]].id, installed_quantity=1),
                Update(sao[HINGE[1]].id, installed_quantity=2),
            ],
        )


# --- 3. deficiency is minted immediately -------------------------------------------------------


def test_mid_assembly_deficiency_mints_the_replacement_pull_at_once(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1])
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P8", items=[(*HINGE, 2), (*LOCK, 3)], leaf=2
    )

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [Update(sao[LOCK[1]].id, flag_deficient_quantity=2, deficient_reason="seized")],
        performed_by="ada",
    )
    db_session.flush()

    # Recorded on the line...
    assert sao[LOCK[1]].deficient_quantity == 2
    assert sao[LOCK[1]].installed_quantity == 0

    # ...returned to inventory flagged deficient (available unchanged)...
    il = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id, InventoryLocation.product_code == LOCK[1]
        )
    ).first()
    assert il.quantity == 2
    assert il.deficient_quantity == 2

    # ...and the replacement pull exists now, with the leaf and source line stamped on it, while the
    # rest of the leaf is still unbuilt.
    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-P8")).first()
    assert repl is not None
    lines = list(db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == repl.id)).all())
    assert len(lines) == 1
    assert lines[0].requested_quantity == 2
    assert lines[0].leaf == 2
    assert lines[0].sa_opening_item_id == sao[LOCK[1]].id
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS
    assert sao[HINGE[1]].installed_quantity == 0


def test_flagging_more_than_remains_is_refused_and_nothing_is_written(db_session):
    """Validation runs over every line before any of them is applied, so a bad line cannot leave an
    earlier line's deficiency already returned to inventory."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1])
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1])
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P9", items=[(*HINGE, 2), (*LOCK, 1)]
    )

    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session,
            opening.id,
            [
                Update(sao[HINGE[1]].id, flag_deficient_quantity=1, deficient_reason="bent"),
                Update(sao[LOCK[1]].id, flag_deficient_quantity=5, deficient_reason="seized"),
            ],
        )

    assert sao[HINGE[1]].deficient_quantity == 0
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-P9")).first() is None
    )


# --- 4. state guards on the save ---------------------------------------------------------------


def test_progress_refused_when_hardware_is_not_pulled(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-P10",
        items=[(*HINGE, 2)],
        # NOT_PULLED, not PARTIAL: since #345 the column carries a CHECK saying an opening's
        # pull_status is binary. PARTIAL is the derived reading over a *set* of openings and is not
        # storable on one of them, so "this cart is not built" is spelled NOT_PULLED.
        pull_status=PullStatus.NOT_PULLED,
    )
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=1)]
        )


def test_progress_refused_when_unassigned(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P11", items=[(*HINGE, 2)], assigned_user=None
    )
    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=1)]
        )


def test_progress_refused_once_completed(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P12", items=[(*HINGE, 2)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)]
    )
    shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.record_assembly_progress(
            db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=1)]
        )


# --- 5. completion reads the persisted state ---------------------------------------------------


def test_completion_blocked_while_units_are_unaccounted_for(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P13", items=[(*HINGE, 4), (*LOCK, 1)]
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [Update(sao[HINGE[1]].id, installed_quantity=3), Update(sao[LOCK[1]].id, installed_quantity=1)],
    )
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    # The message names the line that is short so the assembler knows where to go back to.
    assert HINGE[1] in str(excinfo.value)
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS


def test_untouched_opening_cannot_be_completed(db_session):
    """The pre-#340 shortcut - complete with no checklist and snapshot everything as installed - is
    gone. Nothing recorded means nothing to complete."""
    project = _make_project(db_session)
    opening, _ = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P14", items=[(*HINGE, 2)])
    with pytest.raises(ValidationError):
        shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)


def test_opening_item_hardware_quantities_are_the_installed_counts(db_session):
    """The snapshot records what went on the leaf, not what was pulled for it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1])
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1])
    opening, sao = _make_pulled_opening(
        db_session, project.id, request_number="PR-SA-P15", items=[(*HINGE, 4), (*LOCK, 2)]
    )

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            # 3 of 4 hinges fitted, the fourth condemned.
            Update(sao[HINGE[1]].id, installed_quantity=3, flag_deficient_quantity=1, deficient_reason="bent"),
            # Both locks condemned - the line contributes no hardware row at all.
            Update(sao[LOCK[1]].id, flag_deficient_quantity=2, deficient_reason="seized"),
        ],
        performed_by="ada",
    )
    db_session.flush()

    result = shop_assembly_repository.complete_opening(db_session, opening.id, "A", "1", "1", completed_by="ada")
    db_session.flush()

    hw = list(
        db_session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == result.id)).all()
    )
    assert {h.product_code: h.quantity for h in hw} == {HINGE[1]: 3}
    assert opening.assembly_status == AssemblyStatus.COMPLETED

    # Completion is audited against the minted leaf, naming who finished it.
    completion_events = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.entity_id == result.id,
                InventoryAuditLog.action == AuditAction.ASSEMBLY_COMPLETE,
            )
        ).all()
    )
    assert len(completion_events) == 1
    assert completion_events[0].performed_by == "ada"


# --- 6. assignment and handoff -----------------------------------------------------------------


def test_my_work_includes_in_progress_openings(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P16", items=[(*HINGE, 4)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=1)]
    )
    db_session.flush()

    mine = shop_assembly_repository.get_my_work(db_session, "user_1")
    assert [o.id for o in mine] == [opening.id]


def test_manager_can_reassign_an_in_progress_opening_keeping_the_progress(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P17", items=[(*HINGE, 4)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)]
    )
    db_session.flush()

    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob", allow_reassign=True)
    db_session.flush()

    assert opening.assigned_to_user_id == "user_2"
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS
    # The handoff is lossless - that is what makes it safe.
    assert sao[HINGE[1]].installed_quantity == 2
    assert [o.id for o in shop_assembly_repository.get_my_work(db_session, "user_2")] == [opening.id]
    assert shop_assembly_repository.get_my_work(db_session, "user_1") == []


def test_self_claim_cannot_steal_someone_elses_opening(db_session):
    """allow_reassign defaults to False, which is what the self-claim resolver branch passes."""
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P18", items=[(*HINGE, 4)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)]
    )
    db_session.flush()

    with pytest.raises(ConflictError):
        shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob")
    assert opening.assigned_to_user_id == "user_1"


def test_reclaiming_your_own_opening_is_a_no_op(db_session):
    """A double-click on Assign to me must not error out."""
    project = _make_project(db_session)
    opening, _ = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P19", items=[(*HINGE, 4)])
    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_1", "Ada")
    db_session.flush()
    assert opening.assigned_to_user_id == "user_1"
    assert opening.assigned_to == "Ada"


def test_unassigning_in_progress_work_is_allowed_and_keeps_it_assignable(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P20", items=[(*HINGE, 4)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)]
    )
    db_session.flush()

    shop_assembly_repository.remove_opening_from_user(db_session, opening.id)
    db_session.flush()
    assert opening.assigned_to_user_id is None
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS

    # Back in the pool, and a plain self-claim can pick it up with its progress intact.
    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob")
    db_session.flush()
    assert opening.assigned_to_user_id == "user_2"
    assert sao[HINGE[1]].installed_quantity == 2


def test_completed_openings_cannot_be_unassigned_or_reassigned(db_session):
    project = _make_project(db_session)
    opening, sao = _make_pulled_opening(db_session, project.id, request_number="PR-SA-P21", items=[(*HINGE, 2)])
    shop_assembly_repository.record_assembly_progress(
        db_session, opening.id, [Update(sao[HINGE[1]].id, installed_quantity=2)]
    )
    shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.remove_opening_from_user(db_session, opening.id)
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.assign_openings(db_session, [opening.id], "user_2", "Bob", allow_reassign=True)
