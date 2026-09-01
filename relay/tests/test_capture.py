"""`ucnexus-relay capture`: the read handlers are mocked, so this never touches GP - what is under test
is the shape capture writes, and that fixture_ops can then serve it.

The last test is the one that matters: a snapshot captured from (mocked) GP is loaded straight back into
fixture mode and answers a dispatch. If capture and the fixture handlers ever disagree about the format,
that is where it shows.
"""

import json
from contextlib import contextmanager

import pytest

from ucnexus_relay import capture, channel, econnect, fixture_ops
from ucnexus_relay.config import get_settings


class _Conn:
    """Stands in for a read connection. Every read is monkeypatched, so nothing reaches a cursor."""


@contextmanager
def _connect(company):
    yield _Conn()


@pytest.fixture(autouse=True)
def mocked_reads(monkeypatch):
    monkeypatch.setattr(econnect, "list_divisions", lambda conn: ["VANCOUVER"])
    monkeypatch.setattr(econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "AVERAGE"})
    monkeypatch.setattr(
        econnect,
        "list_vendors",
        lambda conn, active_only=True: [
            {
                "vendor_id": "ALLEGION",
                "vendor_name": "ALLEGION CANADA INC",
                "vendor_class": "HARDWARE",
                "status": 1,
                "currency": "CAD",
            }
        ],
    )
    monkeypatch.setattr(
        econnect,
        "get_vendor_contact",
        lambda conn, vendor_id: {
            "vendor_id": vendor_id,
            "vendor_name": "ALLEGION CANADA INC",
            "contact_name": "Dana Whitfield",
            "email": "dana@allegion.example",
        },
    )
    monkeypatch.setattr(econnect, "list_buyers_detailed", lambda conn: [{"buyer_id": "MIRA", "description": "Mira"}])
    monkeypatch.setattr(
        econnect,
        "list_tax_details",
        lambda conn: [{"tax_detail_id": "BC GST P", "description": "BC GST", "percent": 5.0}],
    )
    monkeypatch.setattr(
        econnect, "list_tax_schedules", lambda conn: [{"tax_schedule_id": "BC-TAX", "description": "BC"}]
    )
    monkeypatch.setattr(
        econnect,
        "list_employees",
        lambda conn, active_only=True: [{"employee_id": "EMP1", "first_name": "Mira", "last_name": "Vasquez"}],
    )
    monkeypatch.setattr(
        econnect, "list_customers", lambda conn: [{"customer_number": "CUST0001", "customer_name": "AGGREGATE"}]
    )
    monkeypatch.setattr(
        econnect,
        "list_customer_addresses",
        lambda conn, customer_number: [
            {"address_code": "MAIN", "address1": "1440 Powell", "city": "Vancouver", "state": "BC"}
        ],
    )
    monkeypatch.setattr(
        econnect,
        "list_cost_code_master",
        lambda conn, division: [
            {
                "cost_code": "210-200",
                "cost_code_number_1": "210",
                "cost_code_number_2": "200",
                "alias": "HDWMAT",
                "description": "HARDWARE MATERIAL",
                "cost_element": 2,
                "profit_type_number": 1,
                "type_of_transaction": 1,
                "account_index": 1201,
                "mapped": True,
            },
            {
                "cost_code": "710-000",
                "cost_code_number_1": "710",
                "cost_code_number_2": "000",
                "alias": "FRGHT",
                "description": "FREIGHT",
                "cost_element": 7,
                "profit_type_number": 1,
                "type_of_transaction": 1,
                "account_index": None,
                "mapped": False,
            },
        ],
    )
    monkeypatch.setattr(
        econnect,
        "list_jobs",
        lambda conn: [
            {"job_number": "23093", "job_name": "AGGREGATE - YARD"},
            {"job_number": "23145", "job_name": "FRASER - PHASE 2"},
        ],
    )
    monkeypatch.setattr(
        econnect,
        "get_job",
        lambda conn, job_number: {
            "job_number": job_number,
            "job_name": "X",
            "customer_number": "CUST0001",
            "job_address_code": "MAIN",
        },
    )
    monkeypatch.setattr(
        econnect,
        "list_cost_codes",
        lambda conn, job_number: [{"cost_code": "210-200", "description": "HARDWARE MATERIAL", "cost_element": 2}],
    )
    monkeypatch.setattr(
        econnect,
        "job_setup_health",
        lambda conn, job_number=None: [
            {"job_number": "23093", "ok": True, "active_cost_code_count": 1, "issues": []},
            {
                "job_number": "23145",
                "ok": False,
                "active_cost_code_count": 2,
                "issues": [{"cost_code": "310-100-3", "account_index": 1617}],
            },
        ],
    )
    monkeypatch.setattr(
        econnect,
        "read_po_totals",
        lambda conn, po_number: {
            "po_number": po_number,
            "subtotal": 100.0,
            "freight": 5.0,
            "miscellaneous": 0.0,
            "tax_amount": 5.0,
        },
    )

    def _sync_pos(conn, *, cursor, page_size, modified_since):
        # one full page then a short one, so the capture loop's paging is actually exercised
        if not cursor:
            return {
                "pos": [_po("PO0000044", "23093"), _po("PO0000056", "23093")],
                "next_cursor": "PO0000056",
            }
        return {"pos": [_po("PO0000070", "23145")], "next_cursor": None}

    monkeypatch.setattr(econnect, "sync_pos", _sync_pos)


