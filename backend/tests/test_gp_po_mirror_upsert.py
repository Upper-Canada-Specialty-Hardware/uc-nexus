"""Upsert rules for the GP PO mirror (gp-owned-po mirror). DB-backed (db_session): convergence onto a
Nexus row without touching the overlay, GP-authoritative received qty, project matching, gp_line_ord
line matching, and the status-past-registration rule that preserves VENDOR_CONFIRMED.

Plus the two-pass rule for a PO deleted outright in GP (note_missing_from_gp): the first pass that
finds it in neither GP table only stamps it, the second cancels it like a void, and a PO that comes
back from GP in between is never cancelled at all."""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.models.enums import POOrigin, POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import gp_po_sync_repository as sync_repo

COMPANY = "TUBC"


def _line(ord_, item, qty, received=0, cancelled=0, unit_cost=10, job="J1", cost_code=None):
    return {
        "ord": ord_,
        "item": item,
        "itemdesc": f"{item} description",
        "qty": qty,
        "qty_cancelled": cancelled,
        "received": received,
        "unit_cost": unit_cost,
        "job": job,
        "line_status": 2,
        "cost_code": cost_code,
    }


def _po(
    po_number,
    lines,
    *,
    source="work",
    vendor_id="V1",
    vendor_name="Acme",
    doc_date="2026-01-05",
    freight=None,
):
    po = {
        "po_number": po_number,
        "gp_status": 2,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "doc_date": doc_date,
        "modified_at": "2026-01-06T09:00:00",
        "source_table": source,
        "lines": lines,
    }
    if freight is not None:
        po["freight"] = freight
    return po


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id="J1", description="Job One", company="TUBC")
    db_session.add(p)
    db_session.flush()
    return p


def _project_map(db_session):
    from sqlalchemy import select

    return {job: pid for job, pid in db_session.execute(select(Project.project_id, Project.id)).all()}


def _get(db_session, po_number):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    return (
        db_session.scalars(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.line_items))
            .where(PurchaseOrder.gp_company == COMPANY, PurchaseOrder.po_number == po_number)
        )
        .unique()
        .first()
    )


def test_creates_gp_origin_po_matched_to_project(db_session, project):
    action = sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO100", [_line(16384, "IT1", 5, received=2)]), _project_map(db_session)
    )
    db_session.flush()
    assert action == "created"
    row = _get(db_session, "PO100")
    assert row.origin == POOrigin.GP
    assert row.request_number is None
    assert row.project_id == project.id
    assert row.status == POStatus.PARTIALLY_RECEIVED
    assert row.vendor_name_snapshot == "Acme"
    assert len(row.line_items) == 1
    line = row.line_items[0]
    assert line.gp_line_ord == 16384
    assert line.ordered_quantity == 5
    assert line.received_quantity == 2


def test_jobless_po_has_no_project(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO101", [_line(16384, "IT1", 3, job=None)]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO101").project_id is None


def test_disagreeing_jobs_go_to_stock(db_session, project):
    lines = [_line(16384, "IT1", 3, job="J1"), _line(32768, "IT2", 2, job="J2")]
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO102", lines), _project_map(db_session))
    db_session.flush()
    assert _get(db_session, "PO102").project_id is None


