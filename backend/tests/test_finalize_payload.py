"""The import wizard's finalize input, flattened for the repository.

This layer is only attribute reads, which is exactly why nothing tested it: every finalize test calls
`import_repository.finalize_import_session` directly with a hand-built dict, so the translation from
the Strawberry input was never executed by CI. It shipped reading three fields #554 had deleted
(`shop_assembly_openings`, and `item_type` / `opening_item_id` / `leaf` on the shipping draft items),
so EVERY finalize died on `'FinalizeImportSessionInput' object has no attribute
'shop_assembly_openings'` - for every purpose, with all four CI jobs green. Found by clicking the
wizard on a preview environment.

No database: constructing the input and reading the dict is the whole test, which is the point.
"""

import pytest

from app.schemas.imports import finalize_payload
from app.schemas.inputs import (
    FinalizeImportSessionInput,
    OpeningInput,
    SARItemInput,
    ShippingOutPRDraftInput,
    ShippingOutPRDraftItemInput,
)


def _opening(number="0001-EX"):
    return OpeningInput(opening_number=number)


def test_a_minimal_finalize_flattens_without_touching_a_missing_field():
    # The regression itself: this raised AttributeError before the fields were realigned, and it is
    # the shape the PO purpose sends - no assembly request, no shipping drafts.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()]),
        created_by_user_id="user_1",
    )
    assert payload["project_id"] == "p1"
    assert payload["created_by_user_id"] == "user_1"
    assert payload["shop_assembly_items"] is None
    assert payload["shipping_out_pr_drafts"] is None


def test_every_key_the_repository_reads_is_produced():
    # Guards the other direction: a field renamed on the input must not silently stop being sent.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()]),
        created_by_user_id="u",
    )
    for key in (
        "project_id",
        "openings",
        "hardware_items",
        "po_drafts",
        "classifications",
        "excluded_items",
        "shipping_out_pr_drafts",
        "include_shop_assembly_request",
        "shop_assembly_request_number",
        "shop_assembly_items",
        "replace_schedule",
        "schedule_filename",
        "created_by_user_id",
    ):
        assert key in payload, f"the repository reads {key} and finalize stopped sending it"


def test_a_dropped_field_is_not_resurrected():
    # #554 removed these from the input. If one comes back here it means the door-management shape is
    # creeping back into the wizard contract.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()]),
        created_by_user_id="u",
    )
    for gone in ("shop_assembly_openings", "acknowledge_incomplete_leaves"):
        assert gone not in payload


def test_shop_assembly_items_flatten_with_their_opening_tag():
    payload = finalize_payload(
        FinalizeImportSessionInput(
            project_id="p1",
            openings=[_opening()],
            include_shop_assembly_request=True,
            shop_assembly_items=[
                SARItemInput(
                    opening_number="0001-EX",
                    hardware_category="Hinges",
                    product_code="BB1279",
                    quantity=4,
                    allocated_quantity=3,
                ),
                # A line raised straight off inventory carries no opening.
                SARItemInput(opening_number=None, hardware_category="Locks", product_code="AD8406", quantity=1),
            ],
        ),
        created_by_user_id="u",
    )
    assert payload["shop_assembly_items"] == [
        {
            "opening_number": "0001-EX",
            "hardware_category": "Hinges",
            "product_code": "BB1279",
            "quantity": 4,
            "allocated_quantity": 3,
        },
        {
            "opening_number": None,
            "hardware_category": "Locks",
            "product_code": "AD8406",
            "quantity": 1,
            # None survives as None: the repository reads that as "fully allocated".
            "allocated_quantity": None,
        },
    ]


def test_shipping_drafts_carry_only_the_flat_line_shape():
    payload = finalize_payload(
        FinalizeImportSessionInput(
            project_id="p1",
            openings=[_opening()],
            shipping_out_pr_drafts=[
                ShippingOutPRDraftInput(
                    request_number="SO-1",
                    items=[
                        ShippingOutPRDraftItemInput(
                            opening_number="0001-EX",
                            hardware_category="Locks",
                            product_code="AD8406",
                            requested_quantity=2,
                        )
                    ],
                )
            ],
        ),
        created_by_user_id="u",
    )
    item = payload["shipping_out_pr_drafts"][0]["items"][0]
    assert item == {
        "opening_number": "0001-EX",
        "hardware_category": "Locks",
        "product_code": "AD8406",
        "requested_quantity": 2,
    }
    for gone in ("item_type", "opening_item_id", "leaf"):
        assert gone not in item


def test_schedule_filename_defaults_to_none_and_passes_through():
    # #627: absent on a hydrate finalize (the repository then leaves the stored name), and forwarded
    # verbatim when a fresh parse carried a file name.
    absent = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()]),
        created_by_user_id="u",
    )
    assert absent["schedule_filename"] is None

    present = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()], schedule_filename="contracterp-74.xml"),
        created_by_user_id="u",
    )
    assert present["schedule_filename"] == "contracterp-74.xml"


@pytest.mark.parametrize("field", ["shop_assembly_items", "shipping_out_pr_drafts"])
def test_empty_collections_send_none_rather_than_an_empty_list(field):
    # The repository treats None as "no request wanted"; an empty list would read as "a request with
    # no lines", which is a different thing and fails downstream.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()], **{field: []}),
        created_by_user_id="u",
    )
    assert payload[field] is None
