"""Builds relay job payloads for the create_po / create_receipt ops (issue #199: GP-first PO
create/register + receive, brokered server-side via relay_call instead of the browser).

The UC Nexus fields (vendor, buyer, job, cost code, line items) map onto POHeader/POLine/ReceiptLine
in relay/src/ucnexus_relay/models.py - kept here as pure functions so createPo and
registerPoInGp (which both push a create_po job) share one mapping instead of drifting apart."""

from datetime import date

from app.errors import ValidationError

_LOCATION_CODE = "VANCOUVER"
_UOFM = "Each"
# PAIRED EDIT: these GP column-width limits mirror the pydantic Field(max_length=...) on the relay's
# models.py (POLine.item_number=30 / item_description=100, POHeader.confirm_with=20, ReceiptLine.
# rack_location=255). They can't share a constant across the backend and relay packages, so if GP's
# column widths ever change, edit BOTH sides - changing one alone lets an over-length value pass here
# and get rejected as an opaque invalid_payload at the relay, or vice-versa.
_MAX_CONFIRM_WITH = 20
_MAX_ITEM_NUMBER = 30
_MAX_ITEM_DESCRIPTION = 100
_MAX_RACK_LOCATION = 255
# GP PONUMBER is char(17); the relay reserves GP's next number when none is supplied.
_MAX_PO_NUMBER = 17


def validate_create_po_inputs(
    *,
    job_number: str | None,
    cost_code: str | None,
    po_number: str | None,
    line_items: list[dict],
) -> None:
    """Field-level pre-checks for a create_po push, run BEFORE the relay round-trip so a bad request
    fails with a clean AppError instead of the relay's opaque invalid_payload (the pydantic models on
    the far side reject the same conditions, but only after the WS hop). The persist-side repository
    re-validates authoritatively; this only fronts the GP write."""
    if not line_items:
        raise ValidationError("At least one line item is required", field="line_items")

    if po_number is not None and po_number.strip():
        if len(po_number.strip()) > _MAX_PO_NUMBER:
            raise ValidationError(f"PO number must be at most {_MAX_PO_NUMBER} characters", field="po_number")

    is_job = job_number is not None
    if is_job and not (cost_code and cost_code.strip()):
        # a job-linked PO makes every line job-cost (product_indicator=2), which GP requires a cost code
        # for; without this the relay rejects the whole payload as invalid.
        raise ValidationError("A cost code is required for a project-linked PO", field="cost_code")

    for li in line_items:
        if not (li.get("order_as") or "").strip() and not (li.get("product_code") or "").strip():
            raise ValidationError("Order as is required for every line item", field="order_as")
        qty = li.get("ordered_quantity")
        if qty is None or qty < 1:
            raise ValidationError("Ordered quantity must be at least 1", field="ordered_quantity")
        unit_cost = li.get("unit_cost")
        if unit_cost is not None and unit_cost < 0:
            raise ValidationError("Unit cost must be zero or greater", field="unit_cost")


def build_create_po_payload(
    *,
    vendor_gp_id: str,
    vendor_contact_name: str | None,
    buyer_id: str,
    job_number: str | None,
    cost_code: str | None,
    po_number: str | None,
    line_items: list[dict],
    po_number_suffix: str | None = None,
    tax_detail_id: str | None = None,
    freight_amount: float | None = None,
    misc_amount: float | None = None,
    trade_discount: float | None = None,
) -> dict:
    """line_items: the same dicts create_po/register_po_in_gp build for the repository call, each
    with hardware_category, product_code, ordered_quantity, unit_cost, order_as. job_number present
    means every line is job-cost (product_indicator=2); absent means non-inventoried (1).

    Issue #257 GP header charges: tax_detail_id is the GP purchase tax detail the relay computes tax
    from (CAD only; the relay resolves currency from the vendor). freight_amount maps from the PO's
    shipping_cost, misc_amount + trade_discount are the new register-form inputs. None -> 0 (the relay
    POHeader charge fields are non-null Decimals)."""
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
            # Issue #257: GP header charges. None -> 0 for the non-null relay Decimals; tax_detail_id
            # stays None when no detail was picked (relay then writes no tax).
            "tax_detail_id": tax_detail_id,
            "freight_amount": freight_amount or 0,
            "misc_amount": misc_amount or 0,
            "trade_discount": trade_discount or 0,
        },
        "lines": lines,
        "po_number": po_number,
        # #488: the relay composes '<reserved>-<suffix>' when it reserves the number itself. Ignored
        # when po_number is explicit, which is taken as given.
        "po_number_suffix": po_number_suffix,
    }


def build_create_receipt_payload(
    *,
    po_number: str,
    received_by: str,
    line_items: list[dict],
    warehouse_code: str | None = None,
) -> dict:
    """line_items: each with gp_line_ord, quantity, and locations (the same aisle/row/bay dicts the
    createReceive input carries for the UC Nexus put-away) - rack_location composes the distinct
    locations a line's units were placed in, same convention the browser used to build it.

    Since #501 put-away happens AFTER the warehouse manager approves, so a line usually reaches this
    point with no locations at all. `warehouse_code` is what GP gets told instead: the building the
    units are in, which is true at receipt time and is the most specific thing anybody knows yet.
    Sending an empty rack_location would lose even that. Lines that DO carry locations - drafts
    counted before #501 shipped - still compose the bins.
    """
    lines = []
    for li in line_items:
        racks: list[str] = []
        seen: set[str] = set()
        for loc in li["locations"]:
            key = f"{loc['aisle']}-{loc['row']}-{loc['bay']}"
            if key not in seen:
                seen.add(key)
                racks.append(key)
        rack_location = ", ".join(racks) if racks else (warehouse_code or "")
        lines.append(
            {
                "po_line_ord": li["gp_line_ord"],
                "quantity": li["quantity"],
                "rack_location": rack_location[:_MAX_RACK_LOCATION],
            }
        )

    return {
        "po_number": po_number,
        "lines": lines,
        "received_by": received_by,
    }