def test_received_qty_is_authoritative_on_reupsert(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO103", [_line(16384, "IT1", 5, received=1)]), pm)
    db_session.flush()
    first = _get(db_session, "PO103")
    first_line_id = first.line_items[0].id
    # A receipt posts inside GP; the next pass reports 4 received.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO103", [_line(16384, "IT1", 5, received=4)]), pm)
    db_session.flush()
    row = _get(db_session, "PO103")
    assert len(row.line_items) == 1
    assert row.line_items[0].id == first_line_id  # matched by gp_line_ord, not duplicated
    assert row.line_items[0].received_quantity == 4
    assert row.status == POStatus.PARTIALLY_RECEIVED


def test_converges_into_nexus_row_without_touching_overlay(db_session, project):
    # A Nexus-registered PO already exists for this (company, po_number), with overlay fields set.
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO200",
        request_number="PO-REQ-042",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        project_id=project.id,
        status=POStatus.VENDOR_CONFIRMED,
        cost_code="210-200-2",
        notes="hand-typed note",
        vendor_quote_number="Q-999",
        company="TUBC",
    )
    db_session.add(nexus)
    db_session.flush()
    nexus_line = POLineItem(
        id=uuid.uuid4(),
        po_id=nexus.id,
        gp_line_ord=16384,
        hardware_category="HINGE",  # nexus schedule category
        product_code="HG-100",
        ordered_quantity=5,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
        nexus_registered=True,
    )
    db_session.add(nexus_line)
    db_session.flush()

    # The mirror pass sees the same PO in GP with one receipt, still below full receipt.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO200", [_line(16384, "GP-ITEM", 5, received=2)]), _project_map(db_session)
    )
    db_session.flush()

    row = _get(db_session, "PO200")
    assert row.origin == POOrigin.NEXUS  # origin never flips
    # NEXUS-ONLY FIELDS untouched.
    assert row.request_number == "PO-REQ-042"
    assert row.notes == "hand-typed note"
    assert row.vendor_quote_number == "Q-999"
    # cost_code is GP-owned now, but GP reported none on this pass, so the stored value stands.
    assert row.cost_code == "210-200-2"
    # GP-owned facts converge: received is authoritative, status moves to partial.
    assert row.status == POStatus.PARTIALLY_RECEIVED
    assert row.line_items[0].received_quantity == 2
    # A Nexus line keeps its schedule categorization (not overwritten with the GP item).
    assert row.line_items[0].hardware_category == "HINGE"
    assert row.line_items[0].product_code == "HG-100"


def test_status_below_registration_preserves_vendor_confirmed(db_session, project):
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO201",
        request_number="PO-REQ-050",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        project_id=project.id,
        status=POStatus.VENDOR_CONFIRMED,
        company="TUBC",
    )
    db_session.add(nexus)
    db_session.flush()
    # GP reports the PO with nothing received yet -> derived stage is GP_REGISTERED (baseline).
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO201", [_line(16384, "GP-ITEM", 5, received=0)]), _project_map(db_session)
    )
    db_session.flush()
    # The sync must not stomp the Nexus overlay status back down to GP_REGISTERED.
    assert _get(db_session, "PO201").status == POStatus.VENDOR_CONFIRMED


def test_gp_origin_project_is_write_once_never_repointed(db_session, project):
    # A second project the PO's job could later match.
    other = Project(id=uuid.uuid4(), project_id="J9", description="Job Nine", company="TUBC")
    db_session.add(other)
    db_session.flush()

    # First pass fills the project from the job match.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO300", [_line(16384, "IT1", 2, job="J1")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO300").project_id == project.id
    # A later JOBNUMBR edit in GP must NOT repoint an already-attached project - that would strand any
    # inventory received under the first project and silently revert a manual project edit.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO300", [_line(16384, "IT1", 2, job="J9")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO300").project_id == project.id  # unchanged, write-once


def test_write_once_fills_a_null_project_when_the_job_appears_later(db_session, project):
    # Job unknown on the first pass (no matching project yet) -> jobless.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO301", [_line(16384, "IT1", 2, job="J-LATE")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO301").project_id is None
    # The project gets adopted later; the next pass fills the still-NULL project.
    late = Project(id=uuid.uuid4(), project_id="J-LATE", description="Adopted later", company="TUBC")
    db_session.add(late)
    db_session.flush()
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO301", [_line(16384, "IT1", 2, job="J-LATE")]), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO301").project_id == late.id


def test_existing_line_cancelled_to_zero_is_zeroed_not_left_stale(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO310", [_line(16384, "IT1", 5, received=2)]), pm)
    db_session.flush()
    # GP later cancels the whole line (net 0) after 2 had been received.
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO310", [_line(16384, "IT1", 5, received=2, cancelled=5)]), pm
    )
    db_session.flush()
    line = _get(db_session, "PO310").line_items[0]
    # Outstanding is zeroed (ordered pinned to received) so no phantom pending survives; ck>=1 holds.
    assert line.received_quantity == 2
    assert line.ordered_quantity == 2
    assert line.ordered_quantity - line.received_quantity == 0


