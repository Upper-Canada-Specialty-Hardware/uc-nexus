"""Fixture-backed op handlers: the same op set channel._OPS serves, answered out of a checked-in JSON
snapshot of the TUBC / TUCSH sandbox companies instead of out of GP over ODBC.

This exists so a Railway preview environment can exercise every relay-dependent path without a
workstation dialling it. The relay runs as a Linux container, `[gp] mode = "fixture"` swaps this
registry in (channel.ops_registry), and no pyodbc, no ODBC driver and no GP are involved at all. The
workstation relay is untouched - it never imports this module.

Every handler returns EXACTLY what the matching `_run_*` wrapper in channel.py returns, built through
the same models.py response models where the wrapper builds one, and raises ops.RelayOpError with the
same error codes ops.py raises, because the backend branches on those codes (job_already_exists in
schemas/project.py, buyer_already_exists and address_code_already_exists in the frontend dialogs).

WRITES LIVE IN MEMORY, for the life of the process. create_po reserves the next number out of the
snapshot's own counter, appends the PO, and read_po_totals / sync_pos then see it; create_receipt
records against that PO and moves its received quantities. Nothing is written back to disk, so a
container restart is a clean company again. reset_state() is how a test gets the same.

snapshot format
{
  "format": "ucnexus-relay-gp-snapshot",
  "version": 1,
  "captured_at": "<iso8601>",
  "companies": {
    "TUBC": {
      "name": "TUBC",   # SY01500.CMPNYNAM, written by `capture` when GP answers. OPTIONAL - company
                        # discovery (companies.py) falls back to the code, as shown here, when absent
      "mc_setup": {"functional": "CAD", "purchase_rate_type": "AVERAGE"},   # MC40000
      "exchange_rates": [{"currency": "USD", "rate_type": "AVERAGE"}],      # what has_exchange_rate probes
      "next_numbers": {"po": "PO0000101", "receipt": "RCT0000042"},         # POP40100 / the receipt counter
      "account_indexes": [1200, ...],       # GL00105 ACTINDX. A cost code pointing outside it dangles (#425)
      "vendors": [{vendor_id, vendor_name, vendor_class, status, currency, contact_name, email}],
      "buyers": [{buyer_id, description}],
      "tax_details": [{tax_detail_id, description, percent}],
      "tax_schedules": [{tax_schedule_id, description}],
      "divisions": ["VANCOUVER"],
      "employees": [{employee_id, first_name, last_name, inactive}],
      "customers": [{customer_number, customer_name, inactive,
                     addresses: [{address_code, address1, address2, city, state, zip_code, country}]}],
      "cost_code_master": [{cost_code, cost_code_number_1, cost_code_number_2, alias, description,
                            cost_element, profit_type_number, type_of_transaction}],   # JC40202
      "division_accounts": {"VANCOUVER": {"2": 1200, ...}},                            # JC40302
      "jobs": [{job_number, job_name, customer_number, job_address_code, division,
                cost_codes: [{cost_code, cost_element, description, account_index, inactive}]}],
      "purchase_orders": [{po_number, gp_status, vendor_id, vendor_name, doc_date, modified_at,
                           source_table, totals: {subtotal, freight, miscellaneous, tax_amount},
                           lines: [{ord, item, itemdesc, unit_cost, qty, qty_cancelled, job,
                                    line_status, received, account_index}]}],
      "receipts": []
    }
  }
}

Two modelling notes on that shape:

`account_indexes` is GL00105, and it is what makes #425 expressible: a job cost code whose
account_index is non-zero and absent from it is a dangling code - hidden from list_cost_codes,
reported as an issue by job_setup_health, refused by create_po's cost_code_account_invalid guard and
by create_receipt's po_line_account_invalid guard, exactly as in GP. Index 0 always passes ("GP picks
the account at posting time"). A snapshot written by `ucnexus-relay capture` (capture.py) carries the
derived split rather than GL00105 itself: usable job cost codes come back as index 0 and only the
codes GP already reports as broken keep their real dangling index, which reproduces the same
behaviour without a read of the account master.

`division_accounts` is JC40302, the (division, cost element) -> account index mapping that decides
what a cost code from the master would be provisioned WITH. An element with no entry is unmapped, and
list_cost_code_master reports it mapped=false rather than hiding it, as GP's own read does.

One error code here has no counterpart in ops.py: `customer_not_found`, answered when an address is
requested under a customer the snapshot does not hold. GP answers that with a raw eConnect state from
taCreateCustomerAddress, and an eConnect error cannot be reproduced honestly without a connection to
resolve its description against - so it is named rather than faked.
"""

import json
import re
import socket
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from . import buyers as buyers_config
from . import models, ops
from .config import DEFAULT_FIXTURE_PATH, get_settings

SNAPSHOT_FORMAT = "ucnexus-relay-gp-snapshot"
SNAPSHOT_VERSION = 1

