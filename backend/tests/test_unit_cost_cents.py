"""GP keeps a PO line's unit cost to the cent (#1394).

A test PO on TUBC at 0.33333 was refused at the line by eConnect (taPoLine 6621). Registration now refuses
such a cost before anything reaches GP, naming the line, instead of surfacing GP's raw error."""

import pytest

from app.errors import ValidationError
from app.repositories.po_repository import unit_cost_past_cents, validate_line_unit_costs


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
