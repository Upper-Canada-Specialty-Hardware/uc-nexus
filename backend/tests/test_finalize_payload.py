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

import contextlib

import pytest

from app.schemas.imports import finalize_payload
from app.schemas.inputs import (
    FinalizeImportSessionInput,
    OpeningInput,
    PODraftInput,
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
                SARItemInput(opening_number="0002-EX", hardware_category="Locks", product_code="AD8406", quantity=1),
            ],
        ),
        created_by_user_id="u",
    )
    # `allocated_quantity` still round-trips so a pre-#646 tab's payload maps unchanged; the
    # repository ignores it, because nothing is allocated until a batch says so.
    assert payload["shop_assembly_items"] == [
        {
            "opening_number": "0001-EX",
            "hardware_category": "Hinges",
            "product_code": "BB1279",
            "quantity": 4,
            "allocated_quantity": 3,
        },
        {
            "opening_number": "0002-EX",
            "hardware_category": "Locks",
            "product_code": "AD8406",
            "quantity": 1,
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


def test_a_po_drafts_vendor_label_is_forwarded_to_the_repository():
    # #632: the wizard's per-draft vendor label seeds vendor_name_snapshot on the created DRAFT PO.
    # A field the repository reads but finalize stops sending is the exact failure this file exists for.
    payload = finalize_payload(
        FinalizeImportSessionInput(
            project_id="p1",
            openings=[_opening()],
            po_drafts=[PODraftInput(po_number="PO-1", vendor_name="Allegion")],
        ),
        created_by_user_id="u",
    )
    assert payload["po_drafts"][0]["vendor_name"] == "Allegion"


def test_a_po_drafts_vendor_quote_number_is_forwarded_to_the_repository():
    # #737: the step 5 draft card's quote number, written onto the created PO.
    payload = finalize_payload(
        FinalizeImportSessionInput(
            project_id="p1",
            openings=[_opening()],
            po_drafts=[PODraftInput(po_number="PO-1", vendor_quote_number="Q-2231")],
        ),
        created_by_user_id="u",
    )
    assert payload["po_drafts"][0]["vendor_quote_number"] == "Q-2231"


def test_a_po_draft_with_no_vendor_label_still_flattens():
    # Optional: the wizard can raise a request before anybody has decided who it is going to.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()], po_drafts=[PODraftInput(po_number="PO-1")]),
        created_by_user_id="u",
    )
    assert payload["po_drafts"][0]["vendor_name"] is None


@pytest.mark.parametrize("field", ["shop_assembly_items", "shipping_out_pr_drafts"])
def test_empty_collections_send_none_rather_than_an_empty_list(field):
    # The repository treats None as "no request wanted"; an empty list would read as "a request with
    # no lines", which is a different thing and fails downstream.
    payload = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()], **{field: []}),
        created_by_user_id="u",
    )
    assert payload[field] is None


def test_excluded_items_keep_null_apart_from_an_explicit_empty_list():
    # #1412: unlike the request collections above, [] is a real answer here - a PO import where every
    # By Others product went back to UCSH clears the exclusions - while null (every other purpose)
    # leaves them alone. Folding both into None kept a cleared list from clearing anything.
    absent = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()]),
        created_by_user_id="u",
    )
    assert absent["excluded_items"] is None

    empty = finalize_payload(
        FinalizeImportSessionInput(project_id="p1", openings=[_opening()], excluded_items=[]),
        created_by_user_id="u",
    )
    assert empty["excluded_items"] == []


class _StopAfterFinalize(Exception):
    pass


def test_the_resolver_names_the_signed_in_person_as_the_requester(monkeypatch):
    # #859: a shop-assembly request raised from the wizard read "by Hardware Schedule Import". The
    # resolver resolves the caller's display name and hands it to finalize as `created_by`.
    from app.schemas import imports as imports_schema

    captured = {}

    def fake_finalize(session, input_data, *, created_by):
        captured["created_by"] = created_by
        captured["created_by_user_id"] = input_data["created_by_user_id"]
        raise _StopAfterFinalize

    monkeypatch.setattr(imports_schema, "current_user", lambda info: {"user_id": "user_1"})
    monkeypatch.setattr(imports_schema, "resolve_display_name", lambda user_id: "Dana Planner")
    monkeypatch.setattr(imports_schema, "tenant_scope", lambda info: None)
    monkeypatch.setattr(imports_schema.tenancy, "require_project_in_scope", lambda *a, **k: None)
    monkeypatch.setattr(imports_schema, "SessionLocal", lambda: contextlib.nullcontext(object()))
    monkeypatch.setattr(imports_schema.import_repository, "finalize_import_session", fake_finalize)

    with pytest.raises(_StopAfterFinalize):
        imports_schema.ImportMutations().finalize_import_session(
            None,
            FinalizeImportSessionInput(project_id="00000000-0000-0000-0000-000000000001", openings=[_opening()]),
        )

    assert captured == {"created_by": "Dana Planner", "created_by_user_id": "user_1"}