# POP10100.POSTATUS 1 = New, and POP10110.POLNESTA 1 = New - what a PO and its lines look like the
# moment GP has them. create_receipt refuses a line at 4 or above (closed / cancelled), as GP does.
_NEW_PO_STATUS = 1
_NEW_LINE_STATUS = 1
# GP spaces receipt line numbers the same way it spaces PO line ordinals.
_RECEIPT_LINE_STEP = 16384
# econnect.sync_pos' own ceiling on a page.
_MAX_PO_PAGE_SIZE = 1000

_NUMBER = re.compile(r"^([A-Za-z]*)(\d+)$")

_state: dict | None = None
_state_path: str | None = None


def snapshot_path() -> Path:
    """The snapshot this relay serves: [gp] fixture_path, else the one bundled with the tree."""
    configured = get_settings().gp.fixture_path
    return Path(configured) if configured else DEFAULT_FIXTURE_PATH


def load_state(path: str | Path | None = None) -> dict:
    """The in-memory snapshot, read from disk on first use and mutated in place by the write ops."""
    global _state, _state_path
    resolved = str(Path(path) if path else snapshot_path())
    if _state is None or _state_path != resolved:
        with open(resolved, "rb") as f:
            _state = json.load(f)
        _state_path = resolved
    return _state


def reset_state() -> None:
    """Forget every in-memory write, so the next op reloads the checked-in snapshot."""
    global _state, _state_path
    _state = None
    _state_path = None


def _company(name: str) -> dict:
    """The snapshot's record for one company.

    check_company_served still runs first: discovery in fixture mode reads the snapshot's own company
    keys, so the served set and the snapshot agree by construction. A company that somehow passes that
    gate but is not in the snapshot gets the same company_not_allowed answer - there is nothing here to
    serve it from either way, and the caller's question ("can this relay reach that company") has one
    answer."""
    ops.check_company_served(name)
    companies = load_state().get("companies") or {}
    data = companies.get(name)
    if data is None:
        held = ", ".join(sorted(companies)) or "no companies"
        raise ops.RelayOpError(
            "company_not_allowed", f"{name} is not in the fixture snapshot (it holds {held})"
        )
    return data


def _find(rows: list[dict], key: str, value) -> dict | None:
    """First row whose `key` matches `value`, compared the way GP's default collation compares: case
    insensitively and ignoring the trailing spaces of a char column."""
    target = str(value or "").strip().casefold()
    for row in rows:
        if str(row.get(key) or "").strip().casefold() == target:
            return row
    return None


def _account_indexes(company: dict) -> set[int]:
    return {int(i) for i in company.get("account_indexes") or []}


def _usable_account(entry: dict, indexes: set[int]) -> bool:
    """account_index_exists' rule: 0 is 'GP picks the account at posting time', anything else has to be
    a real GL00105 row."""
    index = int(entry.get("account_index") or 0)
    return index == 0 or index in indexes


def _active_cost_codes(job: dict) -> list[dict]:
    return [c for c in job.get("cost_codes") or [] if not c.get("inactive")]


def _find_job(company: dict, job_number: str) -> dict | None:
    return _find(company.get("jobs") or [], "job_number", job_number)


def _find_po(company: dict, po_number: str) -> dict | None:
    return _find(company.get("purchase_orders") or [], "po_number", po_number)


