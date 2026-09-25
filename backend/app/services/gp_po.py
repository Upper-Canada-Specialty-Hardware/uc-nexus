"""Builds relay job payloads for the create_po / create_receipt ops (issue #199: GP-first PO
create/register + receive, brokered server-side via relay_call instead of the browser).

The UC Nexus fields (vendor, buyer, job, cost code, line items) map onto POHeader/POLine/ReceiptLine
in relay/src/ucnexus_relay/models.py - kept here as pure functions so createPo and
registerPoInGp (which both push a create_po job) share one mapping instead of drifting apart."""

import logging
from datetime import date

from app.errors import ValidationError

logger = logging.getLogger(__name__)

_SHIPPING_METHOD = "LOCAL DELIVERY"
_VENDOR_ADDRESS_CODE = "PRIMARY"
_UOFM = "Each"
# PAIRED EDIT: these GP column-width limits mirror the pydantic Field(max_length=...) on the relay's
# models.py (POLine.item_number=30 / item_description=100 / uofm=9, POHeader.confirm_with=20 /
# contact=61 / comment=500, ReceiptLine.rack_location=255). They can't share a constant across the
# backend and relay packages, so if GP's column widths ever change, edit BOTH sides - changing one
# alone lets an over-length value pass here and get rejected as an opaque invalid_payload at the
# relay, or vice-versa.
_MAX_CONFIRM_WITH = 20
_MAX_CONTACT = 61
_MAX_COMMENT = 500
_MAX_ITEM_NUMBER = 30
_MAX_ITEM_DESCRIPTION = 100
_MAX_UOFM = 9
_MAX_RACK_LOCATION = 255
# GP PONUMBER is char(17); the relay reserves GP's next number when none is supplied.
_MAX_PO_NUMBER = 17


def line_is_job_cost(li: dict, *, has_project: bool) -> bool:
    """Whether one line books to the job. The input's own answer wins; null means "job-cost when this
    PO has a project", which is the rule every registration applied before the flag existed."""
    explicit = li.get("job_cost")
    return has_project if explicit is None else bool(explicit)