def test_received_never_reduced_below_stored(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO311", [_line(16384, "IT1", 5, received=4)]), pm)
    db_session.flush()
    # An unposted GP batch reports a LOWER received; the mirror must never walk received backwards.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO311", [_line(16384, "IT1", 5, received=1)]), pm)
    db_session.flush()
    assert _get(db_session, "PO311").line_items[0].received_quantity == 4


def test_fractional_ordered_rounds_half_up_and_sub_one_is_skipped(db_session, project):
    pm = _project_map(db_session)
    # 2.5 rounds to 3 (half up), not 2 (banker's).
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO312", [_line(16384, "IT1", 2.5)]), pm)
    db_session.flush()
    assert _get(db_session, "PO312").line_items[0].ordered_quantity == 3
    # A net that rounds below 1 creates no line (nothing orderable, ck>=1 could not hold).
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO313", [_line(16384, "IT1", 0.4)]), pm)
    db_session.flush()
    assert _get(db_session, "PO313").line_items == []


def test_cancelled_po_is_soft_deleted_and_releases_hardware(db_session, project):
    from app.models.enums import HardwareItemState
    from app.models.hardware import HardwareItem
    from app.models.project import Opening

    pm = _project_map(db_session)
    # A mirrored open PO with a line, and a schedule item linked IN_PO against that line.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO320", [_line(16384, "IT1", 3, job="J1")]), pm)
    db_session.flush()
    row = _get(db_session, "PO320")
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="101")
    db_session.add(opening)
    db_session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category="IT1 description",
        product_code="IT1",
        item_quantity=3,
        state=HardwareItemState.IN_PO,
        po_line_item_id=row.line_items[0].id,
    )
    db_session.add(hi)
    db_session.flush()

    # GP posts the PO as fully cancelled (history, nothing received).
    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO320", [_line(16384, "IT1", 3, cancelled=3, job="J1")], source="history"),
        pm,
    )
    db_session.flush()
    row = _get(db_session, "PO320")
    assert row.status == POStatus.CANCELLED
    assert row.deleted_at is not None
    db_session.refresh(hi)
    assert hi.state == HardwareItemState.AVAILABLE
    assert hi.po_line_item_id is None


def test_legacy_null_company_row_converges_instead_of_duplicating(db_session, project):
    # A legacy Nexus PO stamped with a number before gp_company was recorded (NULL company).
    legacy = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO400",
        request_number="PO-REQ-400",
        origin=POOrigin.NEXUS,
        gp_company=None,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        company="TUBC",
    )
    db_session.add(legacy)
    db_session.flush()
    # The mirror sees the same number in GP; it must land on the legacy row, not insert a duplicate.
    action = sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO400", [_line(16384, "IT1", 4, received=1)]), _project_map(db_session)
    )
    db_session.flush()
    assert action == "updated"
    row = _get(db_session, "PO400")
    assert row.id == legacy.id
    assert row.origin == POOrigin.NEXUS  # origin never flips
    assert row.gp_company == COMPANY  # legacy NULL company filled in


def test_po_number_pending_registration_is_skipped(db_session, project):
    from app.models.gp_write import GpWriteIdempotency

    # A register_po_in_gp got GP's number but has not persisted it onto the draft yet.
    db_session.add(
        GpWriteIdempotency(
            key="idem-1",
            op="register_po_in_gp",
            relay_result={"po_number": "PO500", "company": COMPANY},
            result_id=None,
        )
    )
    db_session.flush()
    pending = sync_repo.po_numbers_pending_registration(db_session, COMPANY)
    assert "PO500" in pending
    action = sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO500", [_line(16384, "IT1", 3)]),
        _project_map(db_session),
        pending_registration=pending,
    )
    db_session.flush()
    assert action == "skipped"
    assert _get(db_session, "PO500") is None