def _naive(value: str | None) -> datetime | None:
    """A snapshot timestamp as a naive datetime. DEX_ROW_TS carries no zone and the backend's watermark
    is sent as a naive isoformat string, so anything carrying one is flattened rather than compared
    against a naive value and raising."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=None)


def next_number(current: str) -> str:
    """The number after `current`, keeping its prefix and digit width ('PO0000101' -> 'PO0000102')."""
    match = _NUMBER.match((current or "").strip())
    if match is None:
        return current
    prefix, digits = match.groups()
    return f"{prefix}{int(digits) + 1:0{len(digits)}d}"


def _reserve(company: dict, key: str, fallback: str) -> str:
    """Hand out the next number and advance the counter, the way taGetPONextNumber does - the advance
    is not rolled back if what follows fails, and a gap is normal in GP."""
    numbers = company.setdefault("next_numbers", {})
    current = str(numbers.get(key) or fallback).strip()
    numbers[key] = next_number(current)
    return current


def _po_number_in_use(company: dict, po_number: str) -> str | None:
    po = _find_po(company, po_number)
    if po is None:
        return None
    return "a historical PO (POP30100.PONUMBER)" if po.get("source_table") == "history" else "an active PO (POP10100.PONUMBER)"


# --- reads -----------------------------------------------------------------


def _list_vendors(company: str, payload: dict) -> dict:
    c = _company(company)
    active_only = payload.get("active_only", True)
    vendors = [
        {
            "vendor_id": v["vendor_id"],
            "vendor_name": v["vendor_name"],
            "vendor_class": v.get("vendor_class") or None,
            "status": int(v.get("status") or 0),
            "currency": (v.get("currency") or "").strip().upper() or "CAD",
        }
        for v in c.get("vendors") or []
        if not active_only or int(v.get("status") or 0) == 1
    ]
    vendors.sort(key=lambda v: v["vendor_name"])
    return {"company": company, "vendors": vendors}


def _get_vendor_contact(company: str, payload: dict) -> dict:
    c = _company(company)
    vendor_id = (payload.get("vendor_id") or "").strip()
    if not vendor_id:
        raise ops.RelayOpError("invalid_payload", "vendor_id is required")
    vendor = _find(c.get("vendors") or [], "vendor_id", vendor_id)
    if vendor is None:
        raise ops.RelayOpError(
            "vendor_not_found", f"Vendor '{vendor_id}' does not exist in {company}", vendor_id=vendor_id
        )
    return {
        "company": company,
        "vendor_id": vendor_id,
        "vendor_name": vendor["vendor_name"],
        "contact_name": (vendor.get("contact_name") or "").strip() or None,
        "email": (vendor.get("email") or "").strip() or None,
    }


def _buyer_rows(company: dict) -> list[dict]:
    rows = [b for b in company.get("buyers") or [] if (b.get("buyer_id") or "").strip()]
    return sorted(rows, key=lambda b: b["buyer_id"])


def _list_buyers(company: str, payload: dict) -> dict:
    c = _company(company)
    return {"company": company, "buyers": [b["buyer_id"] for b in _buyer_rows(c)]}


def _list_buyers_detailed(company: str, payload: dict) -> dict:
    c = _company(company)
    rows = [{"buyer_id": b["buyer_id"], "description": b.get("description") or None} for b in _buyer_rows(c)]
    return models.BuyersDetailedResponse(company=company, buyers=rows).model_dump(mode="json")


def _list_tax_details(company: str, payload: dict) -> dict:
    c = _company(company)
    rows = [
        {
            "tax_detail_id": t["tax_detail_id"],
            "description": t.get("description") or None,
            "percent": float(t.get("percent") or 0),
        }
        for t in c.get("tax_details") or []
    ]
    rows.sort(key=lambda t: t["tax_detail_id"])
    return {"company": company, "tax_details": rows}


def _list_cost_codes(company: str, payload: dict) -> dict:
    c = _company(company)
    job_number = (payload.get("job") or "").strip()
    if not job_number:
        raise ops.RelayOpError("missing_job", "job is required")
    job = _find_job(c, job_number)
    indexes = _account_indexes(c)
    rows = []
    if job is not None:
        rows = [
            {
                "cost_code": e["cost_code"],
                "description": e.get("description") or None,
                "cost_element": int(e["cost_element"]),
            }
            for e in _active_cost_codes(job)
            if _usable_account(e, indexes)
        ]
        rows.sort(key=lambda r: (r["cost_code"], r["cost_element"]))
    return {"company": company, "job": job_number, "cost_codes": rows}


def _cost_code_master_rows(company: dict, division: str) -> list[dict]:
    accounts = (company.get("division_accounts") or {}).get(division) or {}
    indexes = _account_indexes(company)
    rows = []
    seen: set[tuple[str, int]] = set()
    for entry in company.get("cost_code_master") or []:
        cost_element = int(entry["cost_element"])
        key = (entry["cost_code"], cost_element)
        if key in seen:
            continue
        seen.add(key)
        mapped_index = accounts.get(str(cost_element))
        account_index = None if mapped_index is None else int(mapped_index)
        rows.append(
            {
                "cost_code": entry["cost_code"],
                "cost_code_number_1": entry["cost_code_number_1"],
                "cost_code_number_2": entry["cost_code_number_2"],
                "alias": entry.get("alias") or None,
                "description": entry.get("description") or None,
                "cost_element": cost_element,
                "profit_type_number": int(entry.get("profit_type_number") or 0),
                "type_of_transaction": int(entry.get("type_of_transaction") or 0),
                "account_index": account_index,
                "mapped": account_index is not None and (account_index == 0 or account_index in indexes),
            }
        )
    rows.sort(key=lambda r: (r["cost_code"], r["cost_element"]))
    return rows


def _list_cost_code_master(company: str, payload: dict) -> dict:
    c = _company(company)
    division = (payload.get("division") or "").strip()
    if not division:
        raise ops.RelayOpError("missing_division", "division is required")
    return {"company": company, "division": division, "cost_codes": _cost_code_master_rows(c, division)}


def _list_jobs(company: str, payload: dict) -> dict:
    c = _company(company)
    rows = [{"job_number": j["job_number"], "job_name": j.get("job_name") or None} for j in c.get("jobs") or []]
    rows.sort(key=lambda j: (j["job_name"] or "", j["job_number"]))
    return {"company": company, "jobs": rows}


def _job_setup_health(company: str, payload: dict) -> dict:
    c = _company(company)
    job_filter = (payload.get("job") or "").strip() or None
    indexes = _account_indexes(c)
    jobs = []
    for job in c.get("jobs") or []:
        job_number = str(job["job_number"]).strip()
        if job_filter is not None and job_number.casefold() != job_filter.casefold():
            continue
        active = _active_cost_codes(job)
        issues = [
            {
                "cost_code": f"{e['cost_code']}-{int(e['cost_element'])}",
                "account_index": int(e.get("account_index") or 0),
            }
            for e in active
            if not _usable_account(e, indexes)
        ]
        jobs.append(
            {
                "job_number": job_number,
                "ok": bool(active) and not issues,
                "active_cost_code_count": len(active),
                "issues": issues,
            }
        )
    jobs.sort(key=lambda j: j["job_number"])
    return models.JobSetupHealthResponse(company=company, job=job_filter, jobs=jobs).model_dump(mode="json")


def _read_po_totals(company: str, payload: dict) -> dict:
    c = _company(company)
    po_number = (payload.get("po_number") or "").strip()
    if not po_number:
        raise ops.RelayOpError("missing_po_number", "po_number is required")
    po = _find_po(c, po_number)
    totals = None
    if po is not None:
        t = po.get("totals") or {}
        totals = {
            "po_number": po["po_number"],
            "subtotal": float(t.get("subtotal") or 0),
            "freight": float(t.get("freight") or 0),
            "miscellaneous": float(t.get("miscellaneous") or 0),
            "tax_amount": float(t.get("tax_amount") or 0),
        }
    return {"company": company, "totals": totals}


def _po_row(po: dict) -> dict:
    """One sync_pos PO, shaped exactly as econnect._assemble_pos shapes it - including deriving a
    history line's received quantity from ordered minus cancelled, since POP10500 only covers open POs."""
    is_work = (po.get("source_table") or "work") == "work"
    lines = []
    for ln in po.get("lines") or []:
        qty = float(ln.get("qty") or 0)
        cancelled = float(ln.get("qty_cancelled") or 0)
        lines.append(
            {
                "ord": int(ln["ord"]),
                "item": ln["item"],
                "itemdesc": ln.get("itemdesc") or "",
                "unit_cost": float(ln.get("unit_cost") or 0),
                "qty": qty,
                "qty_cancelled": cancelled,
                "job": ln.get("job") or None,
                "line_status": None if ln.get("line_status") is None else int(ln["line_status"]),
                "received": float(ln.get("received") or 0) if is_work else max(0.0, qty - cancelled),
            }
        )
    return {
        "po_number": po["po_number"],
        "gp_status": None if po.get("gp_status") is None else int(po["gp_status"]),
        "vendor_id": po.get("vendor_id") or None,
        "vendor_name": (po.get("vendor_name") or "").strip() or None,
        "doc_date": po.get("doc_date"),
        "modified_at": po.get("modified_at"),
        "source_table": "work" if is_work else "history",
        "lines": lines,
    }


