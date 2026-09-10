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
    # The PO REGISTRATION identity: hardware category into GP's item number, product code into its
    # description. Order As stays in Nexus and reaches neither field.
    assert line["item_number"] == "HINGE"
    assert line["item_description"] == "AB123"
    assert line["quantity"] == 2
    assert line["unit_cost"] == 12.5
    assert line["product_indicator"] == 1
    assert line["job_number"] is None
    assert line["cost_code"] is None


def test_build_create_po_payload_defaults_gp_charges_to_zero_without_tax_detail():
    # issue #257: with no charges/tax passed, the header carries the zeroed GP charge fields (the
    # relay POHeader Decimals are non-null) and a null tax detail (relay writes no tax).
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
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
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
        tax_detail_id="ON HST - P",
        freight_amount=25.0,
        misc_amount=5.0,
        trade_discount=2.0,
    )
    h = payload["header"]
    assert h["tax_detail_id"] == "ON HST - P"
    assert h["freight_amount"] == 25.0
    assert h["misc_amount"] == 5.0
    assert h["trade_discount"] == 2.0


def test_build_create_po_payload_header_defaults_match_what_gp_entry_expects():
    """Every header field the register form can leave blank has one answer, and these are they."""
    from datetime import date

    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
    )
    h = payload["header"]
    assert h["shipping_method"] == "LOCAL DELIVERY"
    assert h["vendor_address_code"] == "PRIMARY"
    assert h["site"] == "VANCOUVER"
    assert h["doc_date"] == date.today().isoformat()
    # The form set no contact, so none is sent - the relay then leaves the GP parameter out entirely.
    assert h["contact"] is None
    # Confirm With still falls back, because that field is verified in GP.
    assert h["confirm_with"] == "mira"
    assert h["comment"] is None
    # And the site is what every line without one of its own is stocked at.
    assert payload["lines"][0]["location_code"] == "VANCOUVER"


def test_build_create_po_payload_carries_the_header_the_form_sent():
    from datetime import date

    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
        shipping_method="PICKUP",
        vendor_address_code="WAREHOUSE",
        site="TORONTO",
        doc_date=date(2026, 3, 4),
        contact="Jane Vendor",
        comment="Split shipment - call before delivery",
    )
    h = payload["header"]
    assert h["shipping_method"] == "PICKUP"
    assert h["vendor_address_code"] == "WAREHOUSE"
    assert h["site"] == "TORONTO"
    assert h["doc_date"] == "2026-03-04"
    assert h["contact"] == "Jane Vendor"
    assert h["comment"] == "Split shipment - call before delivery"
    assert payload["lines"][0]["location_code"] == "TORONTO"


def test_the_vendors_own_contact_names_confirm_with_but_is_not_sent_as_the_contact():
    """Only what the form explicitly set reaches GP's contact parameter."""
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name="Jane Vendor",
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
    )
    assert payload["header"]["contact"] is None
    assert payload["header"]["confirm_with"] == "Jane Vendor"


def test_a_long_contact_and_comment_are_cut_to_gps_widths():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item()],
        contact="C" * 100,
        comment="M" * 600,
    )
    assert payload["header"]["contact"] == "C" * 61
    assert payload["header"]["comment"] == "M" * 500
    # confirm_with is a narrower GP column and keeps its own cut.
    assert payload["header"]["confirm_with"] == "C" * 20


def test_the_register_path_sends_no_po_number_suffix():
    """GP's own number is already unique; the project suffix made a Nexus-registered PO's number look
    unlike every other number in the company. The relay still accepts one, so nothing on the
    workstation had to change."""
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number="1001",
        cost_code="310-000-3",
        po_number=None,
        line_items=[_line_item()],
    )
    assert payload["po_number_suffix"] is None


def test_each_line_carries_its_own_cost_code_and_unit_of_measure():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number="1001",
        cost_code="310-000-3",
        po_number=None,
        line_items=[
            _line_item(cost_code="210-200-2", uofm="Box"),
            _line_item(),  # neither, so the PO's cost code and Each
        ],
    )
    first, second = payload["lines"]
    assert (first["cost_code"], first["uofm"]) == ("210-200-2", "Box")
    assert (second["cost_code"], second["uofm"]) == ("310-000-3", "Each")


def test_a_line_marked_not_job_cost_is_non_inventoried_even_on_a_job_po():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number="1001",
        cost_code="310-000-3",
        po_number=None,
        line_items=[_line_item(job_cost=False), _line_item()],
    )
    plain, job = payload["lines"]
    assert plain["product_indicator"] == 1
    assert plain["job_number"] is None
    assert plain["cost_code"] is None
    # Its neighbour, which said nothing, still takes the PO's answer.
    assert job["product_indicator"] == 2
    assert job["job_number"] == "1001"


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