# --- deleted outright in GP: the two-pass rule ---------------------------------------------------------

PASS1 = datetime(2026, 9, 4, 8, 0, 0)
PASS2 = datetime(2026, 9, 4, 12, 0, 0)


def _open_mirrored(db_session, po_number, **kwargs):
    """A mirrored PO sitting in an open stage - what the closure sweep hands to note_missing_from_gp."""
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po(po_number, [_line(16384, "IT1", 3)], **kwargs), _project_map(db_session)
    )
    db_session.flush()
    return _get(db_session, po_number)


def test_a_first_miss_only_stamps_the_po(db_session, project):
    """One pass cannot tell a deleted PO from one being edited in GP while the sweep read it."""
    row = _open_mirrored(db_session, "PO600")

    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO600"], PASS1)
    db_session.flush()

    assert noted == {"marked": ["PO600"], "cancelled": []}
    assert row.gp_missing_since == PASS1
    assert row.status == POStatus.GP_REGISTERED
    assert row.deleted_at is None


def test_a_second_miss_on_a_later_pass_cancels_and_releases_hardware(db_session, project):
    from app.models.enums import HardwareItemState
    from app.models.hardware import HardwareItem
    from app.models.project import Opening

    row = _open_mirrored(db_session, "PO601")
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="101")
    db_session.add(opening)
    db_session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category="IT1 description",
        product_code="IT1",
        item_quantity=3,
        state=HardwareItemState.IN_PO,
        po_line_item_id=row.line_items[0].id,
    )
    db_session.add(hi)
    db_session.flush()

    sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO601"], PASS1)
    db_session.flush()
    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO601"], PASS2)
    db_session.flush()

    assert noted == {"marked": [], "cancelled": ["PO601"]}
    row = _get(db_session, "PO601")
    # Cancelled exactly as a mirrored GP void is: dead status, soft-deleted, hardware handed back.
    assert row.status == POStatus.CANCELLED
    assert row.deleted_at is not None
    db_session.refresh(hi)
    assert hi.state == HardwareItemState.AVAILABLE
    assert hi.po_line_item_id is None


def test_two_misses_inside_the_same_pass_do_not_cancel(db_session, project):
    """The stamp is a PASS, not a count: the same pass reporting a number twice is still one pass."""
    _open_mirrored(db_session, "PO602")

    sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO602"], PASS1)
    db_session.flush()
    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO602"], PASS1)
    db_session.flush()

    assert noted == {"marked": [], "cancelled": []}
    row = _get(db_session, "PO602")
    assert row.status == POStatus.GP_REGISTERED
    assert row.deleted_at is None


def test_a_po_seen_again_clears_the_stamp_and_is_never_cancelled(db_session, project):
    """The whole point of the guard: a PO that reappears between two passes starts over."""
    _open_mirrored(db_session, "PO603")
    sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO603"], PASS1)
    db_session.flush()

    # GP hands it back on the next pass - the by-number re-read upserts it.
    _open_mirrored(db_session, "PO603")
    assert _get(db_session, "PO603").gp_missing_since is None

    # And a later pass that misses it again is a FIRST miss, not a second.
    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO603"], PASS2)
    db_session.flush()
    assert noted == {"marked": ["PO603"], "cancelled": []}
    row = _get(db_session, "PO603")
    assert row.gp_missing_since == PASS2
    assert row.status == POStatus.GP_REGISTERED


def test_a_number_with_no_open_row_is_ignored(db_session, project):
    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO-NOT-HERE"], PASS1)
    assert noted == {"marked": [], "cancelled": []}
    assert sync_repo.note_missing_from_gp(db_session, COMPANY, [], PASS1) == {"marked": [], "cancelled": []}