def _sync_pos(company: str, payload: dict) -> dict:
    c = _company(company)
    page_size = max(1, min(int(payload.get("page_size") or 300), _MAX_PO_PAGE_SIZE))
    pos = sorted(c.get("purchase_orders") or [], key=lambda p: p["po_number"])
    modified_since = payload.get("modified_since")

    if modified_since is None:
        cursor = payload.get("cursor") or ""
        page = [p for p in pos if p["po_number"] > cursor][:page_size]
        next_cursor = page[-1]["po_number"] if len(page) == page_size else None
        return {"company": company, "pos": [_po_row(p) for p in page], "next_cursor": next_cursor}

    # Incremental: every open work PO (re-read so live receipt sums and status stay current) plus the
    # history rows that changed since the watermark. Unpaginated, as econnect.sync_pos is.
    since = _naive(modified_since)
    selected = [
        p
        for p in pos
        if (p.get("source_table") or "work") == "work" or (_naive(p.get("modified_at")) or datetime.min) >= since
    ]
    return {"company": company, "pos": [_po_row(p) for p in selected], "next_cursor": None}


def _list_customers(company: str, payload: dict) -> dict:
    c = _company(company)
    rows = [
        {"customer_number": cu["customer_number"], "customer_name": cu.get("customer_name") or None}
        for cu in c.get("customers") or []
        if not cu.get("inactive")
    ]
    rows.sort(key=lambda r: (r["customer_name"] or "", r["customer_number"]))
    return {"company": company, "customers": rows}


def _list_customer_addresses(company: str, payload: dict) -> dict:
    c = _company(company)
    customer_number = (payload.get("customer") or "").strip()
    if not customer_number:
        raise ops.RelayOpError("missing_customer", "customer is required")
    customer = _find(c.get("customers") or [], "customer_number", customer_number)
    rows = [
        {
            "address_code": a["address_code"],
            "address1": a.get("address1") or None,
            "city": a.get("city") or None,
            "state": a.get("state") or None,
        }
        for a in (customer or {}).get("addresses") or []
    ]
    rows.sort(key=lambda a: a["address_code"])
    return {"company": company, "customer": customer_number, "addresses": rows}


def _list_tax_schedules(company: str, payload: dict) -> dict:
    c = _company(company)
    rows = [
        {"tax_schedule_id": t["tax_schedule_id"], "description": t.get("description") or None}
        for t in c.get("tax_schedules") or []
    ]
    rows.sort(key=lambda t: t["tax_schedule_id"])
    return {"company": company, "tax_schedules": rows}


def _list_employees(company: str, payload: dict) -> dict:
    c = _company(company)
    active_only = payload.get("active_only", True)
    rows = [
        {
            "employee_id": e["employee_id"],
            "first_name": e.get("first_name") or None,
            "last_name": e.get("last_name") or None,
        }
        for e in c.get("employees") or []
        if not active_only or not e.get("inactive")
    ]
    rows.sort(key=lambda e: (e["last_name"] or "", e["first_name"] or ""))
    return models.EmployeesResponse(company=company, employees=rows).model_dump(mode="json")


