"""Fixture mode end to end: every op answered from the checked-in snapshot, dispatched through
channel._dispatch exactly as a backend job would be, with no GP and no pyodbc anywhere.

Everything goes through _dispatch rather than calling the handlers directly - the point of this mode is
that the CHANNEL serves the same op set the same way, so the registry swap has to be part of what is
tested. Writes mutate the in-memory snapshot, so reset_state runs around every test.
"""

from pathlib import Path

import pytest

from ucnexus_relay import channel, companies, fixture_ops
from ucnexus_relay.config import get_settings

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "gp-snapshot.json"


def _fixture_env(monkeypatch) -> None:
    monkeypatch.setenv("UCNEXUS_RELAY_MODE", "fixture")
    monkeypatch.setenv("UCNEXUS_RELAY_FIXTURE_PATH", str(SNAPSHOT))
    get_settings.cache_clear()
    fixture_ops.reset_state()


@pytest.fixture(autouse=True)
def fixture_mode(monkeypatch):
    _fixture_env(monkeypatch)
    # The real discovery path for this mode: the served companies ARE the snapshot's, read out of it
    # the way a workstation reads GP's company master.
    companies.refresh(max_age=0)
    yield
    get_settings.cache_clear()
    fixture_ops.reset_state()


def ok(op: str, company: str = "TUBC", payload: dict | None = None) -> dict:
    reply = channel._dispatch(op, company, payload or {})
    assert reply["ok"] is True, reply
    return reply["result"]


def err(op: str, company: str = "TUBC", payload: dict | None = None) -> dict:
    reply = channel._dispatch(op, company, payload or {})
    assert reply["ok"] is False, reply
    return reply["error"]


# --- the registry itself ----------------------------------------------------


def test_fixture_registry_serves_exactly_the_channel_op_set():
    """The hello frame advertises sorted(_OPS) and the backend refuses anything outside it, so a
    fixture relay answering a different set would be a relay the backend cannot talk to."""
    assert set(fixture_ops.OPS) == set(channel._OPS)


def test_dispatch_resolves_to_the_fixture_registry_in_fixture_mode():
    assert channel.ops_registry() is fixture_ops.OPS


def test_dispatch_resolves_to_the_real_handlers_otherwise(monkeypatch):
    monkeypatch.delenv("UCNEXUS_RELAY_MODE", raising=False)
    get_settings.cache_clear()
    assert channel.ops_registry() is channel._OPS


def test_unknown_op_is_still_unknown_op():
    assert err("no_such_op")["error"] == "unknown_op"


def test_a_company_outside_the_snapshot_is_company_not_allowed(serving):
    # Served, absent from the snapshot: there is nothing to answer it from either way. Only reachable
    # by seeding a served set the snapshot disagrees with - discovery reads the snapshot itself.
    serving(["TUBC", "TUCSH", "UBC"])
    assert err("list_jobs", "UBC")["error"] == "company_not_allowed"


def test_a_company_this_relay_did_not_discover_is_company_not_allowed():
    assert err("list_jobs", "UCSH")["error"] == "company_not_allowed"


def test_the_served_companies_are_the_snapshots_own():
    assert companies.current().companies == ["TUBC", "TUCSH"]


# --- reads ------------------------------------------------------------------


def test_list_vendors_filters_to_active_and_carries_the_currency():
    vendors = ok("list_vendors")["vendors"]
    ids = [v["vendor_id"] for v in vendors]
    assert "ALLEGION" in ids
    assert "OLDCO" not in ids  # VENDSTTS 2
    allegion = next(v for v in vendors if v["vendor_id"] == "ALLEGION")
    assert allegion["currency"] == "CAD"
    assert next(v for v in vendors if v["vendor_id"] == "USLOCK")["currency"] == "USD"


def test_list_vendors_can_include_inactive():
    ids = [v["vendor_id"] for v in ok("list_vendors", payload={"active_only": False})["vendors"]]
    assert "OLDCO" in ids


