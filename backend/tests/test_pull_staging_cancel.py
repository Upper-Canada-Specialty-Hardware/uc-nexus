"""Per-opening pull staging and pull cancel/restock (#343).

Two halves of the same change. Staging: the warehouse confirms a pull cart by cart, each opening
becomes workable the moment it is staged rather than when the whole pull is picked, the pull's
display status derives as PARTIAL in between, and staging the last opening completes the pull
exactly once. Cancel: an approved pull can be unwound - inventory returned, openings released, the
source request handed back to PENDING with its claim re-created if availability still allows - and
is refused whole when assembly has already started on any of its openings.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import (
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
)
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    NotificationType,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipping_out_request import ShippingOutRequest
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository

# --- helpers -----------------------------------------------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity, deficient=0):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
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
        deficient_quantity=deficient,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _on_hand(session, project_id, *, category="HINGE", code="HG-100") -> int:
    rows = session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project_id,
            InventoryLocation.hardware_category == category,
            InventoryLocation.product_code == code,
        )
    ).all()
    return sum(r.quantity for r in rows)


def _two_leaf_request(session, project, *, qty=2, code="HG-100", opening_number="A01"):
    """A shop-assembly request over two leaves of one opening, through the real creation path."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": opening_number,
                    "leaf": leaf,
                    "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
                }
                for leaf in (1, 2)
            ],
        },
    )


def _approved_pull(session, project, *, qty=2, code="HG-100", opening_number="A01"):
    """Create the request, accept it, approve the pull. Returns (sar, pr, [openings by leaf])."""
    result = _two_leaf_request(session, project, qty=qty, code=code, opening_number=opening_number)
    sar = result["shop_assembly_request"]
    shop_assembly_repository.accept_shop_assembly_request(session, sar.id, "acceptor")
    session.flush()
    pr = session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    warehouse_repository.approve_pull_request(session, pr.id, "picker")
    session.flush()
    openings = list(
        session.scalars(
            select(ShopAssemblyOpening)
            .where(ShopAssemblyOpening.pull_request_id == pr.id)
            .order_by(ShopAssemblyOpening.leaf.asc())
        ).all()
    )
    return sar, pr, openings


def _audit(session, action):
    return list(session.scalars(select(InventoryAuditLog).where(InventoryAuditLog.action == action)).all())


# --- staging -----------------------------------------------------------------------------------


def test_staging_one_opening_leaves_the_other_not_pulled(db_session):
    """Each cart is confirmed on its own: the pull is not an all-or-nothing flip any more."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    assert [o.pull_status for o in openings] == [PullStatus.NOT_PULLED, PullStatus.NOT_PULLED]

    result = warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()

    assert result.newly_staged_ids == [openings[0].id]
    assert result.completed is False
    assert openings[0].pull_status == PullStatus.PULLED
    assert openings[0].staged_at is not None
    assert openings[0].staged_by == "picker"
    assert openings[1].pull_status == PullStatus.NOT_PULLED
    assert openings[1].staged_at is None
    # The pull itself stays IN_PROGRESS - the state machine gains no half-state.
    assert pr.status == PullRequestStatus.IN_PROGRESS


def test_partial_derivation(db_session):
    """PullStatus.PARTIAL is the aggregate reading over the openings, derived and never stored."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)

    before = warehouse_repository.get_pull_staging_summaries(db_session, [pr.id])[pr.id]
    assert (before.status, before.staged_opening_count, before.total_opening_count) == (PullStatus.NOT_PULLED, 0, 2)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    mid = warehouse_repository.get_pull_staging_summaries(db_session, [pr.id])[pr.id]
    assert (mid.status, mid.staged_opening_count, mid.total_opening_count) == (PullStatus.PARTIAL, 1, 2)
    # PARTIAL never lands on an opening: one cart is built or it is not.
    assert {o.pull_status for o in openings} == {PullStatus.PULLED, PullStatus.NOT_PULLED}

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()
    after = warehouse_repository.get_pull_staging_summaries(db_session, [pr.id])[pr.id]
    assert (after.status, after.staged_opening_count) == (PullStatus.PULLED, 2)


