"""`ucnexus-relay capture --companies TUBC,TUCSH --out <path>` - run the relay's own read handlers
against GP and write what came back as a fixture snapshot (the format fixture_ops.py documents).

The snapshot checked in at relay/fixtures/gp-snapshot.json is synthetic, written by hand so the
container has something to serve on day one. This is how it gets replaced with the real sandbox
companies: run it on the workstation, which is the only machine that can reach GP, and commit the file
it writes. Read-only throughout - every call here is one of the list_/read_ handlers the channel already
serves (bar one plain SELECT for the company name, below), so capturing costs GP nothing it is not asked
for a hundred times a day anyway.

Four things GP holds that no read op exposes, and what is written instead:

  - GL00105, the account master. Not read at all. A job's usable cost codes are stored at account index
    0 ("GP picks the account at posting time"), which is usable in the fixture for the same reason it is
    usable in GP, and only the codes job_setup_health already reports as broken keep their real dangling
    index. #425 therefore reproduces from the verdict GP itself gave, without a read of the chart.
  - POP10110.INVINDX per PO line. sync_pos does not carry it, so captured lines are stored at index 0
    and are receivable. A PO whose lines dangle in GP is not reproduced as such; the job whose cost code
    dangles still is.
  - the PO and receipt counters. Reserving a number is a WRITE, so the PO counter is derived as one past
    the highest number captured and the receipt counter starts fresh.
  - the company's display name, SY01500.CMPNYNAM. Read here with a plain SELECT against the GP system
    database, because that name is what a workstation relay discovers (companies.py) and a fixture relay
    should report the same thing. A read that fails leaves the field out entirely rather than writing a
    guess; discovery then falls back to the company code, as it does for any older snapshot.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import db, econnect
from .companies import COMPANY_NAME_QUERY
from .config import get_settings
from .fixture_ops import SNAPSHOT_FORMAT, SNAPSHOT_VERSION, next_number

_PAGE_SIZE = 300
_FIRST_PO_NUMBER = "PO0000001"
_FIRST_RECEIPT_NUMBER = "RCT0000001"


def _capture_vendors(conn) -> list[dict]:
    """PM00200 with each vendor's SY01200 contact, since a PO send needs the email and the vendor list
    does not carry it. active_only=False deliberately: an inactive vendor still has to be a vendor the
    fixture can answer for, and list_vendors filters on status at read time anyway."""
    out = []
    for row in econnect.list_vendors(conn, active_only=False):
        contact = econnect.get_vendor_contact(conn, row["vendor_id"]) or {}
        out.append(
            {
                **row,
                "contact_name": contact.get("contact_name"),
                "email": contact.get("email"),
            }
        )
    return out


def _capture_customers(conn) -> list[dict]:
    out = []
    for row in econnect.list_customers(conn):
        addresses = [
            {
                "address_code": a["address_code"],
                "address1": a["address1"],
                "address2": None,
                "city": a["city"],
                "state": a["state"],
                "zip_code": None,
                "country": None,
            }
            for a in econnect.list_customer_addresses(conn, row["customer_number"])
        ]
        out.append({**row, "inactive": False, "addresses": addresses})
    return out


def _capture_cost_code_master(conn, divisions: list[str]) -> tuple[list[dict], dict, set[int]]:
    """JC40202 and JC40302, split back apart out of the per-division read.

    list_cost_code_master answers the master ALREADY resolved for one division, so the master is what
    every division's answer agrees on and the account index is what differs - which is exactly how the
    snapshot stores the two. `mapped` is not stored: it is recomputed against account_indexes, so only
    the indexes GP called usable go into that set and an index it called dangling stays dangling."""
    master: dict[tuple[str, int], dict] = {}
    division_accounts: dict[str, dict[str, int]] = {}
    usable: set[int] = set()
    for division in divisions:
        for row in econnect.list_cost_code_master(conn, division):
            key = (row["cost_code"], row["cost_element"])
            master.setdefault(
                key,
                {
                    "cost_code": row["cost_code"],
                    "cost_code_number_1": row["cost_code_number_1"],
                    "cost_code_number_2": row["cost_code_number_2"],
                    "alias": row["alias"],
                    "description": row["description"],
                    "cost_element": row["cost_element"],
                    "profit_type_number": row["profit_type_number"],
                    "type_of_transaction": row["type_of_transaction"],
                },
            )
            if row["account_index"] is not None:
                division_accounts.setdefault(division, {})[str(row["cost_element"])] = row["account_index"]
                if row["mapped"] and row["account_index"]:
                    usable.add(row["account_index"])
    return [master[key] for key in sorted(master)], division_accounts, usable


def _capture_jobs(conn) -> list[dict]:
    """JC00102, each job carrying the cost codes a PO could name - the usable ones from list_cost_codes
    at index 0, then the broken ones job_setup_health names, at the index it names."""
    health = {h["job_number"]: h for h in econnect.job_setup_health(conn)}
    jobs = []
    for row in econnect.list_jobs(conn):
        job_number = row["job_number"]
        detail = econnect.get_job(conn, job_number) or {}
        cost_codes = [
            {
                "cost_code": c["cost_code"],
                "cost_element": c["cost_element"],
                "description": c["description"],
                "account_index": 0,
                "inactive": False,
            }
            for c in econnect.list_cost_codes(conn, job_number)
        ]
        for issue in (health.get(job_number) or {}).get("issues") or []:
            cost_code, _, element = str(issue["cost_code"]).rpartition("-")
            cost_codes.append(
                {
                    "cost_code": cost_code,
                    "cost_element": int(element),
                    "description": None,
                    "account_index": int(issue["account_index"]),
                    "inactive": False,
                }
            )
        jobs.append(
            {
                "job_number": job_number,
                "job_name": row["job_name"],
                "customer_number": detail.get("customer_number"),
                "job_address_code": detail.get("job_address_code"),
                "division": None,  # JC00102 carries one, but no read op returns it and nothing serves it
                "cost_codes": cost_codes,
            }
        )
    return jobs


def _capture_purchase_orders(conn) -> list[dict]:
    """Every PO sync_pos will page out, plus the header totals read_po_totals answers with (the sync
    shape carries lines but no header amounts, and the generated PO document reads those)."""
    pos = []
    cursor = None
    while True:
        page = econnect.sync_pos(conn, cursor=cursor, page_size=_PAGE_SIZE, modified_since=None)
        for row in page["pos"]:
            totals = econnect.read_po_totals(conn, row["po_number"]) or {}
            pos.append(
                {
                    **row,
                    "totals": {
                        "subtotal": float(totals.get("subtotal") or 0),
                        "freight": float(totals.get("freight") or 0),
                        "miscellaneous": float(totals.get("miscellaneous") or 0),
                        "tax_amount": float(totals.get("tax_amount") or 0),
                    },
                    "lines": [{**ln, "account_index": 0} for ln in row["lines"]],
                }
            )
        cursor = page["next_cursor"]
        if cursor is None:
            return pos


def _next_po_number(pos: list[dict]) -> str:
    numbers = sorted(p["po_number"] for p in pos if next_number(p["po_number"]) != p["po_number"])
    return next_number(numbers[-1]) if numbers else _FIRST_PO_NUMBER


def capture_company(conn) -> dict:
    """One company's whole snapshot record, from the reads above."""
    divisions = econnect.list_divisions(conn)
    master, division_accounts, usable_indexes = _capture_cost_code_master(conn, divisions)
    purchase_orders = _capture_purchase_orders(conn)
    return {
        "mc_setup": econnect.get_mc_setup(conn),
        # No read op lists GP's maintained exchange rates (has_exchange_rate probes for one), so a
        # captured company has none and a foreign-currency PO answers no_exchange_rate - which is what
        # GP would answer for a company that genuinely maintains none.
        "exchange_rates": [],
        "next_numbers": {"po": _next_po_number(purchase_orders), "receipt": _FIRST_RECEIPT_NUMBER},
        "account_indexes": sorted(usable_indexes),
        "vendors": _capture_vendors(conn),
        "buyers": econnect.list_buyers_detailed(conn),
        "tax_details": econnect.list_tax_details(conn),
        "tax_schedules": econnect.list_tax_schedules(conn),
        "divisions": divisions,
        "employees": [{**e, "inactive": False} for e in econnect.list_employees(conn, active_only=True)],
        "customers": _capture_customers(conn),
        "cost_code_master": master,
        "division_accounts": division_accounts,
        "jobs": _capture_jobs(conn),
        "purchase_orders": purchase_orders,
        "receipts": [],
    }