def _po(number: str, job: str) -> dict:
    return {
        "po_number": number,
        "gp_status": 1,
        "vendor_id": "ALLEGION",
        "vendor_name": "ALLEGION CANADA INC",
        "doc_date": "2026-03-16",
        "modified_at": "2026-06-18T11:22:03",
        "source_table": "work",
        "lines": [
            {
                "ord": 16384,
                "item": "L9070",
                "itemdesc": "L9070 LOCK",
                "unit_cost": 25.0,
                "qty": 4.0,
                "qty_cancelled": 0.0,
                "job": job,
                "line_status": 1,
                "received": 0.0,
            }
        ],
    }


def test_capture_writes_a_snapshot_in_the_fixture_format(tmp_path):
    out = tmp_path / "gp-snapshot.json"
    capture.capture(["TUBC", "TUCSH"], out, connect=_connect)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["format"] == fixture_ops.SNAPSHOT_FORMAT
    assert written["version"] == fixture_ops.SNAPSHOT_VERSION
    assert sorted(written["companies"]) == ["TUBC", "TUCSH"]

    tubc = written["companies"]["TUBC"]
    assert tubc["vendors"][0]["email"] == "dana@allegion.example"
    assert tubc["divisions"] == ["VANCOUVER"]
    # JC40202 and JC40302 split apart again: the master is company-wide, the account is per division
    assert [c["cost_code"] for c in tubc["cost_code_master"]] == ["210-200", "710-000"]
    assert tubc["division_accounts"] == {"VANCOUVER": {"2": 1201}}
    assert tubc["account_indexes"] == [1201]
    # every page of sync_pos, each PO carrying the header totals read_po_totals answers with
    assert [p["po_number"] for p in tubc["purchase_orders"]] == ["PO0000044", "PO0000056", "PO0000070"]
    assert tubc["purchase_orders"][0]["totals"]["freight"] == 5.0
    # the counter starts one past the highest number captured, so a create_po cannot collide
    assert tubc["next_numbers"]["po"] == "PO0000071"


def test_capture_preserves_the_broken_cost_codes_gp_reported(tmp_path):
    out = tmp_path / "gp-snapshot.json"
    written = capture.capture(["TUBC"], out, connect=_connect)
    jobs = {j["job_number"]: j for j in written["companies"]["TUBC"]["jobs"]}

    # a usable code lands at index 0 - "GP picks the account at posting time", usable either side
    assert jobs["23093"]["cost_codes"] == [
        {
            "cost_code": "210-200",
            "cost_element": 2,
            "description": "HARDWARE MATERIAL",
            "account_index": 0,
            "inactive": False,
        }
    ]
    # the dangling one keeps the index GP named, so #425 reproduces off GP's own verdict
    assert {
        "cost_code": "310-100",
        "cost_element": 3,
        "description": None,
        "account_index": 1617,
        "inactive": False,
    } in jobs["23145"]["cost_codes"]


def test_a_captured_snapshot_is_servable(tmp_path, monkeypatch):
    """The round trip the whole command exists for: capture on the workstation, serve in the container."""
    out = tmp_path / "gp-snapshot.json"
    capture.capture(["TUBC"], out, connect=_connect)

    monkeypatch.setenv("UCNEXUS_RELAY_MODE", "fixture")
    monkeypatch.setenv("UCNEXUS_RELAY_FIXTURE_PATH", str(out))
    monkeypatch.setenv("UCNEXUS_RELAY_COMPANIES", "TUBC")
    get_settings.cache_clear()
    fixture_ops.reset_state()
    try:
        jobs = channel._dispatch("list_jobs", "TUBC", {})
        assert jobs["ok"] is True
        assert [j["job_number"] for j in jobs["result"]["jobs"]] == ["23093", "23145"]

        health = channel._dispatch("job_setup_health", "TUBC", {"job": "23145"})
        assert health["result"]["jobs"][0]["ok"] is False
        assert health["result"]["jobs"][0]["issues"] == [{"cost_code": "310-100-3", "account_index": 1617}]

        master = channel._dispatch("list_cost_code_master", "TUBC", {"division": "VANCOUVER"})
        by_key = {(c["cost_code"], c["cost_element"]): c for c in master["result"]["cost_codes"]}
        assert by_key[("210-200", 2)]["mapped"] is True
        assert by_key[("710-000", 7)]["mapped"] is False
    finally:
        get_settings.cache_clear()
        fixture_ops.reset_state()


def test_main_requires_both_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(capture.db, "get_read_connection", _connect)
    out = tmp_path / "snap.json"
    assert capture.main(["--companies", "TUBC", "--out", str(out)]) == 0
    assert out.exists()
    with pytest.raises(SystemExit):
        capture.main(["--out", str(out)])


def test_main_rejects_an_empty_company_list(tmp_path):
    assert capture.main(["--companies", " , ", "--out", str(tmp_path / "snap.json")]) == 2