def test_staging_summaries_omit_pulls_with_no_openings(db_session):
    """A shipping-out or PR-REPL pull has no openings, so it gets no staging reading at all - which
    is what lets the UI render nothing rather than "0 of 0 staged"."""
    project = _make_project(db_session)
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-REPL-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.IN_PROGRESS,
        requested_by="tester",
    )
    db_session.add(pr)
    db_session.flush()
    assert warehouse_repository.get_pull_staging_summaries(db_session, [pr.id]) == {}


def test_staged_opening_is_immediately_assignable_and_workable(db_session):
    """The whole point: an opening staged first thing is assignable and appears in the work lists
    while the rest of its pull is still being picked."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()

    # Assemble list shows both (the un-staged one renders as "waiting"), keyed on the opening's own
    # pull_status rather than the pull being COMPLETED.
    assemble = shop_assembly_repository.get_assemble_list(db_session, project.id)
    assert {o.id for o in assemble} == {openings[0].id, openings[1].id}

    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user-1", "Assembler One")
    db_session.flush()
    assert [o.id for o in shop_assembly_repository.get_my_work(db_session, "user-1")] == [openings[0].id]

    # The un-staged one is refused at the data layer, not merely hidden.
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.assign_openings(db_session, [openings[1].id], "user-1", "Assembler One")


def test_my_work_excludes_a_claimed_opening_whose_staging_was_undone(db_session):
    """My Work is keyed on the opening's own pull_status, so an opening released back to NOT_PULLED
    drops out of the board even though the pull it hung off is otherwise fine."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user-1", "Assembler One")
    db_session.flush()
    assert len(shop_assembly_repository.get_my_work(db_session, "user-1")) == 1

    openings[0].pull_status = PullStatus.NOT_PULLED
    db_session.flush()
    assert shop_assembly_repository.get_my_work(db_session, "user-1") == []


def test_staging_the_last_opening_completes_the_pull_once(db_session):
    """Completion runs through complete_pull_request, so the notification fires exactly once."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    assert pr.status == PullRequestStatus.IN_PROGRESS

    result = warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()
    assert result.completed is True
    assert pr.status == PullRequestStatus.COMPLETED
    assert pr.completed_at is not None

    completions = db_session.scalars(
        select(Notification).where(
            Notification.project_id == project.id,
            Notification.type == NotificationType.PULL_REQUEST_COMPLETED,
        )
    ).all()
    assert len(completions) == 1


def test_replacement_arrivals_are_not_applied_twice_by_staging(db_session):
    """A pull carrying both openings and a replacement line must apply the arrival once, at the
    single completion staging triggers - not once per staged opening."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    item = openings[0].items[0]
    item.deficient_quantity = 1
    item.installed_quantity = 0
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number=openings[0].opening_number,
            leaf=openings[0].leaf,
            sa_opening_item_id=item.id,
            hardware_category=item.hardware_category,
            product_code=item.product_code,
            requested_quantity=1,
        )
    )
    db_session.flush()
    # The pull's items collection was loaded before this line existed; expire it so the completion
    # path sees what a fresh resolver session would.
    db_session.expire(pr, ["items"])

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    assert item.deficient_quantity == 1  # nothing applied yet - the pull is only part-staged

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()
    assert item.deficient_quantity == 0
    assert len(_audit(db_session, AuditAction.REPLACEMENT_RECEIVED)) == 1