def _list_divisions(company: str, payload: dict) -> dict:
    c = _company(company)
    return {"company": company, "divisions": sorted(c.get("divisions") or [])}


# --- writes ----------------------------------------------------------------


def _create_buyer(company: str, payload: dict) -> dict:
    c = _company(company)
    request = models.CreateBuyerRequest(company=company, **payload)
    rows = c.setdefault("buyers", [])
    if _find(rows, "buyer_id", request.buyer_id) is not None:
        raise ops.RelayOpError(
            "buyer_already_exists",
            f"buyer '{request.buyer_id}' is already registered in GP company {company} (POP00101)",
        )
    created = {"buyer_id": request.buyer_id, "description": request.description or None}
    rows.append(created)
    return models.CreateBuyerResponse(
        company=company, buyer_id=created["buyer_id"], description=created["description"]
    ).model_dump(mode="json")


def _resolve_cost_code_selection(c: dict, *, company: str, request: models.CreateJobRequest) -> list[dict]:
    """ops._resolve_cost_code_selection against the snapshot's master: a code the master does not hold
    is a stale picker, and a code the division has no usable account for would provision exactly the
    dangling JC00701 row #425 is about."""
    if not request.cost_codes:
        return []
    master = {(row["cost_code"], row["cost_element"]): row for row in _cost_code_master_rows(c, request.division)}
    chosen = []
    for selection in request.cost_codes:
        row = master.get((selection.cost_code, selection.cost_element))
        if row is None:
            raise ops.RelayOpError(
                "cost_code_not_in_master",
                f"cost code '{selection.cost_code}' element {selection.cost_element} is not in the "
                f"cost-code master (JC40202) for GP company {company}",
                cost_code=selection.cost_code,
                cost_element=selection.cost_element,
            )
        if not row["mapped"]:
            raise ops.RelayOpError(
                "cost_code_unmapped",
                f"cost code '{selection.cost_code}' element {selection.cost_element} has no usable GL "
                f"account for division '{request.division}' in {company}: JC40302 maps no account index "
                f"for that cost element, or the one it maps does not exist in the chart (GL00105). A job "
                f"provisioned with it could register POs and never receive them.",
                cost_code=selection.cost_code,
                cost_element=selection.cost_element,
                division=request.division,
            )
        chosen.append(row)
    return chosen


def _create_job(company: str, payload: dict) -> dict:
    c = _company(company)
    request = models.CreateJobRequest(company=company, **payload)
    if _find_job(c, request.job_number) is not None:
        raise ops.RelayOpError(
            "job_already_exists",
            f"job '{request.job_number}' already exists in GP company {company} (JC00102)",
        )
    chosen = _resolve_cost_code_selection(c, company=company, request=request)
    job = {
        "job_number": request.job_number,
        "job_name": request.job_name,
        "customer_number": request.customer_number,
        "job_address_code": request.job_address_code,
        "division": request.division,
        "cost_codes": [
            {
                "cost_code": row["cost_code"],
                "cost_element": row["cost_element"],
                "description": row["description"],
                "account_index": int(row["account_index"] or 0),
            }
            for row in chosen
        ],
    }
    c.setdefault("jobs", []).append(job)
    return models.CreateJobResponse(
        job_number=job["job_number"],
        job_name=job["job_name"],
        company=company,
        cost_codes_provisioned=len(chosen),
    ).model_dump(mode="json")


def _customer_or_refuse(c: dict, company: str, customer_number: str) -> dict:
    customer = _find(c.get("customers") or [], "customer_number", customer_number)
    if customer is None:
        raise ops.RelayOpError(
            "customer_not_found",
            f"customer '{customer_number}' is not in GP company {company} (RM00101)",
        )
    return customer


def _create_customer_address(company: str, payload: dict) -> dict:
    c = _company(company)
    # `customer` on the read half, `customer_number` on the model - both accepted, a disagreement
    # refused rather than resolved, exactly as channel._run_create_customer_address does.
    fields = dict(payload)
    customer_key = fields.pop("customer", None)
    if customer_key is not None:
        stated = fields.get("customer_number")
        if stated is not None and str(stated).strip() != str(customer_key).strip():
            raise ops.RelayOpError("invalid_payload", "customer and customer_number disagree")
        fields["customer_number"] = customer_key
    if not str(fields.get("customer_number") or "").strip():
        raise ops.RelayOpError("missing_customer", "customer is required")

    request = models.CreateCustomerAddressRequest(company=company, **fields)
    customer = _customer_or_refuse(c, company, request.customer_number)
    addresses = customer.setdefault("addresses", [])
    if _find(addresses, "address_code", request.address_code) is not None:
        raise ops.RelayOpError(
            "address_code_already_exists",
            f"customer '{request.customer_number}' already has address code '{request.address_code}' "
            f"in GP company {company} (RM00102)",
        )
    addresses.append(
        {
            "address_code": request.address_code,
            "address1": request.address1,
            "address2": request.address2 or None,
            "city": request.city,
            "state": request.state or None,
            "zip_code": request.zip_code or None,
            "country": request.country or None,
        }
    )
    return models.CreateCustomerAddressResponse(
        company=company,
        customer=request.customer_number,
        address=models.CustomerAddressOut(
            address_code=request.address_code,
            address1=request.address1 or None,
            city=request.city or None,
            state=request.state or None,
        ),
    ).model_dump(mode="json")