def test_get_vendor_contact_answers_the_email():
    contact = ok("get_vendor_contact", payload={"vendor_id": "ALLEGION"})
    assert contact["email"] == "dana.whitfield@allegion.example"
    assert contact["contact_name"] == "Dana Whitfield"


def test_get_vendor_contact_without_an_email_answers_none():
    assert ok("get_vendor_contact", payload={"vendor_id": "TRIMCO"})["email"] is None


def test_get_vendor_contact_errors():
    assert err("get_vendor_contact")["error"] == "invalid_payload"
    assert err("get_vendor_contact", payload={"vendor_id": "NOPE"})["error"] == "vendor_not_found"


def test_buyer_reads():
    assert "MIRA" in ok("list_buyers")["buyers"]
    detailed = ok("list_buyers_detailed")["buyers"]
    assert {"buyer_id": "MIRA", "description": "Mira Vasquez"} in detailed


def test_tax_and_schedule_reads():
    details = ok("list_tax_details")["tax_details"]
    assert {"tax_detail_id": "BC GST P", "description": "BC GST 5% purchases", "percent": 5.0} in details
    assert "BC-TAX" in [s["tax_schedule_id"] for s in ok("list_tax_schedules")["tax_schedules"]]


def test_division_customer_and_employee_reads():
    assert ok("list_divisions")["divisions"] == ["VANCOUVER"]
    assert ok("list_divisions", "TUCSH")["divisions"] == ["VANCOUVER", "VICTORIA"]
    customers = ok("list_customers")["customers"]
    assert "AGGRIT0001" in [c["customer_number"] for c in customers]
    employees = ok("list_employees")["employees"]
    assert "EMP0007" not in [e["employee_id"] for e in employees]  # inactive
    assert "EMP0007" in [
        e["employee_id"] for e in ok("list_employees", payload={"active_only": False})["employees"]
    ]


def test_customer_addresses_are_scoped_and_require_a_customer():
    assert err("list_customer_addresses")["error"] == "missing_customer"
    result = ok("list_customer_addresses", payload={"customer": "AGGRIT0001"})
    assert [a["address_code"] for a in result["addresses"]] == ["MAIN", "SITE-BURN"]
    assert ok("list_customer_addresses", payload={"customer": "NOBODY"})["addresses"] == []


def test_list_jobs():
    jobs = ok("list_jobs")["jobs"]
    assert {"job_number": "23093", "job_name": "AGGREGATE - BURNABY CIVIC YARD"} in jobs


def test_list_cost_codes_requires_a_job_and_hides_a_dangling_code():
    assert err("list_cost_codes")["error"] == "missing_job"
    healthy = ok("list_cost_codes", payload={"job": "23093"})["cost_codes"]
    assert ("210-200", 2) in [(c["cost_code"], c["cost_element"]) for c in healthy]
    # 310-100 on job 23145 points at account index 1617, which TUBC's chart has never had (#425)
    broken_job = ok("list_cost_codes", payload={"job": " 23145 "})
    assert broken_job["job"] == "23145"
    assert ("310-100", 3) not in [(c["cost_code"], c["cost_element"]) for c in broken_job["cost_codes"]]


def test_list_cost_code_master_requires_a_division_and_reports_unmapped_codes():
    assert err("list_cost_code_master")["error"] == "missing_division"
    rows = ok("list_cost_code_master", payload={"division": "VANCOUVER"})["cost_codes"]
    by_key = {(r["cost_code"], r["cost_element"]): r for r in rows}
    assert by_key[("210-200", 2)]["mapped"] is True
    assert by_key[("210-200", 2)]["account_index"] == 1201
    # VANCOUVER has no division account for cost element 7, so freight is offered disabled, not hidden
    assert by_key[("710-000", 7)]["mapped"] is False
    assert by_key[("710-000", 7)]["account_index"] is None


def test_job_setup_health_names_the_broken_codes():
    jobs = {j["job_number"]: j for j in ok("job_setup_health")["jobs"]}
    assert jobs["23093"]["ok"] is True
    assert jobs["23145"]["ok"] is False
    assert jobs["23145"]["issues"] == [{"cost_code": "310-100-3", "account_index": 1617}]
    # a job nobody has set a cost structure on yet is its own failure
    assert jobs["25044"]["ok"] is False
    assert jobs["25044"]["active_cost_code_count"] == 0