def test_order_as_never_reaches_gp_whatever_it_holds():
    """Order As is Nexus-only. Setting it, blanking it or dropping the key entirely produces the
    same GP line - the category and the code are the only two values that travel."""
    for line_item in (_line_item(), _line_item(order_as=""), _line_item(order_as=None)):
        payload = gp_po.build_create_po_payload(
            vendor_gp_id="ING100",
            vendor_contact_name=None,
            buyer_id="mira",
            job_number=None,
            cost_code=None,
            po_number=None,
            line_items=[line_item],
        )
        assert payload["lines"][0]["item_number"] == "HINGE"
        assert payload["lines"][0]["item_description"] == "AB123"


def test_build_create_po_payload_trims_the_category_and_the_code():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(hardware_category="  HINGE  ", product_code="  AB123  ")],
    )
    assert payload["lines"][0]["item_number"] == "HINGE"
    assert payload["lines"][0]["item_description"] == "AB123"


def test_build_create_po_payload_truncates_confirm_with_and_item_number():
    long_name = "A" * 50
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=long_name,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(hardware_category="B" * 50)],
    )
    assert payload["header"]["confirm_with"] == long_name[:20]
    # GP's ITEMNMBR is 30 characters. An over-long category is cut, never a reason to refuse the PO.
    assert payload["lines"][0]["item_number"] == ("B" * 50)[:30]


def test_an_over_long_product_code_is_cut_to_gps_description_width():
    payload = gp_po.build_create_po_payload(
        vendor_gp_id="ING100",
        vendor_contact_name=None,
        buyer_id="mira",
        job_number=None,
        cost_code=None,
        po_number=None,
        line_items=[_line_item(product_code="C" * 150)],
    )
    assert payload["lines"][0]["item_description"] == ("C" * 150)[:100]


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


def test_a_line_with_no_locations_tells_gp_the_warehouse():
    """#501: put-away happens after approval, so a line normally reaches GP with no bin yet. The
    warehouse is true at receipt time and is the most specific thing anybody knows - an empty
    rack_location would throw even that away."""
    payload = gp_po.build_create_receipt_payload(
        po_number="PO0000001",
        received_by="Jane Doe",
        line_items=[{"gp_line_ord": 16384, "quantity": 5, "locations": []}],
        warehouse_code="MAIN",
    )
    assert payload["lines"][0]["rack_location"] == "MAIN"


def test_a_legacy_draft_that_still_carries_bins_keeps_composing_them():
    """Drafts counted before #501 shipped still have rack rows; those win over the warehouse."""
    payload = gp_po.build_create_receipt_payload(
        po_number="PO0000001",
        received_by="Jane Doe",
        line_items=[{"gp_line_ord": 16384, "quantity": 5, "locations": [{"aisle": "A1", "row": "B1", "bay": "C1"}]}],
        warehouse_code="MAIN",
    )
    assert payload["lines"][0]["rack_location"] == "A1-B1-C1"


def test_no_locations_and_no_warehouse_sends_an_empty_rack_location():
    payload = gp_po.build_create_receipt_payload(
        po_number="PO0000001",
        received_by="Jane Doe",
        line_items=[{"gp_line_ord": 16384, "quantity": 5, "locations": []}],
    )
    assert payload["lines"][0]["rack_location"] == ""


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


def test_validate_create_po_inputs_rejects_a_blank_hardware_category():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(
            job_number=None, cost_code=None, po_number=None, line_items=[_line_item(hardware_category="  ")]
        )
    assert exc.value.field == "hardware_category"


def test_validate_create_po_inputs_rejects_a_blank_product_code_even_with_an_order_as():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(
            job_number=None,
            cost_code=None,
            po_number=None,
            line_items=[_line_item(product_code="", order_as="ML2010")],
        )
    assert exc.value.field == "product_code"


def test_validate_create_po_inputs_accepts_a_line_with_no_order_as():
    """Order As is the one optional field on a line."""
    gp_po.validate_create_po_inputs(
        job_number=None, cost_code=None, po_number=None, line_items=[_line_item(order_as=None)]
    )


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


def test_validate_create_po_inputs_accepts_a_job_po_whose_line_brings_its_own_cost_code():
    """The PO's code is only the fallback; a line that names one satisfies GP on its own."""
    gp_po.validate_create_po_inputs(
        job_number="1001", cost_code=None, po_number=None, line_items=[_line_item(cost_code="210-200-2")]
    )


def test_validate_create_po_inputs_rejects_a_job_cost_line_on_a_po_with_no_project():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(
            job_number=None, cost_code="210-200-2", po_number=None, line_items=[_line_item(job_cost=True)]
        )
    assert exc.value.field == "job_cost"


def test_validate_create_po_inputs_accepts_a_non_job_line_on_a_job_po_without_a_cost_code():
    gp_po.validate_create_po_inputs(
        job_number="1001", cost_code=None, po_number=None, line_items=[_line_item(job_cost=False)]
    )


def test_validate_create_po_inputs_rejects_an_overlong_unit_of_measure():
    import pytest

    from app.errors import ValidationError

    with pytest.raises(ValidationError) as exc:
        gp_po.validate_create_po_inputs(
            job_number=None, cost_code=None, po_number=None, line_items=[_line_item(uofm="Kilogrammes")]
        )
    assert exc.value.field == "uofm"