def _update_job_site(company: str, payload: dict) -> dict:
    c = _company(company)
    request = models.UpdateJobSiteRequest(company=company, **payload)
    job = _find_job(c, request.job_number)
    if job is None:
        raise ops.RelayOpError("job_not_found", f"Job '{request.job_number}' is not in {company}")

    address_code: str | None = None
    address_created = False
    if request.address1:
        customer_number = job.get("customer_number")
        if not customer_number:
            raise ops.RelayOpError(
                "job_has_no_customer",
                f"Job '{request.job_number}' has no customer, so a site address cannot be created for it",
            )
        # Derived from the job number and stable, so a re-push finds its own code instead of minting
        # another - and never edits an address code other jobs share.
        address_code = (request.address_code or f"SITE-{request.job_number}")[:15].strip().upper()
        customer = _customer_or_refuse(c, company, customer_number)
        addresses = customer.setdefault("addresses", [])
        if _find(addresses, "address_code", address_code) is None:
            addresses.append(
                {
                    "address_code": address_code,
                    "address1": request.address1,
                    "address2": request.address2 or None,
                    "city": request.city,
                    "state": request.state or None,
                    "zip_code": request.zip_code or None,
                    "country": request.country or None,
                }
            )
            address_created = True

    if not request.job_name and not address_code:
        # Nothing to push, so nothing is written - a no-op write against accounting data is not a thing
        # to do for the sake of a tidy code path.
        return models.UpdateJobSiteResponse(
            job_number=job["job_number"], job_name=job.get("job_name") or "", company=company
        ).model_dump(mode="json")

    if request.job_name:
        job["job_name"] = request.job_name
    if address_code:
        job["job_address_code"] = address_code
    return models.UpdateJobSiteResponse(
        job_number=job["job_number"],
        job_name=job.get("job_name") or "",
        company=company,
        address_code=job.get("job_address_code") or address_code,
        address_created=address_created,
    ).model_dump(mode="json")


def _has_exchange_rate(c: dict, *, currency: str, rate_type: str) -> bool:
    for rate in c.get("exchange_rates") or []:
        if (rate.get("currency") or "").strip().upper() == currency and (
            rate.get("rate_type") or ""
        ).strip().upper() == rate_type.upper():
            return True
    return False


def _cost_code_on_job(job: dict, cost_code: str) -> dict | None:
    """The ACTIVE cost code entry a PO line names, matched on the same 'phase-step-element' shape
    econnect.split_cost_code splits - dangling codes included, since cost_code_on_job passes those and
    the account guard right after is what refuses them."""
    for entry in _active_cost_codes(job):
        if f"{entry['cost_code']}-{int(entry['cost_element'])}".casefold() == (cost_code or "").strip().casefold():
            return entry
    return None