def line_uofm(li: dict) -> str:
    """The line's unit of measure. Null or blank is 'Each', which is what GP has been sent all along."""
    return (li.get("uofm") or "").strip() or _UOFM


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

    has_project = job_number is not None

    for li in line_items:
        # Both halves of the line's GP identity are required: hardware_category becomes GP's item
        # number and product_code its description. Order As is the one optional field and reaches GP
        # not at all.
        if not (li.get("hardware_category") or "").strip():
            raise ValidationError("Hardware category is required for every line item", field="hardware_category")
        if not (li.get("product_code") or "").strip():
            raise ValidationError("Product code is required for every line item", field="product_code")
        qty = li.get("ordered_quantity")
        if qty is None or qty < 1:
            raise ValidationError("Ordered quantity must be at least 1", field="ordered_quantity")
        unit_cost = li.get("unit_cost")
        if unit_cost is not None and unit_cost < 0:
            raise ValidationError("Unit cost must be zero or greater", field="unit_cost")
        if len(line_uofm(li)) > _MAX_UOFM:
            raise ValidationError(f"Unit of measure must be at most {_MAX_UOFM} characters", field="uofm")
        if line_is_job_cost(li, has_project=has_project):
            if not has_project:
                # GP books a job-cost line against a job number, and this PO has none to give it.
                raise ValidationError("A purchase order with no project cannot have a job-cost line", field="job_cost")
            line_cost_code = (li.get("cost_code") or "").strip() or (cost_code or "").strip()
            if not line_cost_code:
                # GP requires a cost code on a job-cost line (product_indicator 2); without this the
                # relay rejects the whole payload as invalid.
                raise ValidationError("A cost code is required for every job-cost line", field="cost_code")


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
    idempotency_key: str | None = None,
    tax_detail_ids: list[str] | None = None,
    tax_schedule_id: str | None = None,
    freight_amount: float | None = None,
    misc_amount: float | None = None,
    trade_discount: float | None = None,
    shipping_method: str | None = None,
    vendor_address_code: str | None = None,
    site: str | None = None,
    doc_date: date | None = None,
    contact: str | None = None,
    comment: str | None = None,
) -> dict:
    """line_items: the same dicts create_po/register_po_in_gp build for the repository call, each with
    hardware_category, product_code, ordered_quantity, unit_cost, order_as, and the three fields GP
    takes per line - cost_code, uofm and job_cost. A job-cost line is GP's product_indicator 2 and
    carries the job number and a cost code; every other line is non-inventoried (1) and carries
    neither. A null job_cost on a line means "job-cost when this PO has a project".

    The GP PO LINE ITEM identity a PO REGISTRATION writes: item number is the schedule's hardware
    category, item description is its product code. Order As is Nexus-only and is never sent to GP,
    so nothing in the payload reads it. GP's item number is 30 characters and its description 100, so
    an over-long category is truncated (and logged) rather than refused - a PO must never fail to
    register over the width of a label.

    Issue #257 / #762 GP header charges: tax_detail_ids are the GP purchase tax details the relay
    computes tax from - per line per detail, on freight and misc too, net of the trade discount - the
    way GP's own PO entry does (CAD only; the relay resolves currency from the vendor). Sent as a
    list under the key a #762 relay reads; an older relay ignores that key, which is why the resolver
    only pushes a taxed registration to a relay advertising CREATE_PO_TAX_ROWS_FEATURE. freight_amount
    maps from the PO's shipping_cost, misc_amount + trade_discount are the register-form inputs.
    None -> 0 (the relay POHeader charge fields are non-null Decimals).

    The rest of the header is what GP's Purchase Order Entry takes: the shipping method, the vendor's
    purchase address code, the site every line is stocked at, the document date, the contact, and the
    comment. The shipping method and the vendor address code default to what every registration has
    sent so far, and the contact is sent only when the form actually set one - see the header below.
    The site has no default: it has to be one of the sites the company's own GP holds (IV40700), so a
    PO REGISTRATION that names none is refused here rather than by the relay."""
    has_project = job_number is not None
    header_site = (site or "").strip()
    if not header_site:
        raise ValidationError("A GP site is required to register a PO", field="site")
    header_cost_code = (cost_code or "").strip() or None
    # GP's Confirm With is the person at the vendor this PO was placed with. The register form sends
    # the vendor's own contact as its default; with neither that nor an explicit value, the buyer id
    # is the only name anybody has.
    confirm_with = (contact or vendor_contact_name or buyer_id).strip()[:_MAX_CONFIRM_WITH]

    lines = []
    for li in line_items:
        product_code = li["product_code"].strip()
        hardware_category = li["hardware_category"].strip()
        item_number = hardware_category[:_MAX_ITEM_NUMBER]
        if len(hardware_category) > _MAX_ITEM_NUMBER:
            logger.info(
                "create_po payload: hardware category %r cut to %s characters for GP's item number",
                hardware_category,
                _MAX_ITEM_NUMBER,
            )
        item_description = product_code[:_MAX_ITEM_DESCRIPTION]
        is_job_line = line_is_job_cost(li, has_project=has_project)
        line_cost_code = (li.get("cost_code") or "").strip() or header_cost_code
        lines.append(
            {
                "item_number": item_number,
                "item_description": item_description,
                "quantity": li["ordered_quantity"],
                "unit_cost": li["unit_cost"],
                "location_code": header_site,
                "uofm": line_uofm(li),
                "product_indicator": 2 if (is_job_line and has_project) else 1,
                "job_number": job_number if (is_job_line and has_project) else None,
                "cost_code": line_cost_code if (is_job_line and has_project) else None,
            }
        )

    return {
        "header": {
            "vendor_id": vendor_gp_id,
            "buyer_id": buyer_id,
            "confirm_with": confirm_with,
            "doc_date": (doc_date or date.today()).isoformat(),
            # Issue #257 / #762: GP header charges. None -> 0 for the non-null relay Decimals; an empty
            # detail list is a PO with no tax (the relay then writes no tax row at all).
            "tax_detail_ids": list(tax_detail_ids or []),
            # #763: the picked GP purchase tax schedule, which the relay expands to its details. Only
            # sent when there is one, so an untaxed registration still suits a relay that predates it.
            **({"tax_schedule_id": tax_schedule_id} if tax_schedule_id else {}),
            "freight_amount": freight_amount or 0,
            "misc_amount": misc_amount or 0,
            "trade_discount": trade_discount or 0,
            "shipping_method": (shipping_method or "").strip() or _SHIPPING_METHOD,
            "vendor_address_code": (vendor_address_code or "").strip() or _VENDOR_ADDRESS_CODE,
            # The site every line without one of its own is stocked at.
            "site": header_site,
            # The EXPLICIT contact only, and null when the form sent none. The relay leaves the GP
            # parameter out altogether for a null, and that parameter's name is not verified on the
            # workstation yet - so a wrong name can only ever fail a PO that actually set a contact,
            # never one that did not. Confirm With, which is verified, still falls back.
            "contact": (contact or "").strip()[:_MAX_CONTACT] or None,
            "comment": (comment or "").strip()[:_MAX_COMMENT] or None,
        },
        "lines": lines,
        "po_number": po_number,
        # #488: the relay composes '<reserved>-<suffix>' when it reserves the number itself. Ignored
        # when po_number is explicit, which is taken as given.
        "po_number_suffix": po_number_suffix,
        # The attempt's key, which the relay stamps on the PO it creates in GP so the same key coming
        # back returns that PO instead of reserving a second number. It lives in the payload rather
        # than beside it because a queued write replays the STORED payload: the key rides along on
        # every retry the outbox makes, with nothing to re-derive.
        "idempotency_key": idempotency_key,
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
