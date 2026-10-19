"""A resend after a lost reply must not move the units a second time (#1552).

Warehouse wifi drops after the server commits but before the reply reaches the tablet: the dialog
shows a network error, keeps its input, and the user confirms again. Every delta move carries the
count the dialog showed, so the resend finds the row already moved by its own first attempt and is
refused. Each test runs the move once with the shown count, then resends it unchanged.
"""

import pytest

from app.errors import ConflictError
from app.models.enums import DeficiencyResolution, DestockCost, DestockSource, PoolKind
from app.repositories import stock as stock_repository

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def test_a_resent_transfer_off_a_project_row_is_refused(db_session):
    """The issue's own example: 10 on a row, transfer 4, reply lost, transfer again."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    define_location(db_session, aisle="B", row="2", bay="2")

    def transfer():
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=4,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="2",
            dest_bay="2",
            performed_by="warehouse",
            expected_quantity=10,
        )

    transfer()
    with pytest.raises(ConflictError) as exc:
        transfer()

    assert exc.value.field == "expected_quantity"
    db_session.refresh(il)
    assert il.quantity == 6


def test_a_resent_transfer_off_a_pool_row_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, aisle="A", row="1", bay="1")
    define_location(db_session, aisle="B", row="2", bay="2")

    def transfer():
        stock_repository.transfer_inventory(
            db_session,
            source_type="STOCK_ITEM",
            source_id=si.id,
            quantity=4,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="2",
            dest_bay="2",
            performed_by="warehouse",
            expected_quantity=10,
        )

    transfer()
    with pytest.raises(ConflictError):
        transfer()

    db_session.refresh(si)
    assert si.quantity == 6


def test_a_resent_destock_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    def destock():
        return stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=4,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
            destock_cost=DestockCost.ZERO,
            expected_quantity=10,
        )

    pool_row = destock()
    with pytest.raises(ConflictError):
        destock()

    db_session.refresh(il)
    db_session.refresh(pool_row)
    assert il.quantity == 6
    assert pool_row.quantity == 4


def test_a_resent_allocation_is_refused(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)

    def allocate():
        stock_repository.allocate_stock_to_project(
            db_session,
            stock_item_id=si.id,
            project_id=project.id,
            target_hardware_category="HINGE",
            target_product_code="HG-100",
            quantity=4,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
            expected_quantity=10,
        )

    allocate()
    with pytest.raises(ConflictError):
        allocate()

    db_session.refresh(si)
    assert si.quantity == 6


def test_a_resent_partial_reclassify_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, aisle="A", row="1", bay="1")

    def reclassify():
        stock_repository.reclassify_stock_item(
            db_session,
            stock_item_id=si.id,
            new_hardware_category="HINGE",
            new_product_code="HG-200",
            quantity=4,
            reason_text=None,
            performed_by="warehouse",
            expected_quantity=10,
        )

    reclassify()
    with pytest.raises(ConflictError):
        reclassify()

    db_session.refresh(si)
    assert si.quantity == 6


def test_a_resent_partial_kind_change_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, aisle="A", row="1", bay="1")

    def set_kind():
        stock_repository.set_stock_item_kind(
            db_session,
            stock_item_id=si.id,
            kind=PoolKind.OVERHEAD,
            quantity=4,
            performed_by="warehouse",
            expected_quantity=10,
        )

    set_kind()
    with pytest.raises(ConflictError):
        set_kind()

    db_session.refresh(si)
    assert si.quantity == 6


def test_a_resent_deficiency_report_is_refused(db_session):
    """A report leaves the quantity alone, so only the flagged count tells the resend apart."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    def report():
        stock_repository.report_inventory_deficiency(
            db_session,
            inventory_location_id=il.id,
            quantity=2,
            reason_text="dented",
            performed_by="warehouse",
            expected_deficient_quantity=0,
        )

    report()
    with pytest.raises(ConflictError) as exc:
        report()

    assert exc.value.field == "expected_deficient_quantity"
    db_session.refresh(il)
    assert il.deficient_quantity == 2


def test_a_resent_pool_deficiency_report_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10)

    def report():
        stock_repository.report_stock_deficiency(
            db_session,
            stock_item_id=si.id,
            quantity=2,
            reason_text="dented",
            performed_by="warehouse",
            expected_deficient_quantity=0,
        )

    report()
    with pytest.raises(ConflictError):
        report()

    db_session.refresh(si)
    assert si.deficient_quantity == 2


def test_a_resent_repair_is_refused(db_session):
    """A repair clears flags without touching the quantity: 4 flagged, repair 2, resend."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    def repair():
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.REPAIR,
            quantity=2,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
            expected_deficient_quantity=4,
        )

    repair()
    with pytest.raises(ConflictError):
        repair()

    db_session.refresh(il)
    assert il.deficient_quantity == 2
    assert il.quantity == 10


def test_a_resent_pool_scrap_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    def scrap():
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=None,
            stock_item_id=si.id,
            resolution=DeficiencyResolution.SCRAP,
            quantity=2,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
            expected_deficient_quantity=4,
        )

    scrap()
    with pytest.raises(ConflictError):
        scrap()

    db_session.refresh(si)
    assert (si.quantity, si.deficient_quantity) == (8, 2)


def test_a_move_without_the_shown_count_still_applies(db_session):
    """A tab loaded on the previous build sends no count; it keeps working, unchecked."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)
    define_location(db_session, aisle="B", row="2", bay="2")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=4,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    db_session.refresh(il)
    assert il.quantity == 6