def test_a_closed_or_already_cancelled_row_is_never_touched(db_session, project):
    # Posted to history with nothing cancelled -> CLOSED; posted fully cancelled -> CANCELLED.
    closed = _open_mirrored(db_session, "PO604", source="history")
    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO605", [_line(16384, "IT1", 3, cancelled=3)], source="history"),
        _project_map(db_session),
    )
    db_session.flush()
    cancelled = _get(db_session, "PO605")
    assert closed.status == POStatus.CLOSED
    assert cancelled.status == POStatus.CANCELLED
    cancelled_deleted_at = cancelled.deleted_at

    noted = sync_repo.note_missing_from_gp(db_session, COMPANY, ["PO604", "PO605"], PASS1)
    db_session.flush()

    assert noted == {"marked": [], "cancelled": []}
    assert closed.status == POStatus.CLOSED
    assert closed.gp_missing_since is None
    assert cancelled.gp_missing_since is None
    assert cancelled.deleted_at == cancelled_deleted_at


# --- the NEXUS REGISTERED LINE rule -------------------------------------------------------------------
#
# Identity is decided per LINE, not per PO. A line whose hardware category and product code came off a
# hardware schedule keeps them forever; every other line takes GP's item number and description on
# every pass. That is what lets a GP-born PO be registered one line at a time.


def _registered_line(db_session, po, ord_, *, category, product_code, ordered=5):
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        gp_line_ord=ord_,
        hardware_category=category,
        product_code=product_code,
        ordered_quantity=ordered,
        received_quantity=0,
        unit_cost=Decimal("10.00"),
        nexus_registered=True,
    )
    db_session.add(li)
    db_session.flush()
    return li


def test_a_registered_line_keeps_its_identity_while_its_quantities_converge(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO700", [_line(16384, "HD 001", 5)]), _project_map(db_session)
    )
    db_session.flush()
    row = _get(db_session, "PO700")
    line = row.line_items[0]
    line.hardware_category = "HINGE"
    line.product_code = "HG-100"
    line.nexus_registered = True
    db_session.flush()

    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO700", [_line(16384, "HD 001", 8, received=3, unit_cost=12)]),
        _project_map(db_session),
    )
    db_session.flush()

    line = _get(db_session, "PO700").line_items[0]
    assert (line.hardware_category, line.product_code) == ("HINGE", "HG-100")
    # Quantities and unit cost are GP-owned on every line, registered or not.
    assert line.ordered_quantity == 8
    assert line.received_quantity == 3
    assert line.unit_cost == Decimal("12")


def test_an_unregistered_line_is_overwritten_with_gps_own_identity(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO701", [_line(16384, "HD 001", 5)]), _project_map(db_session)
    )
    db_session.flush()

    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO701", [_line(16384, "SP 001", 5)]), _project_map(db_session)
    )
    db_session.flush()

    line = _get(db_session, "PO701").line_items[0]
    # GP's item number into hardware_category and its description into product_code - the same way
    # round as a NEXUS REGISTERED LINE holds them.
    assert line.hardware_category == "SP 001"
    assert line.product_code == "SP 001 description"
    assert line.nexus_registered is False


def test_a_line_the_mirror_creates_starts_unregistered(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO702", [_line(16384, "HD 001", 5)]), _project_map(db_session)
    )
    db_session.flush()

    line = _get(db_session, "PO702").line_items[0]
    assert line.nexus_registered is False
    assert line.hardware_category == "HD 001"
    assert line.product_code == "HD 001 description"


def test_registration_survives_a_line_gp_has_cancelled_to_nothing(db_session, project):
    """The zeroing branch writes identity too, so it needs the same per-line rule as the live one."""
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO703",
        request_number="PO-REQ-703",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        company=COMPANY,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
    )
    db_session.add(nexus)
    db_session.flush()
    _registered_line(db_session, nexus, 16384, category="HINGE", product_code="HG-100")

    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO703", [_line(16384, "HD 001", 5, cancelled=5)]), _project_map(db_session)
    )
    db_session.flush()

    line = _get(db_session, "PO703").line_items[0]
    assert (line.hardware_category, line.product_code) == ("HINGE", "HG-100")