def test_job_setup_health_filters_to_one_job():
    result = ok("job_setup_health", payload={"job": "23145"})
    assert result["job"] == "23145"
    assert [j["job_number"] for j in result["jobs"]] == ["23145"]


def test_read_po_totals():
    assert err("read_po_totals")["error"] == "missing_po_number"
    totals = ok("read_po_totals", payload={"po_number": "PO0000044"})["totals"]
    assert totals == {
        "po_number": "PO0000044",
        "subtotal": 2616.0,
        "freight": 85.0,
        "miscellaneous": 0.0,
        "tax_amount": 63.55,
    }
    assert ok("read_po_totals", payload={"po_number": "NOPE"})["totals"] is None


def test_sync_pos_backfill_pages_by_keyset():
    first = ok("sync_pos", payload={"page_size": 2})
    assert [p["po_number"] for p in first["pos"]] == ["PO0000019", "PO0000031"]
    assert first["next_cursor"] == "PO0000031"
    second = ok("sync_pos", payload={"page_size": 2, "cursor": first["next_cursor"]})
    assert [p["po_number"] for p in second["pos"]] == ["PO0000044", "PO0000056"]
    last = ok("sync_pos", payload={"page_size": 2, "cursor": second["next_cursor"]})
    assert [p["po_number"] for p in last["pos"]] == ["PO0000070", "PO0000081"]
    # a full page still hands back a cursor, exactly as the keyset read does - the SHORT page is what
    # says the history has drained, so the loop always makes one more call
    assert last["next_cursor"] == "PO0000081"
    drained = ok("sync_pos", payload={"page_size": 2, "cursor": last["next_cursor"]})
    assert drained["pos"] == []
    assert drained["next_cursor"] is None


def test_sync_pos_history_lines_derive_their_received_quantity():
    page = ok("sync_pos", payload={"page_size": 100})
    cancelled = next(p for p in page["pos"] if p["po_number"] == "PO0000019")
    assert cancelled["source_table"] == "history"
    # 24 ordered, 24 cancelled - nothing was ever received against it
    assert cancelled["lines"][0]["received"] == 0.0
    closed = next(p for p in page["pos"] if p["po_number"] == "PO0000031")
    assert [ln["received"] for ln in closed["lines"]] == [6.0, 6.0]


def test_sync_pos_incremental_takes_every_open_po_plus_changed_history():
    result = ok("sync_pos", payload={"modified_since": "2026-06-01T00:00:00"})
    assert result["next_cursor"] is None
    numbers = [p["po_number"] for p in result["pos"]]
    assert numbers == ["PO0000044", "PO0000056", "PO0000070", "PO0000081"]
    # a history PO that changed after the watermark comes back too
    numbers = [p["po_number"] for p in ok("sync_pos", payload={"modified_since": "2026-01-01T00:00:00"})["pos"]]
    assert "PO0000019" in numbers and "PO0000031" in numbers


# --- the write sequence -----------------------------------------------------

_JOB = {
    "job_number": "26001",
    "job_name": "PACIFIC - NEW BUILD",
    "division": "VANCOUVER",
    "customer_number": "PACIFI0001",
    "job_address_code": "MAIN",
    "billto_address_code": "MAIN",
    "tax_schedule_id": "BC-TAX",
    "created_date": "2026-09-01",
    "cost_codes": [{"cost_code": "210-200", "cost_element": 2}, {"cost_code": "310-000", "cost_element": 3}],
}