def test_restaging_an_already_staged_opening_is_a_no_op(db_session):
    """A double-click or a stale checklist must not be an error, and must not restamp the opening."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    first_stamp = openings[0].staged_at

    result = warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "someone-else")
    db_session.flush()
    assert result.newly_staged_ids == []
    assert result.completed is False
    assert openings[0].staged_at == first_stamp
    assert openings[0].staged_by == "picker"
    assert len(_audit(db_session, AuditAction.PULL_STAGED)) == 1


def test_staging_writes_an_audit_row_per_opening(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()

    rows = _audit(db_session, AuditAction.PULL_STAGED)
    assert len(rows) == 2
    assert {r.entity_type for r in rows} == {AuditEntityType.SHOP_ASSEMBLY_OPENING}
    assert {r.entity_id for r in rows} == {o.id for o in openings}


def test_staging_refuses_a_pull_that_is_not_approved(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    result = _two_leaf_request(db_session, project)
    sar = result["shop_assembly_request"]
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    opening = db_session.scalars(
        select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == pr.id)
    ).first()

    with pytest.raises(InvalidStateTransitionError):
        warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")


def test_staging_refuses_an_opening_from_another_pull(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    _sar_a, pr_a, _openings_a = _approved_pull(db_session, project, opening_number="A01")
    _sar_b, _pr_b, openings_b = _approved_pull(db_session, project, opening_number="B01")

    with pytest.raises(ValidationError):
        warehouse_repository.stage_pull_openings(db_session, pr_a.id, [openings_b[0].id], "picker")


def test_staging_refuses_an_empty_selection_and_an_unknown_opening(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)

    with pytest.raises(ValidationError):
        warehouse_repository.stage_pull_openings(db_session, pr.id, [], "picker")
    with pytest.raises(NotFoundError):
        warehouse_repository.stage_pull_openings(db_session, pr.id, [uuid.uuid4()], "picker")


def test_completing_the_pull_wholesale_still_stages_whatever_is_left(db_session):
    """The old "Mark as Pulled" path is now "stage everything remaining", and it must not overwrite
    the stamp on a cart that was already confirmed individually."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    first_stamp = openings[0].staged_at

    warehouse_repository.complete_pull_request(db_session, pr.id, completed_by="supervisor")
    db_session.flush()
    assert openings[1].pull_status == PullStatus.PULLED
    assert openings[1].staged_by == "supervisor"
    assert openings[0].staged_at == first_stamp
    assert openings[0].staged_by == "picker"


def test_staging_deducts_no_inventory(db_session):
    """Deduction timing is unchanged (#343): approval commits the pull, staging only tracks it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    after_approve = _on_hand(db_session, project.id)
    assert after_approve == 16  # 20 - (2 leaves x 2 units)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()
    assert _on_hand(db_session, project.id) == after_approve


# --- cancel / restock --------------------------------------------------------------------------


def test_cancel_restocks_releases_and_returns_the_request_to_pending(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, pr, openings = _approved_pull(db_session, project)
    assert _on_hand(db_session, project.id) == 16
    assert sar.status == ShopAssemblyRequestStatus.APPROVED

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", "wrong project")
    db_session.flush()

    assert _on_hand(db_session, project.id) == 20
    assert pr.status == PullRequestStatus.CANCELLED
    assert pr.cancelled_by == "warehouse"
    assert pr.cancellation_reason == "wrong project"
    assert pr.cancelled_at is not None
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sar.approved_by is None
    assert result.source_request_returned_to_pending is True
    assert [(r.hardware_category, r.product_code, r.quantity) for r in result.restocked] == [("HINGE", "HG-100", 4)]
    for opening in openings:
        assert opening.pull_status == PullStatus.NOT_PULLED
        assert opening.pull_request_id is None
        assert opening.assigned_to_user_id is None


def test_cancel_returns_staged_openings_too(db_session):
    """Staged-but-unassembled hardware is on a cart in the shop, which is exactly as retrievable as
    hardware still on the shelf - so it comes back, stamp and all."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()

    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()

    assert _on_hand(db_session, project.id) == 20
    assert openings[0].pull_status == PullStatus.NOT_PULLED
    assert openings[0].staged_at is None
    assert openings[0].staged_by is None