def test_one_registered_line_and_one_not_are_treated_apart(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO704", [_line(16384, "HD 001", 5), _line(32768, "SP 001", 2)]),
        _project_map(db_session),
    )
    db_session.flush()
    row = _get(db_session, "PO704")
    first = next(li for li in row.line_items if li.gp_line_ord == 16384)
    first.hardware_category = "HINGE"
    first.product_code = "HG-100"
    first.nexus_registered = True
    db_session.flush()

    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO704", [_line(16384, "HD 002", 5), _line(32768, "SP 002", 2)]),
        _project_map(db_session),
    )
    db_session.flush()

    row = _get(db_session, "PO704")
    registered = next(li for li in row.line_items if li.gp_line_ord == 16384)
    mirrored = next(li for li in row.line_items if li.gp_line_ord == 32768)
    assert (registered.hardware_category, registered.product_code) == ("HINGE", "HG-100")
    assert (mirrored.hardware_category, mirrored.product_code) == ("SP 002", "SP 002 description")


# --- cost code and freight, now GP-OWNED FIELDS -------------------------------------------------------


def test_freight_lands_in_shipping_cost(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO710", [_line(16384, "IT1", 5)], freight=125.5), _project_map(db_session)
    )
    db_session.flush()
    assert _get(db_session, "PO710").shipping_cost == Decimal("125.50")

    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO710", [_line(16384, "IT1", 5)], freight=0), _project_map(db_session)
    )
    db_session.flush()
    # GP dropping the charge to zero is a real value, not an absent one.
    assert _get(db_session, "PO710").shipping_cost == Decimal("0.00")


def test_cost_code_comes_from_the_first_line_carrying_one(db_session, project):
    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO711", [_line(16384, "IT1", 5), _line(32768, "IT2", 2, cost_code="210-200-2")]),
        _project_map(db_session),
    )
    db_session.flush()
    assert _get(db_session, "PO711").cost_code == "210-200-2"


def test_lines_that_disagree_on_a_cost_code_each_keep_their_own(db_session, project):
    """The PO's own column is the first line's code and nothing more - a summary for the register.
    Each line stores what GP actually books it against, so a PO built on two codes is represented
    faithfully line by line."""
    sync_repo.upsert_mirrored_po(
        db_session,
        COMPANY,
        _po("PO712", [_line(16384, "IT1", 5, cost_code="210-200-2"), _line(32768, "IT2", 2, cost_code="310-000-3")]),
        _project_map(db_session),
    )
    db_session.flush()
    row = _get(db_session, "PO712")
    assert row.cost_code == "210-200-2"
    by_ord = {li.gp_line_ord: li for li in row.line_items}
    assert by_ord[16384].cost_code == "210-200-2"
    assert by_ord[32768].cost_code == "310-000-3"
    # Both carry GP's job number, so both are job-cost lines.
    assert by_ord[16384].job_cost is True
    assert by_ord[32768].job_cost is True


def test_a_line_with_no_gp_job_is_not_a_job_cost_line(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO714", [_line(16384, "IT1", 5, job="J1", cost_code="210-200-2")]), pm
    )
    db_session.flush()
    assert _get(db_session, "PO714").line_items[0].job_cost is True

    # GP takes the job off the line: it books to nothing now, and the code goes with the job.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO714", [_line(16384, "IT1", 5, job=None)]), pm)
    db_session.flush()
    line = _get(db_session, "PO714").line_items[0]
    assert line.job_cost is False
    assert line.cost_code is None


def test_a_relay_too_old_to_read_the_line_cost_code_leaves_it_alone(db_session, project):
    """Same rule as the PO's own cost code: absent is not blank, and a workstation that has not been
    updated must not wipe what a registration typed."""
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO717", [_line(16384, "IT1", 5, cost_code="210-200-2")]), pm)
    db_session.flush()

    # _line() carries cost_code None unless asked, which is an old relay's payload.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO717", [_line(16384, "IT1", 5)]), pm)
    db_session.flush()

    assert _get(db_session, "PO717").line_items[0].cost_code == "210-200-2"


