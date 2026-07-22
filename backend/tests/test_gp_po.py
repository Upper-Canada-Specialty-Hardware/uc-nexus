"""Pure unit tests for the create_po / create_receipt relay payload builders (issue #199: GP-first
PO create/register + receive, brokered server-side). No DB, no relay - just the field mapping."""

from app.services import gp_po


def _line_item(**overrides) -> dict:
    base = {
        "hardware_category": "HINGE",
        "product_code": "AB123",
        "ordered_quantity": 2,
        "unit_cost": 12.5,
        "order_as": "ML2010",
    }
    base.update(overrides)
    return base


def test_build_create_po_payload_non_job_line():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name="Jane Vendor",
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
    )
    assert payload["header"]["vendor_id"] == "ING100"
    assert payload["header"]["buyer_id"] == "mira"
    assert payload["header"]["confirm_with"] == "Jane Vendor"
    assert payload["po_number"] is None
    line = payload["lines"][0]
    assert line["item_number"] == "ML2010"
    assert line["item_description"] == "AB123 HINGE"
    assert line["quantity"] == 2
    assert line["unit_cost"] == 12.5
    assert line["product_indicator"] == 1
    assert line["job_number"] is None
    assert line["cost_code"] is None


def test_build_create_po_payload_defaults_gp_charges_to_zero_without_tax_detail():
    # issue #257: with no charges/tax passed, the header carries the zeroed GP charge fields (the
    # relay POHeader Decimals are non-null) and a null tax detail (relay writes no tax).
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100", vendor_contact_name=None, buyer_id="mira",
        job_number=None, cost_code=None, po_number=None, line_items=[_line_item()],
    )
    h = payload["header"]
    assert h["tax_detail_id"] is None
    assert h["freight_amount"] == 0
    assert h["misc_amount"] == 0
    assert h["trade_discount"] == 0


def test_build_create_po_payload_maps_gp_charges_with_freight_from_shipping_cost():
    # issue #257: freight_amount is passed from the PO's shipping_cost at the call site; misc + trade
    # discount are the new register-form inputs; tax_detail_id drives the relay's tax computation.
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100", vendor_contact_name=None, buyer_id="mira",
        job_number=None, cost_code=None, po_number=None, line_items=[_line_item()],
        tax_detail_id="ON HST - P", freight_amount=25.0, misc_amount=5.0, trade_discount=2.0,
    )
    h = payload["header"]
    assert h["tax_detail_id"] == "ON HST - P"
    assert h["freight_amount"] == 25.0
    assert h["misc_amount"] == 5.0
    assert h["trade_discount"] == 2.0


def test_build_create_po_payload_job_cost_line_carries_job_and_cost_code():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number="1001",
        cost_code="310-000-3",
        po_number="ucnexus-42",
        line_items=[_line_item()],
    )
    assert payload["po_number"] == "ucnexus-42"
    # no vendor contact name - falls back to the buyer id
    assert payload["header"]["confirm_with"] == "mira"
    line = payload["lines"][0]
    assert line["product_indicator"] == 2
    assert line["job_number"] == "1001"
    assert line["cost_code"] == "310-000-3"


def test_build_create_po_payload_falls_back_to_product_code_without_order_as():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(order_as="")],
    )
    assert payload["lines"][0]["item_number"] == "AB123"


def test_build_create_po_payload_truncates_confirm_with_and_item_number():
    long_name = "A" * 50
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=long_name,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(order_as="B" * 50)],
    )
    assert payload["header"]["confirm_with"] == long_name[:20]
    assert payload["lines"][0]["item_number"] == ("B" * 50)[:30]


def test_build_create_receipt_payload_dedupes_and_joins_rack_locations():
    payload = gp_po.build_create_receipt_payload(
        po_number="PO0000001",
        received_by="Jane Doe",
        line_items=[
            {
                "gp_line_ord": 16384,
                "quantity": 5,
                "locations": [
                    {"aisle": "A1", "row": "B1", "bay": "C1"},
                    {"aisle": "A1", "row": "B1", "bay": "C1"},
                    {"aisle": "A2", "row": "B2", "bay": "C2"},
                ],
            }
        ],
    )
    assert payload["po_number"] == "PO0000001"
    assert payload["received_by"] == "Jane Doe"
    line = payload["lines"][0]
    assert line["po_line_ord"] == 16384
    assert line["quantity"] == 5
    assert line["rack_location"] == "A1-B1-C1, A2-B2-C2"


# --- validate_create_po_inputs: pre-relay field checks (issue #202 #1) --------------------------------


def test_validate_create_po_inputs_accepts_a_valid_non_job_po():
    gp_po.validate_create_po_inputs(job_number=None, cost_code=None, po_number=None, line_items=[_line_item()])


def test_validate_create_po_inputs_requires_a_cost_code_for_a_job_po():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(job_number="JC00102", cost_code=None, po_number=None, line_items=[_line_item()])
    assert exc.value.field == "cost_code"


def test_validate_create_po_inputs_rejects_an_overlong_po_number():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(job_number=None, cost_code=None, po_number="X" * 18, line_items=[_line_item()])
    assert exc.value.field == "po_number"


def test_validate_create_po_inputs_rejects_a_zero_quantity_line():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(
            job_number=None, cost_code=None, po_number=None, line_items=[_line_item(ordered_quantity=0)]
        )
    assert exc.value.field == "ordered_quantity"


def test_validate_create_po_inputs_rejects_empty_line_items():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(job_number=None, cost_code=None, po_number=None, line_items=[])
    assert exc.value.field == "line_items"