def test_cancel_recreates_the_reservation_for_the_returned_quantities(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, pr, _openings = _approved_pull(db_session, project)
    # Approval consumed the claim.
    assert warehouse_repository.get_reserved_quantities(db_session, project.id) == {}

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()

    assert result.reservations_recreated is True
    assert result.integrity_note is None
    assert sar.integrity_note is None
    assert warehouse_repository.get_reserved_quantities(db_session, project.id) == {("HINGE", "HG-100"): 4}


def test_cancel_flags_rather_than_oversubscribes_when_stock_vanished(db_session):
    """The claim was consumed at approval, so re-creating it competes with everyone else. If another
    request claimed the freed stock and some of it was then written off, the returned units cannot
    all be re-claimed - and the request is left unreserved and flagged, never half-claimed."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=20)
    sar, pr, _openings = _approved_pull(db_session, project, opening_number="A01")
    assert _on_hand(db_session, project.id) == 16
    # A second request claims everything the first one left behind...
    _two_leaf_request(db_session, project, qty=8, opening_number="B01")
    db_session.flush()
    assert warehouse_repository.get_reserved_quantities(db_session, project.id) == {("HINGE", "HG-100"): 16}
    # ...and then an admin writes 14 units off from under it.
    il.quantity -= 14
    db_session.flush()
    assert _on_hand(db_session, project.id) == 2

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()

    assert _on_hand(db_session, project.id) == 6
    assert result.reservations_recreated is False
    assert result.integrity_note is not None
    assert "could not be re-reserved" in result.integrity_note
    assert sar.integrity_note == result.integrity_note
    # Nothing partial was written: the only claim left is the second request's, untouched.
    assert warehouse_repository.get_reserved_quantities(db_session, project.id) == {("HINGE", "HG-100"): 16}
    assert sar.status == ShopAssemblyRequestStatus.PENDING


def test_cancel_is_blocked_by_an_opening_in_progress(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user-1", "Assembler One")
    db_session.flush()
    shop_assembly_repository.record_assembly_progress(
        db_session,
        openings[0].id,
        [shop_assembly_repository.AssemblyProgressUpdate(openings[0].items[0].id, installed_quantity=1)],
        performed_by="Assembler One",
    )
    db_session.flush()
    on_hand_before = _on_hand(db_session, project.id)

    with pytest.raises(ConflictError) as exc:
        warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)

    assert "A01" in str(exc.value)
    assert "in progress" in str(exc.value).lower()
    # All-or-nothing: nothing was restocked, and the pull is untouched.
    assert _on_hand(db_session, project.id) == on_hand_before
    assert pr.status == PullRequestStatus.COMPLETED


def test_cancel_is_blocked_by_a_completed_opening(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()
    openings[1].assembly_status = AssemblyStatus.COMPLETED
    db_session.flush()

    with pytest.raises(ConflictError) as exc:
        warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    assert "completed" in str(exc.value).lower()


def test_a_fully_staged_shop_assembly_pull_is_still_cancellable(db_session):
    """Staging is per opening now, so a COMPLETED shop-assembly pull means no more than "every cart
    is built" - which is not a point of no return."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()
    assert pr.status == PullRequestStatus.COMPLETED

    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()
    assert pr.status == PullRequestStatus.CANCELLED
    assert _on_hand(db_session, project.id) == 20


def test_cancel_refuses_a_pending_or_already_cancelled_pull(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    result = _two_leaf_request(db_session, project)
    sar = result["shop_assembly_request"]
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))

    with pytest.raises(InvalidStateTransitionError) as exc:
        warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    assert "not been approved" in str(exc.value)

    warehouse_repository.approve_pull_request(db_session, pr.id, "picker")
    db_session.flush()
    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()
    with pytest.raises(InvalidStateTransitionError):
        warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)


