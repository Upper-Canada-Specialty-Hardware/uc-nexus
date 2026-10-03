"""The hard reservation gate on destock, and the deliberate absence of it elsewhere (#342).

Post-creation inventory writes can shrink a project's on-hand below what active requests have already
reserved, silently stranding a picker's claim. Creation is airtight, so this closes the one write
that moves sound stock out of the project - destock - and makes it refuse rather than corrupt.

The writes that record physical reality are not refused outright. A count correction (adjust, spot
check, override) below reserved needs a Warehouse Manager's confirmation and flags the stranded
holders (#1124); flagging units deficient still proceeds - a condemned unit is a fact, not a claim.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import DestockCost, DestockSource, NotificationType
from app.models.notification import Notification
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_il, make_project, make_reservation

# --- the gate: destock only ---------------------------------------------------------------------


def test_destock_that_would_strand_a_reservation_is_refused(db_session):
    """5 on hand, 4 reserved -> only 1 is free. Destocking 3 as OVERAGE would leave on-hand 2 under
    the 4-unit claim, so it is refused and the message names the reserved count."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=5)
    make_reservation(db_session, project, quantity=4)

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=3,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
            destock_cost=DestockCost.ZERO,
        )

    assert excinfo.value.field == "quantity"
    assert "4" in excinfo.value.message  # the reserved count is named
    assert il.quantity == 5  # nothing moved


def test_destock_of_true_overage_above_the_claim_is_allowed(db_session):
    """10 on hand, 4 reserved -> 6 are free of the claim. Destocking exactly 6 leaves on-hand 4,
    which still covers the reservation, so it goes through."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=6,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=DestockCost.ZERO,
    )

    assert il.quantity == 4  # exactly the reserved count remains
    assert stock_row.quantity == 6


def test_deficient_swap_is_never_blocked_by_the_gate(db_session):
    """A DEFICIENT_SWAP removes deficient units, which are already excluded from availability, so it
    can never strand a claim - even when every free unit is reserved. Here on-hand 10 / deficient 3
    with 7 reserved leaves 0 free, which would block any sound destock; the swap of the 3 deficient
    units still proceeds and leaves on-hand 7, exactly the claim."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=3)
    make_reservation(db_session, project, quantity=7)

    stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=3,
        source=DestockSource.DEFICIENT_SWAP,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=DestockCost.ZERO,
    )

    assert il.quantity == 7
    assert il.deficient_quantity == 0


def test_the_gate_reads_availability_under_lock(db_session, monkeypatch):
    """The check consults get_available_quantities with lock=True, so it takes FOR UPDATE on the
    combo's inventory rows and serialises with a concurrent reservation mint reading the same number.
    Spy on the call to prove the lock is asked for."""
    import app.repositories.stock.movements as movements

    real = movements.get_available_quantities
    locks_seen: list[bool] = []

    def spy(session, project_id, combos, *, lock=False):
        locks_seen.append(lock)
        return real(session, project_id, combos, lock=lock)

    monkeypatch.setattr(movements, "get_available_quantities", spy)

    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=2)

    stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=1,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=DestockCost.ZERO,
    )

    assert locks_seen == [True]


# --- count corrections: a Warehouse Manager decides (#1124) --------------------------------------
#
# An adjust, a spot check or an override records what is physically on the shelf, so it is not
# refused outright the way a destock is. It may not strand a claim silently either: below what is
# reserved, the write needs a Warehouse Manager's confirmation, and the stranded holders are told.

_MANAGER = lambda: True  # noqa: E731
_FLOOR = lambda: False  # noqa: E731


def _shortfall_notes(session, project):
    return list(
        session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
    )


def test_adjust_within_the_free_stock_needs_nothing(db_session):
    """10 on hand, 4 reserved: 6 are free, so counting 6 off is an ordinary correction."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    warehouse_repository.adjust_inventory_quantity(db_session, il.id, -6, "counted short", performed_by="warehouse")

    assert il.quantity == 4
    assert _shortfall_notes(db_session, project) == []


def test_adjust_below_reserved_is_refused_until_confirmed(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    with pytest.raises(ValidationError, match="4 unit\\(s\\) reserved") as excinfo:
        warehouse_repository.adjust_inventory_quantity(
            db_session, il.id, -8, "counted short", performed_by="warehouse", caller_is_manager=_MANAGER
        )
    assert "Warehouse Manager can confirm" in excinfo.value.message
    assert il.quantity == 10


def test_adjust_below_reserved_confirmed_by_the_floor_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    with pytest.raises(ValidationError, match="Only a Warehouse Manager"):
        warehouse_repository.adjust_inventory_quantity(
            db_session,
            il.id,
            -8,
            "counted short",
            performed_by="warehouse",
            caller_is_manager=_FLOOR,
            confirm_below_reserved=True,
        )
    assert il.quantity == 10


def test_the_role_is_only_looked_up_for_a_confirmed_shortfall(db_session):
    """The manager check is a Clerk round trip, so an ordinary count must never pay for it."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    def _must_not_be_called():
        raise AssertionError("role looked up for a count that strands nothing")

    warehouse_repository.adjust_inventory_quantity(
        db_session, il.id, -2, "counted short", performed_by="warehouse", caller_is_manager=_must_not_be_called
    )
    assert il.quantity == 8


def test_spot_check_below_reserved_confirmed_by_a_manager_lands_and_flags_the_holder(db_session):
    """The spot-check UI submits an adjustment of (physical - system). Confirmed by a manager it lands
    under the claim, and the batch holding the claim is flagged to the warehouse managers."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    batch = make_reservation(db_session, project, quantity=4)

    warehouse_repository.adjust_inventory_quantity(
        db_session,
        il.id,
        -7,
        "Spot check: system=10, physical=3",
        performed_by="Wendy Warehouse",
        spot_check=True,
        caller_is_manager=_MANAGER,
        confirm_below_reserved=True,
    )

    assert il.quantity == 3
    notes = _shortfall_notes(db_session, project)
    assert len(notes) == 1
    assert notes[0].recipient_role == "WAREHOUSE_MANAGER"
    assert batch.batch_number in notes[0].message
    assert "3 on hand against 4 reserved" in notes[0].message
    assert notes[0].pull_request_id == batch.pull_request_id


def test_override_below_reserved_follows_the_same_rule(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    with pytest.raises(ValidationError):
        warehouse_repository.override_inventory_quantity(
            db_session,
            inv_id=il.id,
            new_quantity=2,
            reason="physical correction",
            destinations=[],
            performed_by="admin",
        )
    assert il.quantity == 10

    warehouse_repository.override_inventory_quantity(
        db_session,
        inv_id=il.id,
        new_quantity=2,
        reason="physical correction",
        destinations=[],
        performed_by="admin",
        caller_is_manager=_MANAGER,
        confirm_below_reserved=True,
    )
    assert il.quantity == 2
    assert len(_shortfall_notes(db_session, project)) == 1


def test_flag_deficient_may_push_available_below_reserved(db_session):
    """Flagging units deficient nets them out of availability. That can drop available under the
    claim, and it still proceeds - a condemned unit is a fact, not a claim to protect."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    make_reservation(db_session, project, quantity=4)

    stock_repository.report_inventory_deficiency(
        db_session,
        inventory_location_id=il.id,
        quantity=8,
        reason_text="damaged in rack",
        performed_by="warehouse",
    )

    assert il.deficient_quantity == 8  # available now 10 - 8 - 4 = -2, and allowed
