"""Pool writers read the row under a lock, not the copy the session already holds (#1156).

Allocate, adjust, reclassify, set-kind, the deficiency report and resolve each read a pool row's
count and then write it back, and destock does the same to a project row. A concurrent write in
between used to be overwritten or double-spent. Each now takes the row FOR UPDATE and re-reads it.

As in test_inventory_write_locks: a real race needs two connections, so what a single rolled-back
transaction proves is the re-read. The row is changed underneath the ORM, the way another
transaction's committed write would be, and the writer must act on the new value.
"""

import pytest
from sqlalchemy import update

from app.errors import ValidationError
from app.models.enums import DeficiencyResolution, DestockCost, DestockSource, PoolKind
from app.models.inventory import InventoryLocation
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def _changed_underneath(session, model, row, **values):
    """Write the row in SQL, behind the session's back, as a concurrent committed write would."""
    session.execute(
        update(model).where(model.id == row.id).values(**values).execution_options(synchronize_session=False)
    )


def test_allocate_reads_the_pool_count_after_another_allocation(db_session):
    """Allocating 8 off a stale 10 would pass; off the real 2 it must be refused."""
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)
    _changed_underneath(db_session, StockItem, si, quantity=2)
    assert si.quantity == 10  # the session still holds the stale copy

    with pytest.raises(ValidationError):
        stock_repository.allocate_stock_to_project(
            db_session,
            stock_item_id=si.id,
            project_id=project.id,
            target_hardware_category="HINGE",
            target_product_code="HG-100",
            quantity=8,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
        )


def test_adjust_stock_audits_the_count_after_a_concurrent_move(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=0)
    _changed_underneath(db_session, StockItem, si, deficient_quantity=6)

    with pytest.raises(ValidationError):
        # 5 is fine against the stale deficient 0, and below the real deficient 6.
        stock_repository.adjust_stock_quantity(
            db_session, stock_item_id=si.id, new_quantity=5, reason_text="recount", performed_by="warehouse"
        )


def test_reclassify_reads_the_pool_count_after_another_write(db_session):
    si = make_stock_item(db_session, quantity=10)
    _changed_underneath(db_session, StockItem, si, quantity=3)

    with pytest.raises(ValidationError):
        stock_repository.reclassify_stock_item(
            db_session,
            stock_item_id=si.id,
            new_hardware_category="HINGE",
            new_product_code="HG-200",
            quantity=5,
            reason_text=None,
            performed_by="warehouse",
        )


def test_set_kind_reads_the_pool_count_after_another_write(db_session):
    si = make_stock_item(db_session, quantity=10)
    _changed_underneath(db_session, StockItem, si, quantity=3)

    with pytest.raises(ValidationError):
        stock_repository.set_stock_item_kind(
            db_session, stock_item_id=si.id, kind=PoolKind.OVERHEAD, quantity=5, performed_by="warehouse"
        )


def test_stock_deficiency_report_reads_the_count_after_another_write(db_session):
    """Flagging 5 of a stale 10 would pass and then trip the deficient <= quantity check as a raw 500."""
    si = make_stock_item(db_session, quantity=10)
    _changed_underneath(db_session, StockItem, si, quantity=4)

    with pytest.raises(ValidationError):
        stock_repository.report_stock_deficiency(
            db_session, stock_item_id=si.id, quantity=5, reason_text="damaged", performed_by="warehouse"
        )


def test_resolve_on_a_pool_row_reads_the_deficient_count_after_another_resolve(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)
    _changed_underneath(db_session, StockItem, si, quantity=6, deficient_quantity=0)

    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=None,
            stock_item_id=si.id,
            resolution=DeficiencyResolution.SCRAP,
            quantity=4,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )


def test_resolve_on_a_project_row_reads_the_deficient_count_after_another_resolve(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)
    _changed_underneath(db_session, InventoryLocation, il, quantity=6, deficient_quantity=0)

    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.SCRAP,
            quantity=4,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )


def test_resolve_refuses_an_rma_reference_over_100_characters(db_session):
    """The column is String(100); a longer reference is a field error, not a raw flush failure (#1209)."""
    si = make_stock_item(db_session, quantity=10, deficient=4)

    with pytest.raises(ValidationError) as exc:
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=None,
            stock_item_id=si.id,
            resolution=DeficiencyResolution.RETURN_TO_VENDOR,
            quantity=1,
            reason_text=None,
            rma_reference="R" * 101,
            destock_source=None,
            reviewed_by="manager",
        )
    assert exc.value.field == "rma_reference"


def test_destock_computes_off_the_count_after_a_pick(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    _changed_underneath(db_session, InventoryLocation, il, quantity=6)

    stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=2,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=DestockCost.ZERO,
    )

    assert il.quantity == 4  # 6 - 2, not the stale 10 - 2


