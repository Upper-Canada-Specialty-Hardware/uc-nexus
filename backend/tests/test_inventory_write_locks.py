"""Inventory writers read the row under the combo lock, not the copy the session already holds (#1119).

Adjust, override, split, transfer and the deficiency report each read a row's count and then write
an absolute value. A pick confirmed in between used to be overwritten: the writer computed off the
count it had read before the pick. Each now takes the combo's rows FOR UPDATE and re-reads them.

A real race needs two connections. What a single rolled-back transaction can prove is the re-read:
the row is loaded into the session, its quantity is changed underneath the ORM (as another
transaction's committed pick would be), and the writer must compute off the new value, not the
stale identity-map copy a plain FOR UPDATE would hand back.
"""

import pytest
from sqlalchemy import update

from app.errors import ValidationError
from app.models.inventory import InventoryLocation
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.services.locking import lock_inventory_combo

from .inventory_fixtures import define_location, make_il, make_project, wh_id


def _picked_underneath(session, il, new_quantity):
    """Change the row the way a concurrent committed pick would: in SQL, behind the session's back."""
    session.execute(
        update(InventoryLocation)
        .where(InventoryLocation.id == il.id)
        .values(quantity=new_quantity)
        .execution_options(synchronize_session=False)
    )
    assert il.quantity != new_quantity  # the session still holds the stale copy


def test_the_combo_lock_returns_the_row_fresh(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _picked_underneath(db_session, il, 6)

    locked = lock_inventory_combo(db_session, il.id)

    assert locked is il
    assert locked.quantity == 6


def test_adjust_computes_off_the_count_after_a_pick(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _picked_underneath(db_session, il, 6)

    warehouse_repository.adjust_inventory_quantity(db_session, il.id, -1, "recount", performed_by="warehouse")

    assert il.quantity == 5  # 6 - 1, not the stale 10 - 1


def test_override_decrease_reads_the_count_after_a_pick(db_session):
    """The audit's old quantity is the real one, and an override to the picked count is a no-op."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _picked_underneath(db_session, il, 6)

    warehouse_repository.override_inventory_quantity(
        db_session, inv_id=il.id, new_quantity=5, reason="recount", destinations=[], performed_by="warehouse"
    )
    assert il.quantity == 5


def test_split_reads_the_count_after_a_pick(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle=None, row=None, bay=None)
    _picked_underneath(db_session, il, 4)

    kept, moved = warehouse_repository.split_inventory_location(db_session, il.id, 3, performed_by="picker")

    assert (kept.quantity, moved.quantity) == (1, 3)


def test_deficiency_report_reads_the_count_after_a_pick(db_session):
    """Flagging 5 of a stale 10 would pass; of the real 4 it must be refused."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _picked_underneath(db_session, il, 4)

    with pytest.raises(ValidationError):
        stock_repository.report_inventory_deficiency(
            db_session, inventory_location_id=il.id, quantity=5, reason_text="damaged", performed_by="warehouse"
        )


def test_transfer_reads_the_count_after_a_pick(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    define_location(db_session, aisle="B", row="2", bay="2")
    _picked_underneath(db_session, il, 4)

    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=5,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="2",
            dest_bay="2",
            performed_by="warehouse",
        )
