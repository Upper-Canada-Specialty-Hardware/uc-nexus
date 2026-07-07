"""Builds relay job payloads for the create_po / create_receipt ops (issue #199: GP-first PO
create/register + receive, brokered server-side via relay_call instead of the browser).

The UC Nexus fields (vendor, buyer, job, cost code, line items) map onto POHeader/POLine/ReceiptLine
in localhost relay/src/ucnexus_relay/models.py - kept here as pure functions so createPo and
registerPoInGp (which both push a create_po job) share one mapping instead of drifting apart."""

from datetime import date

_LOCATION_CODE = "VANCOUVER"
_UOFM = "Each"
_MAX_CONFIRM_WITH = 20
_MAX_ITEM_NUMBER = 30
_MAX_ITEM_DESCRIPTION = 100
_MAX_RACK_LOCATION = 255


def build_create_po_payload(
    *,
    vendor_gp_id: str,
    vendor_contact_name: str | None,
    buyer_id: str,
    job_number: str | None,
    cost_code: str | None,
    po_number: str | None,
    line_items: list[dict],
) -> dict:
    """line_items: the same dicts create_po/register_po_in_gp build for the repository call, each
    with hardware_category, product_code, ordered_quantity, unit_cost, order_as. job_number present
    means every line is job-cost (product_indicator=2); absent means non-inventoried (1)."""
    is_job = job_number is not None
    confirm_with = (vendor_contact_name or buyer_id).strip()[:_MAX_CONFIRM_WITH]

    lines = []
    for li in line_items:
        product_code = li["product_code"].strip()
        order_as = (li.get("order_as") or "").strip()
        item_number = (order_as or product_code)[:_MAX_ITEM_NUMBER]
        item_description = f"{product_code} {li['hardware_category'].strip()}".strip()[:_MAX_ITEM_DESCRIPTION]
        lines.append(
            {
                "item_number": item_number,
                "item_description": item_description,
                "quantity": li["ordered_quantity"],
                "unit_cost": li["unit_cost"],
                "location_code": _LOCATION_CODE,
                "uofm": _UOFM,
                "product_indicator": 2 if is_job else 1,
                "job_number": job_number if is_job else None,
                "cost_code": cost_code if is_job else None,
            }
        )

    return {
        "header": {
            "vendor_id": vendor_gp_id,
            "buyer_id": buyer_id,
            "confirm_with": confirm_with,
            "doc_date": date.today().isoformat(),
        },
        "lines": lines,
        "po_number": po_number,
    }


def build_create_receipt_payload(
    *,
    po_number: str,
    received_by: str,
    line_items: list[dict],
) -> dict:
    """line_items: each with gp_line_ord, quantity, and locations (the same aisle/bay/bin dicts the
    createReceive input carries for the UC Nexus put-away) - rack_location composes the distinct bins
    a line's units were placed in, same convention the browser used to build it."""
    lines = []
    for li in line_items:
        racks: list[str] = []
        seen: set[str] = set()
        for loc in li["locations"]:
            key = f"{loc['aisle']}-{loc['bay']}-{loc['bin']}"
            if key not in seen:
                seen.add(key)
                racks.append(key)
        lines.append(
            {
                "po_line_ord": li["gp_line_ord"],
                "quantity": li["quantity"],
                "rack_location": ", ".join(racks)[:_MAX_RACK_LOCATION],
            }
        )

    return {
        "po_number": po_number,
        "lines": lines,
        "received_by": received_by,
    }