def _create_po(company: str, payload: dict) -> dict:
    c = _company(company)
    request = models.CreatePoRequest(company=company, **payload)
    h = request.header

    buyer_id = h.buyer_id
    if not buyer_id:
        buyer_id = buyers_config.resolve_buyer(get_settings().gp.buyers, socket.gethostname(), None)
        if not buyer_id:
            raise ops.RelayOpError(
                "buyer_unresolved",
                "no buyer_id sent and none resolved from [gp.buyers]; pick a buyer from list_buyers",
            )
    registered = [b["buyer_id"] for b in _buyer_rows(c)]
    if buyer_id not in registered:
        raise ops.RelayOpError(
            "buyer_not_registered",
            f"buyer '{buyer_id}' is not a registered GP buyer for {company} (registered: {registered})",
        )

    vendor = _find(c.get("vendors") or [], "vendor_id", h.vendor_id)
    currency = ((vendor or {}).get("currency") or "").strip().upper() or "CAD"
    mc = c.get("mc_setup") or {}
    functional = (mc.get("functional") or "CAD").strip().upper() or "CAD"
    is_foreign = currency != functional
    if is_foreign:
        rate_type = (mc.get("purchase_rate_type") or "").strip() or None
        if not rate_type:
            raise ops.RelayOpError(
                "rate_type_unresolved",
                f"no default purchasing rate type (MC40000.DEFPURTP) configured for {company}; "
                f"cannot price a {currency} PO",
            )
        if h.tax_detail_id:
            raise ops.RelayOpError(
                "tax_detail_on_foreign_po",
                f"a {currency} PO carries no tax schedule (issue #257); tax_detail_id must be omitted",
            )
        if not _has_exchange_rate(c, currency=currency, rate_type=rate_type):
            raise ops.RelayOpError(
                "no_exchange_rate",
                f"GP has no {currency} exchange rate covering {h.doc_date} for rate type {rate_type} - "
                f"add one in GP or use a {functional} vendor",
            )

    indexes = _account_indexes(c)
    line_accounts: list[int] = []
    for line in request.lines:
        if line.product_indicator != 2:
            line_accounts.append(0)
            continue
        job = _find_job(c, line.job_number)
        if job is None:
            raise ops.RelayOpError(
                "job_not_registered",
                f"job '{line.job_number}' is not a registered GP job (JC00102) for {company}",
            )
        entry = _cost_code_on_job(job, line.cost_code)
        if entry is None:
            raise ops.RelayOpError(
                "cost_code_not_on_job",
                f"cost code '{line.cost_code}' is not set up on job '{line.job_number}' (JC00701) for {company}",
            )
        account_index = int(entry.get("account_index") or 0)
        if account_index and account_index not in indexes:
            raise ops.RelayOpError(
                "cost_code_account_invalid",
                f"cost code '{line.cost_code}' on job '{line.job_number}' points at GL account index "
                f"{account_index}, which does not exist in {company} (GL00105). A PO on this cost "
                f"code would register but could never be received; the job's GP setup needs fixing "
                f"in accounting first.",
                job=line.job_number,
                cost_code=line.cost_code,
                account_index=account_index,
            )
        line_accounts.append(account_index)

    if request.po_number:
        po_number = request.po_number
    else:
        po_number = _reserve(c, "po", "PO0000001")
        if request.po_number_suffix:
            composed = f"{po_number.strip()}-{request.po_number_suffix}"
            if len(composed) > ops._MAX_PO_NUMBER:
                raise ops.RelayOpError(
                    "invalid_payload",
                    f"PO number '{composed}' is {len(composed)} characters; GP's PONUMBER holds "
                    f"{ops._MAX_PO_NUMBER}. Shorten the project number suffix.",
                    po_number=composed,
                )
            po_number = composed
    in_use = _po_number_in_use(c, po_number)
    if in_use:
        raise ops.RelayOpError("po_number_taken", f"PO number '{po_number}' is already in use in GP as {in_use}")

    subtotal = sum(line.quantity * line.unit_cost for line in request.lines)
    tax_amount = Decimal(0)
    if h.tax_detail_id:
        detail = _find(c.get("tax_details") or [], "tax_detail_id", h.tax_detail_id)
        if detail is None:
            raise ops.RelayOpError(
                "tax_detail_not_found",
                f"tax detail '{h.tax_detail_id}' is not a GP purchase tax detail "
                f"(TX00201 TXDTLTYP=2) for {company}",
            )
        tax_amount = (subtotal * Decimal(str(detail["percent"])) / Decimal(100)).quantize(Decimal("0.01"))

    c.setdefault("purchase_orders", []).append(
        {
            "po_number": po_number,
            "gp_status": _NEW_PO_STATUS,
            "vendor_id": h.vendor_id,
            "vendor_name": (vendor or {}).get("vendor_name") or h.vendor_id,
            "doc_date": h.doc_date.isoformat(),
            "modified_at": datetime.now().replace(microsecond=0).isoformat(),
            "source_table": "work",
            "buyer_id": buyer_id,
            "currency": currency,
            "totals": {
                "subtotal": float(subtotal),
                "freight": float(h.freight_amount),
                "miscellaneous": float(h.misc_amount),
                "tax_amount": float(tax_amount),
            },
            "lines": [
                {
                    # GP spaces line ordinals by 16384, and the relay dictates them (#538) so a receipt
                    # can target a line by the number UC Nexus stored.
                    "ord": index * ops.GP_LINE_ORD_STEP,
                    "item": line.item_number,
                    "itemdesc": line.item_description,
                    "unit_cost": float(line.unit_cost),
                    "qty": float(line.quantity),
                    "qty_cancelled": 0.0,
                    "job": line.job_number,
                    "line_status": _NEW_LINE_STATUS,
                    "received": 0.0,
                    "uofm": line.uofm,
                    "location_code": line.location_code,
                    "noninven": 1 if line.product_indicator == 1 else 0,
                    # POP10110.INVINDX, stamped off the job's cost code at registration - which is why a
                    # dangling one only surfaces at receipt time (#425).
                    "account_index": account,
                }
                for index, (line, account) in enumerate(zip(request.lines, line_accounts), start=1)
            ],
        }
    )

    return models.CreatePoResponse(
        po_number=po_number,
        company=company,
        lines_created=len(request.lines),
        subtotal=subtotal,
        doc_date=h.doc_date,
        vendor_id=h.vendor_id,
        currency=currency,
        tax_amount=tax_amount,
    ).model_dump(mode="json")