def _company_name(open_connection, company: str) -> str | None:
    """One company's display name out of the company master, or None if it cannot be read.

    The master lives in the GP SYSTEM database, not the company's own, so this opens its own connection
    there. None rather than a fallback on failure: the field is then absent from the snapshot and
    discovery falls back to the code, which is the honest answer for a name nobody read."""
    system_db = get_settings().sql.system_db
    try:
        with open_connection(system_db) as conn:
            row = conn.cursor().execute(COMPANY_NAME_QUERY, company).fetchone()
    except Exception as e:  # noqa: BLE001 - a name is a nicety; a capture must not die for one
        print(f"{company}: could not read its name from {system_db} ({e}); leaving it out", file=sys.stderr)
        return None
    return (str(row[0]).strip() or None) if row and row[0] is not None else None


def capture(companies: list[str], out_path: str | Path, *, connect=None) -> dict:
    """Read `companies` out of GP and write the snapshot to `out_path`. `connect` is the read-connection
    factory, injectable so the tests can drive this with a fake connection instead of a GP one. It takes
    a DATABASE name - each company's own, then the system database for the name read."""
    open_connection = connect or db.get_read_connection
    snapshot = {
        "format": SNAPSHOT_FORMAT,
        "version": SNAPSHOT_VERSION,
        "captured_at": datetime.now().replace(microsecond=0).isoformat(),
        "source": "captured from GP by `ucnexus-relay capture`",
        "companies": {},
    }
    for company in companies:
        with open_connection(company) as conn:
            record = capture_company(conn)
        name = _company_name(open_connection, company)
        snapshot["companies"][company] = {"name": name, **record} if name else record
    path = Path(out_path)
    if path.parent != Path():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ucnexus-relay capture",
        description="read GP through the relay's own read handlers and write a fixture snapshot",
    )
    parser.add_argument("--companies", required=True, help="comma-separated GP companies, e.g. TUBC,TUCSH")
    parser.add_argument("--out", required=True, help="path to write the snapshot to")
    args = parser.parse_args(argv)

    companies = [c.strip() for c in args.companies.split(",") if c.strip()]
    if not companies:
        print("--companies must name at least one GP company", file=sys.stderr)
        return 2

    snapshot = capture(companies, args.out)
    for company, data in snapshot["companies"].items():
        print(
            f"{company}: {len(data['jobs'])} jobs, {len(data['vendors'])} vendors, "
            f"{len(data['purchase_orders'])} purchase orders"
        )
    print(f"wrote {args.out}")
    return 0