def _po_payload(**overrides) -> dict:
    payload = {
        "header": {
            "vendor_id": "ALLEGION",
            "buyer_id": "MIRA",
            "confirm_with": "Mira",
            "doc_date": "2026-09-01",
        },
        "lines": [
            {
                "item_number": "L9070",
                "item_description": "L9070 MORTISE LOCK 626",
                "quantity": "4",
                "unit_cost": "412.75",
                "product_indicator": 2,
                "job_number": "26001",
                "cost_code": "210-200-2",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_create_job_then_po_then_receipt_is_visible_to_the_reads():
    created = ok("create_job", payload=_JOB)
    assert created == {
        "job_number": "26001",
        "job_name": "PACIFIC - NEW BUILD",
        "company": "TUBC",
        "cost_codes_provisioned": 2,
    }
    # the new job answers the reads a register-PO screen makes
    assert "26001" in [j["job_number"] for j in ok("list_jobs")["jobs"]]
    assert ok("job_setup_health", payload={"job": "26001"})["jobs"][0]["ok"] is True
    assert [c["cost_code"] for c in ok("list_cost_codes", payload={"job": "26001"})["cost_codes"]] == [
        "210-200",
        "310-000",
    ]

    po = ok("create_po", payload=_po_payload(po_number_suffix="26001"))
    # GP reserves the number and the suffix makes it traceable (#488)
    assert po["po_number"] == "PO0000101-26001"
    assert po["lines_created"] == 1
    assert po["subtotal"] == "1651.00"
    assert po["currency"] == "CAD"

    totals = ok("read_po_totals", payload={"po_number": po["po_number"]})["totals"]
    assert totals["subtotal"] == 1651.0

    page = ok("sync_pos", payload={"page_size": 100})
    mirrored = next(p for p in page["pos"] if p["po_number"] == po["po_number"])
    assert mirrored["source_table"] == "work"
    assert mirrored["lines"][0] == {
        "ord": 16384,
        "item": "L9070",
        "itemdesc": "L9070 MORTISE LOCK 626",
        "unit_cost": 412.75,
        "qty": 4.0,
        "qty_cancelled": 0.0,
        "job": "26001",
        "line_status": 1,
        "received": 0.0,
    }

    receipt = ok(
        "create_receipt",
        payload={
            "po_number": po["po_number"],
            "lines": [{"po_line_ord": 16384, "quantity": "3", "rack_location": "A-12"}],
            "receipt_date": "2026-09-02",
        },
    )
    assert receipt["receipt_number"] == "RCT0000042"
    assert receipt["batch_number"] == "EC-2026/09/02"
    assert receipt["lines_received"] == 1
    # TUBC has no paired custom warehouse DB, so the receipt is GP-only
    assert receipt["custom_db_written"] is False

    page = ok("sync_pos", payload={"page_size": 100})
    mirrored = next(p for p in page["pos"] if p["po_number"] == po["po_number"])
    assert mirrored["lines"][0]["received"] == 3.0

    # and the counters advanced for the next caller
    assert ok("create_po", payload=_po_payload())["po_number"] == "PO0000102"


def test_a_second_create_job_is_job_already_exists():
    ok("create_job", payload=_JOB)
    error = err("create_job", payload=_JOB)
    assert error["error"] == "job_already_exists"
    assert "26001" in error["message"]


def test_create_job_refuses_a_code_the_master_cannot_account_for():
    unmapped = dict(_JOB, cost_codes=[{"cost_code": "710-000", "cost_element": 7}])
    assert err("create_job", payload=unmapped)["error"] == "cost_code_unmapped"
    made_up = dict(_JOB, cost_codes=[{"cost_code": "999-999", "cost_element": 2}])
    assert err("create_job", payload=made_up)["error"] == "cost_code_not_in_master"


def test_create_po_pre_checks():
    assert err("create_po", payload=_po_payload())["error"] == "job_not_registered"
    ok("create_job", payload=_JOB)

    bad_buyer = _po_payload()
    bad_buyer["header"]["buyer_id"] = "NOBODY"
    assert err("create_po", payload=bad_buyer)["error"] == "buyer_not_registered"

    wrong_code = _po_payload()
    wrong_code["lines"][0]["cost_code"] = "510-000-5"
    assert err("create_po", payload=wrong_code)["error"] == "cost_code_not_on_job"

    taken = _po_payload(po_number="PO0000044")
    assert err("create_po", payload=taken)["error"] == "po_number_taken"

    long_suffix = _po_payload(po_number_suffix="12345678")
    assert err("create_po", payload=long_suffix)["error"] == "invalid_payload"

    missing_tax = _po_payload()
    missing_tax["header"]["tax_detail_id"] = "NOT A DETAIL"
    assert err("create_po", payload=missing_tax)["error"] == "tax_detail_not_found"


def test_create_po_computes_the_tax_the_chosen_detail_implies():
    ok("create_job", payload=_JOB)
    payload = _po_payload()
    payload["header"]["tax_detail_id"] = "BC GST P"
    result = ok("create_po", payload=payload)
    assert result["subtotal"] == "1651.00"
    assert result["tax_amount"] == "82.55"


def test_create_po_refuses_a_cost_code_whose_account_dangles():
    """The #425 guard: the code is on the job, but the GL account it carries is not in this company's
    chart, so a PO against it would register and could never be received."""
    payload = _po_payload()
    payload["lines"][0]["job_number"] = "23145"
    payload["lines"][0]["cost_code"] = "310-100-3"
    error = err("create_po", payload=payload)
    assert error["error"] == "cost_code_account_invalid"
    assert error["context"]["account_index"] == 1617


def test_create_po_on_a_foreign_vendor_needs_a_maintained_rate():
    ok("create_job", payload=_JOB)
    payload = _po_payload()
    payload["header"]["vendor_id"] = "USLOCK"
    # TUBC maintains a USD rate, so this prices; TUCSH maintains none.
    assert ok("create_po", payload=payload)["currency"] == "USD"
    payload["header"]["tax_detail_id"] = "BC GST P"
    assert err("create_po", payload=payload)["error"] == "tax_detail_on_foreign_po"


def test_create_receipt_refuses_more_than_the_line_has_left():
    assert err("create_receipt", payload={"po_number": "NOPE", "lines": [
        {"po_line_ord": 16384, "quantity": "1", "rack_location": "A-1"}
    ]})["error"] == "po_not_found"

    assert err("create_receipt", payload={"po_number": "PO0000056", "lines": [
        {"po_line_ord": 99999, "quantity": "1", "rack_location": "A-1"}
    ]})["error"] == "po_line_not_found"

    # PO0000044 line 16384 is fully received and closed (POLNESTA 4)
    assert err("create_receipt", payload={"po_number": "PO0000044", "lines": [
        {"po_line_ord": 16384, "quantity": "1", "rack_location": "A-1"}
    ]})["error"] == "line_not_receivable"

    # PO0000056 line 32768: 10 ordered, 4 already received
    assert err("create_receipt", payload={"po_number": "PO0000056", "lines": [
        {"po_line_ord": 32768, "quantity": "7", "rack_location": "A-1"}
    ]})["error"] == "qty_exceeds_remaining"
    result = ok("create_receipt", payload={"po_number": "PO0000056", "lines": [
        {"po_line_ord": 32768, "quantity": "6", "rack_location": "A-1"}
    ]})
    assert result["lines_received"] == 1


def test_create_receipt_refuses_a_line_stamped_with_a_dangling_account():
    error = err("create_receipt", payload={"po_number": "PO0000070", "lines": [
        {"po_line_ord": 16384, "quantity": "1", "rack_location": "A-1"}
    ]})
    assert error["error"] == "po_line_account_invalid"
    assert error["context"]["lines"][0]["account_index"] == 1617


def test_create_buyer():
    created = ok("create_buyer", payload={"buyer_id": "NEWB", "description": "New Buyer"})
    assert created == {"company": "TUBC", "buyer_id": "NEWB", "description": "New Buyer"}
    assert "NEWB" in ok("list_buyers")["buyers"]
    assert err("create_buyer", payload={"buyer_id": "NEWB"})["error"] == "buyer_already_exists"


def test_create_customer_address():
    payload = {
        "customer": "AGGRIT0001",
        "address_code": "site-new",
        "address1": "700 Terminal Avenue",
        "city": "Vancouver",
        "state": "BC",
    }
    created = ok("create_customer_address", payload=payload)
    assert created["address"] == {
        "address_code": "SITE-NEW",  # uppercased so it reads like GP's own codes
        "address1": "700 Terminal Avenue",
        "city": "Vancouver",
        "state": "BC",
    }
    assert "SITE-NEW" in [
        a["address_code"] for a in ok("list_customer_addresses", payload={"customer": "AGGRIT0001"})["addresses"]
    ]
    assert err("create_customer_address", payload=payload)["error"] == "address_code_already_exists"

    assert err("create_customer_address", payload={"address1": "x", "city": "y", "address_code": "z"})[
        "error"
    ] == "missing_customer"
    disagreeing = dict(payload, customer_number="COASTP0001", address_code="OTHER")
    assert err("create_customer_address", payload=disagreeing)["error"] == "invalid_payload"
    unknown = dict(payload, customer="NOBODY", address_code="OTHER")
    assert err("create_customer_address", payload=unknown)["error"] == "customer_not_found"


def test_update_job_site_mints_a_job_specific_address_code():
    assert err("update_job_site", payload={"job_number": "99999"})["error"] == "job_not_found"

    result = ok(
        "update_job_site",
        payload={
            "job_number": "23093",
            "job_name": "AGGREGATE - BURNABY CIVIC YARD (REV)",
            "address1": "3300 Still Creek Drive",
            "city": "Burnaby",
            "state": "BC",
        },
    )
    assert result["address_code"] == "SITE-23093"
    assert result["address_created"] is True
    assert result["job_name"] == "AGGREGATE - BURNABY CIVIC YARD (REV)"

    # re-pushing the same thing is idempotent: the code exists, so nothing is minted again
    again = ok(
        "update_job_site",
        payload={"job_number": "23093", "address1": "3300 Still Creek Drive", "city": "Burnaby"},
    )
    assert again["address_code"] == "SITE-23093"
    assert again["address_created"] is False


def test_update_job_site_with_nothing_to_push_writes_nothing():
    result = ok("update_job_site", payload={"job_number": "23110"})
    assert result["address_code"] is None
    assert result["address_created"] is False
    assert result["job_name"] == "COASTAL - GRANVILLE TOWER LOBBY"


def test_writes_never_reach_the_checked_in_file():
    before = SNAPSHOT.read_bytes()
    ok("create_buyer", payload={"buyer_id": "EPHEM", "description": "in memory only"})
    assert SNAPSHOT.read_bytes() == before
    fixture_ops.reset_state()
    assert "EPHEM" not in ok("list_buyers")["buyers"]


def test_capture_snapshot_hands_back_the_loaded_record():
    """#666: the export is idempotent against a stub. Capture what a preview serves and the record that
    comes back is the one it was loaded with, so re-running it cannot quietly rewrite the fixture."""
    result = ok("capture_snapshot")

    assert result["format"] == fixture_ops.SNAPSHOT_FORMAT
    assert result["version"] == fixture_ops.SNAPSHOT_VERSION
    assert result["record"] == fixture_ops.load_state()["companies"]["TUBC"]
    assert result["record"]["jobs"] and result["record"]["vendors"]

    # The in-memory writes are part of what a stub serves, so they are part of what it captures.
    ok("create_buyer", payload={"buyer_id": "EPHEM", "description": "in memory only"})
    assert "EPHEM" in [b["buyer_id"] for b in ok("capture_snapshot")["record"]["buyers"]]


def test_capture_snapshot_is_gated_like_every_other_fixture_op():
    assert err("capture_snapshot", "UCSH")["error"] == "company_not_allowed"


def test_the_second_company_is_served_too():
    assert "31004" in [j["job_number"] for j in ok("list_jobs", "TUCSH")["jobs"]]
    rows = ok("list_cost_code_master", "TUCSH", {"division": "VICTORIA"})["cost_codes"]
    assert {(r["cost_code"], r["cost_element"]): r["account_index"] for r in rows}[("210-200", 2)] == 2301