def test_cancel_audits_the_pull_and_every_restocked_row(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)

    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", "duplicate")
    db_session.flush()

    cancels = _audit(db_session, AuditAction.PULL_CANCELLED)
    assert len(cancels) == 1
    assert cancels[0].entity_type == AuditEntityType.PULL_REQUEST
    assert cancels[0].entity_id == pr.id
    assert cancels[0].detail["reasonText"] == "duplicate"
    assert cancels[0].detail["restocked"] == [{"hardwareCategory": "HINGE", "productCode": "HG-100", "quantity": 4}]

    restocks = _audit(db_session, AuditAction.PULL_RESTOCK)
    assert len(restocks) == 1
    assert restocks[0].entity_type == AuditEntityType.INVENTORY_LOCATION

    notifications = db_session.scalars(
        select(Notification).where(
            Notification.project_id == project.id,
            Notification.type == NotificationType.PULL_REQUEST_CANCELLED,
        )
    ).all()
    assert len(notifications) == 1


def test_cancel_rejects_a_missing_actor_and_an_over_long_reason(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)

    with pytest.raises(ValidationError):
        warehouse_repository.cancel_pull_request(db_session, pr.id, "", None)
    with pytest.raises(ValidationError):
        warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", "x" * 501)


def test_a_cancelled_request_can_be_re_accepted_and_re_pulled(db_session):
    """The whole point of returning the request to PENDING: re-accepting mints a fresh pull carrying
    the same request number, which is why uniqueness on that number had to become partial."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, first_pr, _openings = _approved_pull(db_session, project)
    warehouse_repository.cancel_pull_request(db_session, first_pr.id, "warehouse", None)
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    live = db_session.scalars(
        select(PullRequest).where(
            PullRequest.request_number == sar.request_number,
            PullRequest.status != PullRequestStatus.CANCELLED,
        )
    ).all()
    assert len(live) == 1
    assert live[0].id != first_pr.id

    warehouse_repository.approve_pull_request(db_session, live[0].id, "picker")
    db_session.flush()
    assert live[0].status == PullRequestStatus.IN_PROGRESS
    assert _on_hand(db_session, project.id) == 16
    # The cancelled pull's openings were re-pointed at the new one by the accept.
    reattached = db_session.scalars(
        select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_request_id == live[0].id)
    ).all()
    assert len(reattached) == 2


def test_reopen_still_finds_the_live_pull_after_a_cancel(db_session):
    """The reopen lookup is by request_number, which a cancelled pull now shares with a live one."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, first_pr, _openings = _approved_pull(db_session, project)
    warehouse_repository.cancel_pull_request(db_session, first_pr.id, "warehouse", None)
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)
    db_session.flush()

    assert sar.status == ShopAssemblyRequestStatus.PENDING
    remaining = db_session.scalars(select(PullRequest).where(PullRequest.request_number == sar.request_number)).all()
    assert [p.id for p in remaining] == [first_pr.id]  # only the cancelled record survives


