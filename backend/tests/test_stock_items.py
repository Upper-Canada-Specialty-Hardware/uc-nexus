"""Stock-pool corrections (stock/items.py): reclassify and absolute-quantity adjust.

The split branch of reclassify used to 500 - it created the destination stock row without a
warehouse_id. Because the UI caps the quantity at the available (non-deficient) count, any row that
carries deficient units can only ever take the split branch, so exact full-row reclassify was the
only thing that worked.
"""

import pytest

from app.errors import ValidationError
from app.repositories import stock as stock_repository

from .inventory_fixtures import make_stock_item

# --- reclassify ---------------------------------------------------------------------------------


def test_reclassify_full_row_changes_category_in_place(db_session):
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    reclassified, original = stock_repository.reclassify_stock_item(
        db_session,
        stock_item_id=si.id,
        new_hardware_category="STRIKE",
        new_product_code="ST-200",
        quantity=10,
        reason_text="mislabelled",
        performed_by="warehouse",
    )

    assert original is None
    assert reclassified.id == si.id
    assert (si.hardware_category, si.product_code) == ("STRIKE", "ST-200")
    assert si.quantity == 10


def test_reclassify_split_moves_part_to_a_new_row(db_session):
    """The branch that crashed: the new row is created via _find_or_create_stock_row."""
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    new_row, original = stock_repository.reclassify_stock_item(
        db_session,
        stock_item_id=si.id,
        new_hardware_category="STRIKE",
        new_product_code="ST-200",
        quantity=4,
        reason_text="partial mislabel",
        performed_by="warehouse",
    )

    assert original.id == si.id
    assert original.quantity == 6
    assert original.hardware_category == "HINGE"
    assert new_row.quantity == 4
    assert (new_row.hardware_category, new_row.product_code) == ("STRIKE", "ST-200")
    assert new_row.warehouse_id == si.warehouse_id


def test_reclassify_split_on_a_row_with_deficient_units(db_session):
    """qty 10 / deficient 3 -> available 7, so reclassify 4 is legal and must take the split path."""
    si = make_stock_item(db_session, quantity=10, deficient=3, category="HINGE", code="HG-100")

    new_row, original = stock_repository.reclassify_stock_item(
        db_session,
        stock_item_id=si.id,
        new_hardware_category="STRIKE",
        new_product_code="ST-200",
        quantity=4,
        reason_text=None,
        performed_by="warehouse",
    )

    assert original.quantity == 6
    assert original.deficient_quantity == 3  # the deficient units stay on the original row
    assert new_row.quantity == 4
    assert new_row.warehouse_id == si.warehouse_id


def test_reclassify_cannot_touch_deficient_units(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=3)  # available 7

    with pytest.raises(ValidationError):
        stock_repository.reclassify_stock_item(
            db_session,
            stock_item_id=si.id,
            new_hardware_category="STRIKE",
            new_product_code="ST-200",
            quantity=8,  # > available 7
            reason_text=None,
            performed_by="warehouse",
        )


def test_reclassify_beyond_stock_quantity_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10)

    with pytest.raises(ValidationError):
        stock_repository.reclassify_stock_item(
            db_session,
            stock_item_id=si.id,
            new_hardware_category="STRIKE",
            new_product_code="ST-200",
            quantity=11,
            reason_text=None,
            performed_by="warehouse",
        )


def test_reclassify_requires_a_target_category_and_code(db_session):
    si = make_stock_item(db_session, quantity=10)

    with pytest.raises(ValidationError):
        stock_repository.reclassify_stock_item(
            db_session,
            stock_item_id=si.id,
            new_hardware_category="",
            new_product_code="ST-200",
            quantity=4,
            reason_text=None,
            performed_by="warehouse",
        )


# --- adjust_stock_quantity (absolute recount) ---------------------------------------------------


def test_adjust_stock_quantity_sets_an_absolute_value(db_session):
    si = make_stock_item(db_session, quantity=10)

    stock_repository.adjust_stock_quantity(
        db_session, stock_item_id=si.id, new_quantity=7, reason_text="recount", performed_by="warehouse"
    )

    assert si.quantity == 7


def test_adjust_stock_quantity_below_deficient_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    with pytest.raises(ValidationError):
        stock_repository.adjust_stock_quantity(
            db_session, stock_item_id=si.id, new_quantity=3, reason_text="recount", performed_by="warehouse"
        )


def test_adjust_stock_quantity_down_to_deficient_floor_is_allowed(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    stock_repository.adjust_stock_quantity(
        db_session, stock_item_id=si.id, new_quantity=4, reason_text="recount", performed_by="warehouse"
    )

    assert si.quantity == 4


def test_adjust_stock_quantity_negative_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10)

    with pytest.raises(ValidationError):
        stock_repository.adjust_stock_quantity(
            db_session, stock_item_id=si.id, new_quantity=-1, reason_text="recount", performed_by="warehouse"
        )


def test_adjust_stock_quantity_requires_a_reason(db_session):
    si = make_stock_item(db_session, quantity=10)

    with pytest.raises(ValidationError):
        stock_repository.adjust_stock_quantity(
            db_session, stock_item_id=si.id, new_quantity=7, reason_text="", performed_by="warehouse"
        )


def test_reclassify_split_carries_the_unit_cost(db_session):
    """The split used to drop the off-PO cost the full in-place reclassify kept."""
    from decimal import Decimal

    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100", unit_cost=Decimal("6"))

    new_row, _ = stock_repository.reclassify_stock_item(
        db_session,
        stock_item_id=si.id,
        new_hardware_category="STRIKE",
        new_product_code="ST-200",
        quantity=4,
        reason_text="partial mislabel",
        performed_by="warehouse",
    )

    assert new_row.unit_cost == Decimal("6")