def test_destock_adds_to_the_pool_count_after_another_destock(db_session):
    """The target pool row is re-read too, so a concurrent increment into it is kept."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    pool = make_stock_item(db_session, quantity=3, aisle="A", row="1", bay="1", unit_cost=0)
    _changed_underneath(db_session, StockItem, pool, quantity=5)

    row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=2,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
        destock_cost=DestockCost.ZERO,
    )

    assert row.id == pool.id
    assert row.quantity == 7  # 5 + 2, not the stale 3 + 2


def test_merge_folds_a_pool_row_into_the_same_key_row_on_the_target_shelf(db_session):
    define_location(db_session, aisle="A", row="1", bay="1")
    define_location(db_session, aisle="B", row="2", bay="2")
    source = make_stock_item(db_session, quantity=4, deficient=1, aisle="A", row="1", bay="1")
    target = make_stock_item(db_session, quantity=6, aisle="B", row="2", bay="2")
    other = make_stock_item(db_session, quantity=2, code="HG-999", aisle="A", row="1", bay="1")

    warehouse_repository.merge_locations(
        db_session,
        warehouse_id=wh_id(db_session),
        from_aisle="A",
        from_row="1",
        from_bay="1",
        to_aisle="B",
        to_row="2",
        to_bay="2",
        performed_by="manager",
    )

    assert (target.quantity, target.deficient_quantity) == (10, 1)
    assert (source.quantity, source.deficient_quantity) == (0, 0)
    # A row with no same-key partner on the target shelf simply moves.
    assert (other.aisle, other.row, other.bay, other.quantity) == ("B", "2", "2", 2)


def test_merge_refuses_an_empty_from_aisle_and_leaves_unlocated_rows_alone(db_session):
    """Only row and bay match null; an empty aisle would otherwise sweep every unlocated row onto the shelf."""
    define_location(db_session, aisle="B", row="2", bay="2")
    project = make_project(db_session)
    unlocated = make_il(db_session, project, quantity=3, aisle=None, row=None, bay=None)

    with pytest.raises(ValidationError) as exc:
        warehouse_repository.merge_locations(
            db_session,
            warehouse_id=wh_id(db_session),
            from_aisle="",
            from_row="",
            from_bay="",
            to_aisle="B",
            to_row="2",
            to_bay="2",
            performed_by="manager",
        )

    assert exc.value.field == "from_aisle"
    assert unlocated.aisle is None


def test_merge_matches_an_empty_row_and_bay_as_null(db_session):
    """The cleanup page sends a variant's missing row/bay as '' (#1199); the NULL rows must still move."""
    define_location(db_session, aisle="B", row="2", bay="2")
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=3, aisle="A", row=None, bay=None)
    si = make_stock_item(db_session, quantity=2, code="HG-777", aisle="A", row=None, bay=None)

    counts = warehouse_repository.merge_locations(
        db_session,
        warehouse_id=wh_id(db_session),
        from_aisle="A",
        from_row="",
        from_bay="",
        to_aisle="B",
        to_row="2",
        to_bay="2",
        performed_by="manager",
    )

    assert counts["inventory_locations"] >= 1 and counts["stock_items"] >= 1
    assert (il.aisle, il.row, il.bay) == ("B", "2", "2")
    assert (si.aisle, si.row, si.bay) == ("B", "2", "2")


def test_move_folds_into_the_same_key_row_on_the_target_shelf(db_session):
    """#1377: a move onto a shelf already holding the row's key sums into that row; the unreferenced
    source is deleted."""
    define_location(db_session, aisle="C", row="3", bay="3")
    source = make_stock_item(db_session, quantity=4, deficient=1, aisle="A", row="1", bay="1")
    target = make_stock_item(db_session, quantity=6, aisle="C", row="3", bay="3")
    source_id = source.id

    result = stock_repository.move_stock_location(
        db_session, stock_item_id=source_id, new_aisle="C", new_row="3", new_bay="3", performed_by="warehouse"
    )

    assert result.id == target.id
    assert (target.quantity, target.deficient_quantity) == (10, 1)
    assert db_session.get(StockItem, source_id) is None


def test_put_away_folds_and_keeps_a_referenced_source_empty(db_session):
    """A source that is still the origin of an allocated project row is emptied, not deleted."""
    define_location(db_session, aisle="C", row="3", bay="3")
    project = make_project(db_session)
    source = make_stock_item(db_session, quantity=4)
    make_il(db_session, project, quantity=1, stock_item_id=source.id)
    target = make_stock_item(db_session, quantity=6, aisle="C", row="3", bay="3")

    result = stock_repository.assign_stock_item_location(
        db_session, stock_item_id=source.id, aisle="C", row="3", bay="3", performed_by="warehouse"
    )

    assert result.id == target.id
    assert target.quantity == 10
    assert db_session.get(StockItem, source.id) is not None
    assert (source.quantity, source.deficient_quantity) == (0, 0)


def test_move_without_a_same_key_row_just_moves(db_session):
    define_location(db_session, aisle="C", row="3", bay="3")
    source = make_stock_item(db_session, quantity=4, aisle="A", row="1", bay="1")
    make_stock_item(db_session, quantity=6, code="HG-OTHER", aisle="C", row="3", bay="3")

    result = stock_repository.move_stock_location(
        db_session, stock_item_id=source.id, new_aisle="C", new_row="3", new_bay="3", performed_by="warehouse"
    )

    assert result.id == source.id
    assert (source.aisle, source.row, source.bay, source.quantity) == ("C", "3", "3", 4)