def _create_receipt(company: str, payload: dict) -> dict:
    c = _company(company)
    request = models.ReceiptRequest(company=company, **payload)
    rdate = request.receipt_date or date.today()
    batch = f"{request.batch_prefix}-{rdate:%Y/%m/%d}"
    custom_db = get_settings().gp.custom_db.get(company)  # None for sandboxes / unmapped companies

    po = _find_po(c, request.po_number)
    if po is None:
        raise ops.RelayOpError("po_not_found", f"PO {request.po_number} not found in {company}")
    po_lines = {int(ln["ord"]): ln for ln in po.get("lines") or []}

    for rl in request.lines:
        pl = po_lines.get(rl.po_line_ord)
        if pl is None:
            raise ops.RelayOpError(
                "po_line_not_found", f"PO {request.po_number} has no line ORD {rl.po_line_ord}"
            )
        status = int(pl.get("line_status") or 0)
        if status >= 4:
            raise ops.RelayOpError(
                "line_not_receivable",
                f"line ORD {rl.po_line_ord} is closed/cancelled (POLNESTA={status})",
            )
        ordered = Decimal(str(pl.get("qty") or 0))
        already = Decimal(str(pl.get("received") or 0))
        remaining = ordered - already
        if rl.quantity > remaining:
            raise ops.RelayOpError(
                "qty_exceeds_remaining",
                f"line ORD {rl.po_line_ord}: qty {rl.quantity} exceeds remaining {remaining} "
                f"(ordered {ordered}, already received {already})",
            )

    receiving_ords = {rl.po_line_ord for rl in request.lines}
    indexes = _account_indexes(c)
    broken = [
        {
            "ord": int(ln["ord"]),
            "item": ln["item"],
            "account_index": int(ln.get("account_index") or 0),
            "job": ln.get("job") or None,
        }
        for ln in po.get("lines") or []
        if int(ln["ord"]) in receiving_ords and not _usable_account(ln, indexes)
    ]
    if broken:
        first = broken[0]
        raise ops.RelayOpError(
            "po_line_account_invalid",
            f"PO {request.po_number} line {first['ord']} ({first['item']}) is stamped with GL account "
            f"index {first['account_index']}, which does not exist in {company} (GL00105). This came "
            f"from job '{first['job'] or 'unknown'}' cost-code setup when the PO was registered, so "
            f"the receipt cannot be posted until accounting fixes the job's GP setup.",
            po_number=request.po_number,
            lines=broken,
        )

    receipt_number = _reserve(c, "receipt", "RCT0000001")
    rcpt_ln = _RECEIPT_LINE_STEP
    receipt_lines = []
    for rl in request.lines:
        pl = po_lines[rl.po_line_ord]
        pl["received"] = float(Decimal(str(pl.get("received") or 0)) + rl.quantity)
        receipt_lines.append(
            {
                "po_line_ord": rl.po_line_ord,
                "rcpt_line_num": rcpt_ln,
                "quantity": float(rl.quantity),
                "item": pl["item"],
                "rack_location": rl.rack_location,
                "revision_number": rl.revision_number,
                "comments": rl.comments,
            }
        )
        rcpt_ln += _RECEIPT_LINE_STEP

    po["modified_at"] = datetime.now().replace(microsecond=0).isoformat()
    c.setdefault("receipts", []).append(
        {
            "receipt_number": receipt_number,
            "batch_number": batch,
            "po_number": request.po_number,
            "receipt_date": rdate.isoformat(),
            "received_by": request.received_by,
            "lines": receipt_lines,
        }
    )

    return models.ReceiptResponse(
        receipt_number=receipt_number,
        batch_number=batch,
        po_number=request.po_number,
        company=company,
        lines_received=len(request.lines),
        custom_db_written=bool(custom_db),
    ).model_dump(mode="json")


def _capture_snapshot(company: str, payload: dict) -> dict:
    """This relay's own record for one company, in the shape the GP handler builds by reading GP
    (channel._run_capture_snapshot, via capture.capture_company).

    Answering the op out of the loaded snapshot is what makes an export through the backend's
    relaySnapshot query idempotent against a preview: capture what a stub serves and the file that
    comes back is the file it was built from, in-memory writes included. `name` is carried only when
    the snapshot has one, which is the same rule the GP handler applies to what discovery knew."""
    return {"format": SNAPSHOT_FORMAT, "version": SNAPSHOT_VERSION, "record": _company(company)}


# The SAME op names channel._OPS carries - the hello frame advertises that set and the backend refuses
# anything outside it, so a fixture relay that answered a different set would be a relay the backend
# could not talk to. test_fixture_ops pins the two together.
OPS = {
    "list_vendors": _list_vendors,
    "get_vendor_contact": _get_vendor_contact,
    "list_buyers": _list_buyers,
    "list_tax_details": _list_tax_details,
    "list_cost_codes": _list_cost_codes,
    "list_cost_code_master": _list_cost_code_master,
    "list_jobs": _list_jobs,
    "read_po_totals": _read_po_totals,
    "sync_pos": _sync_pos,
    "create_po": _create_po,
    "create_receipt": _create_receipt,
    "list_customers": _list_customers,
    "list_customer_addresses": _list_customer_addresses,
    "list_tax_schedules": _list_tax_schedules,
    "list_divisions": _list_divisions,
    "create_job": _create_job,
    "list_employees": _list_employees,
    "list_buyers_detailed": _list_buyers_detailed,
    "create_buyer": _create_buyer,
    "create_customer_address": _create_customer_address,
    "update_job_site": _update_job_site,
    "job_setup_health": _job_setup_health,
    "capture_snapshot": _capture_snapshot,
}