def test_a_gp_read_with_no_lines_is_not_mirrored(db_session, project, caplog):
    """A PO somebody has opened in GP's Purchase Order Entry and not yet given a line to. Mirroring
    the header alone would put a PO for no hardware in the register, receivable by nobody."""
    import logging

    with caplog.at_level(logging.INFO, logger="app.repositories.gp_po_sync_repository"):
        action = sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO715", []), _project_map(db_session))
    db_session.flush()

    assert action == "skipped"
    assert _get(db_session, "PO715") is None
    assert "has no lines in GP yet" in caplog.text


def test_a_lineless_read_leaves_a_row_that_already_exists_alone(db_session, project):
    """GP momentarily reporting a PO with no lines must not converge quantities or status against an
    empty line set - the row is left exactly as the last real read wrote it."""
    sync_repo.upsert_mirrored_po(
        db_session, COMPANY, _po("PO716", [_line(16384, "IT1", 5, received=2)]), _project_map(db_session)
    )
    db_session.flush()
    before = _get(db_session, "PO716")
    synced_at = before.gp_synced_at

    action = sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO716", []), _project_map(db_session))
    db_session.flush()

    assert action == "skipped"
    row = _get(db_session, "PO716")
    assert row.status == POStatus.PARTIALLY_RECEIVED
    assert row.gp_synced_at == synced_at
    assert len(row.line_items) == 1
    assert row.line_items[0].ordered_quantity == 5


def test_a_relay_that_sends_neither_key_leaves_both_values_alone(db_session, project):
    """The relay ships separately from the backend. Until the workstation is updated the keys are
    simply absent, and absent must not read as zero - that would wipe what registration typed."""
    nexus = PurchaseOrder(
        id=uuid.uuid4(),
        po_number="PO713",
        request_number="PO-REQ-713",
        origin=POOrigin.NEXUS,
        gp_company=COMPANY,
        company=COMPANY,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        cost_code="210-200-2",
        shipping_cost=Decimal("42.00"),
    )
    db_session.add(nexus)
    db_session.flush()
    _registered_line(db_session, nexus, 16384, category="HINGE", product_code="HG-100")

    # _po() omits "freight" unless asked, and _line() carries cost_code None: an old relay's payload.
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO713", [_line(16384, "IT1", 5)]), _project_map(db_session))
    db_session.flush()

    row = _get(db_session, "PO713")
    assert row.shipping_cost == Decimal("42.00")
    assert row.cost_code == "210-200-2"


# --- the NEW PO CHECK's cursor ------------------------------------------------------------------------


def test_the_new_po_cursor_is_the_highest_gp_number_this_company_holds(db_session, project):
    pm = _project_map(db_session)
    for number in ("PO0000900", "PO0000902", "PO0000901"):
        sync_repo.upsert_mirrored_po(db_session, COMPANY, _po(number, [_line(16384, "IT1", 1)]), pm)
    db_session.flush()

    assert sync_repo.highest_gp_po_number(db_session, COMPANY) == "PO0000902"


def test_the_new_po_cursor_ignores_a_number_that_is_not_gps_own_shape(db_session, project):
    """A hand-typed number sorts above every real one, and parking the cursor there would hide every
    PO GP is about to mint behind it."""
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO0000910", [_line(16384, "IT1", 1)]), pm)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO0000910-REV2", [_line(16384, "IT1", 1)]), pm)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("MANUAL-4", [_line(16384, "IT1", 1)]), pm)
    db_session.flush()

    assert sync_repo.highest_gp_po_number(db_session, COMPANY) == "PO0000910"


def test_the_new_po_cursor_is_scoped_to_one_company(db_session, project):
    pm = _project_map(db_session)
    sync_repo.upsert_mirrored_po(db_session, COMPANY, _po("PO0000920", [_line(16384, "IT1", 1)]), pm)
    sync_repo.upsert_mirrored_po(db_session, "UCSH", _po("PO0000999", [_line(16384, "IT1", 1)]), pm)
    db_session.flush()

    assert sync_repo.highest_gp_po_number(db_session, COMPANY) == "PO0000920"


def test_a_company_with_no_gp_number_has_no_cursor(db_session, project):
    assert sync_repo.highest_gp_po_number(db_session, "UBC") is None