def test_cancelling_a_replacement_pull_restocks_without_reservations(db_session):
    """A PR-REPL pull never held a claim (nobody can reserve for a deficiency that has not happened
    yet), so cancelling it restocks and re-creates nothing. The leaf's deficient expectation stands -
    the replacement simply has to be requested again."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings], "picker")
    db_session.flush()
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user-1", "Assembler One")
    db_session.flush()
    item = openings[0].items[0]
    shop_assembly_repository.record_assembly_progress(
        db_session,
        openings[0].id,
        [
            shop_assembly_repository.AssemblyProgressUpdate(
                item.id, installed_quantity=1, flag_deficient_quantity=1, deficient_reason="bent"
            )
        ],
        performed_by="Assembler One",
    )
    db_session.flush()

    repl = db_session.scalar(
        select(PullRequest).where(PullRequest.request_number.like("PR-REPL-%"), PullRequest.project_id == project.id)
    )
    assert repl is not None
    warehouse_repository.approve_pull_request(db_session, repl.id, "picker")
    db_session.flush()
    on_hand_after_repl_pull = _on_hand(db_session, project.id)

    result = warehouse_repository.cancel_pull_request(db_session, repl.id, "warehouse", "supplier cannot supply")
    db_session.flush()

    assert repl.status == PullRequestStatus.CANCELLED
    assert _on_hand(db_session, project.id) == on_hand_after_repl_pull + 1
    assert result.source_request_returned_to_pending is False
    assert result.reservations_recreated is False
    assert warehouse_repository.get_reserved_quantities(db_session, project.id) == {}
    # The expectation stays on the leaf.
    assert item.deficient_quantity == 1


def test_cancelling_a_shipping_out_pull_returns_its_request_and_reserves_loose_lines_only(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "item_type": "LOOSE",
                            "opening_number": "A01",
                            "opening_item_id": None,
                            "hardware_category": "HINGE",
                            "product_code": "HG-100",
                            "requested_quantity": 3,
                        }
                    ],
                }
            ],
        },
    )
    db_session.flush()
    sor = db_session.scalars(select(ShippingOutRequest).where(ShippingOutRequest.project_id == project.id)).first()
    from app.repositories import shipping_repository

    shipping_repository.accept_shipping_out_request(db_session, sor.id, "acceptor")
    db_session.flush()
    warehouse_repository.approve_pull_request(db_session, sor.pull_request_id, "picker")
    db_session.flush()
    pr_id = sor.pull_request_id
    assert _on_hand(db_session, project.id) == 17

    result = warehouse_repository.cancel_pull_request(db_session, pr_id, "warehouse", None)
    db_session.flush()

    assert _on_hand(db_session, project.id) == 20
    assert sor.status == ShippingOutRequestStatus.PENDING
    assert sor.pull_request_id is None
    assert result.reservations_recreated is True
    reserved = db_session.scalars(
        select(InventoryReservation).where(InventoryReservation.project_id == project.id)
    ).all()
    assert [(r.source, r.quantity) for r in reserved] == [(ReservationSource.SHIPPING_OUT_REQUEST, 3)]


def test_restock_lands_on_the_projects_newest_row_and_re_materializes_a_deleted_one(db_session):
    """Which row a hinge sits on carries no identity, so the return is not a row-by-row reversal of
    the FIFO deduction - and it must still land somewhere if a re-upload deleted every row."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)
    db_session.delete(il)
    db_session.flush()
    assert _on_hand(db_session, project.id) == 0

    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()
    assert _on_hand(db_session, project.id) == 4


def test_complete_opening_works_while_the_pull_is_only_part_staged(db_session):
    """The COMPLETED-filter rework, end to end: a leaf can be built and finished while its pull is
    still IN_PROGRESS, and an un-staged sibling still cannot."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, openings = _approved_pull(db_session, project, qty=1)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user-1", "Assembler One")
    db_session.flush()
    shop_assembly_repository.record_assembly_progress(
        db_session,
        openings[0].id,
        [shop_assembly_repository.AssemblyProgressUpdate(openings[0].items[0].id, installed_quantity=1)],
        performed_by="Assembler One",
    )
    db_session.flush()

    opening_item = shop_assembly_repository.complete_opening(db_session, openings[0].id, "A", "1", "1")
    db_session.flush()
    assert opening_item.opening_number == "A01"
    assert openings[0].assembly_status == AssemblyStatus.COMPLETED
    assert pr.status == PullRequestStatus.IN_PROGRESS

    openings[1].assigned_to = "Assembler One"
    openings[1].assigned_to_user_id = "user-1"
    db_session.flush()
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.complete_opening(db_session, openings[1].id, "A", "1", "1")


def test_get_pull_request_openings_orders_by_opening_and_leaf(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)

    rows = warehouse_repository.get_pull_request_openings(db_session, pr.id)
    assert [(r.opening_number, r.leaf) for r in rows] == [("A01", 1), ("A01", 2)]
    assert all(r.items for r in rows)
    assert warehouse_repository.get_pull_request_openings(db_session, uuid.uuid4()) == []


def test_assemble_list_excludes_a_cancelled_pulls_openings(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr, _openings = _approved_pull(db_session, project)
    assert len(shop_assembly_repository.get_assemble_list(db_session, project.id)) == 2

    warehouse_repository.cancel_pull_request(db_session, pr.id, "warehouse", None)
    db_session.flush()
    assert shop_assembly_repository.get_assemble_list(db_session, project.id) == []
