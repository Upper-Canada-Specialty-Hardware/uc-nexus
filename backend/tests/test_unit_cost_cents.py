"""GP keeps a PO line's unit cost to the cent (#1394).

A test PO on TUBC at 0.33333 was refused at the line by eConnect (taPoLine 6621). Registration now refuses
such a cost before anything reaches GP, naming the line, instead of surfacing GP's raw error."""

import pytest

from app.errors import ValidationError
from app.repositories.po_repository import (
    refuse_unit_cost_too_large,
    unit_cost_past_cents,
    update_line_item_unit_cost,
    validate_line_unit_costs,
)


@pytest.mark.parametrize("cost", [0, 5, 100, 0.1, 12.34, "12.30", None])
def test_costs_to_the_cent_pass(cost):
    assert not unit_cost_past_cents(cost)


@pytest.mark.parametrize("cost", [0.33333, 12.345, 0.001, "1.005"])
def test_costs_past_the_cent_are_caught(cost):
    assert unit_cost_past_cents(cost)


def test_registration_names_each_line_gp_would_refuse():
    lines = [
        {"product_code": "HG-1", "unit_cost": 12.5},
        {"product_code": "SD-84C", "unit_cost": 0.33333},
        {"product_code": "CL-2", "unit_cost": 1.255},
    ]
    with pytest.raises(ValidationError) as err:
        validate_line_unit_costs(lines)

    assert err.value.field == "line_items"
    assert "SD-84C at 0.33333" in err.value.message and "CL-2 at 1.255" in err.value.message
    assert "HG-1" not in err.value.message


def test_registration_with_every_cost_to_the_cent_passes():
    validate_line_unit_costs([{"product_code": "HG-1", "unit_cost": 12.5}, {"product_code": "X", "unit_cost": 0}])


# A line's unit_cost is Numeric(19,5): a cost at or past 10^14 overflowed at flush, the masked server
# error (#1936). It is refused on the field instead, on every path that writes one.


@pytest.mark.parametrize("cost", [10**14, 1e15, "100000000000000"])
def test_a_unit_cost_too_large_for_its_column_is_refused_on_the_field(cost):
    with pytest.raises(ValidationError) as err:
        refuse_unit_cost_too_large(cost)
    assert err.value.field == "unit_cost"
    assert "100,000,000,000,000" in err.value.message


@pytest.mark.parametrize("cost", [None, 0, 12.5, 99_999_999_999_999.99])
def test_a_unit_cost_the_column_holds_passes(cost):
    refuse_unit_cost_too_large(cost)


def test_registration_refuses_a_unit_cost_too_large_before_gp():
    with pytest.raises(ValidationError) as err:
        validate_line_unit_costs([{"product_code": "HG-1", "unit_cost": 1e14}])
    assert err.value.field == "unit_cost"


def test_a_cost_edit_too_large_is_refused_before_the_row_is_read():
    # The refusal comes before any session use, so no database is needed to pin it.
    with pytest.raises(ValidationError) as err:
        update_line_item_unit_cost(None, None, 1e14)
    assert err.value.field == "unit_cost"
