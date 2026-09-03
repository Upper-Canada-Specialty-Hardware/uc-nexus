"""Channel op dispatch: {op, company, payload} -> {ok, result|error}. Fakes db.get_read_connection /
db.get_connection and the econnect calls they wrap - no real SQL, matching the rest of this suite's
convention of never touching GP from a test."""

from contextlib import contextmanager

import pytest

from ucnexus_relay import channel, db, econnect, ops


def _body(reply: dict) -> dict:
    """A dispatch reply without the two pacing fields every reply now carries (`cost`, `server`), so a
    test can go on asserting the exact {ok, result|error} it is actually about."""
    return {key: value for key, value in reply.items() if key not in ("cost", "server")}


class _FakeConn:
    def cursor(self):
        raise AssertionError("test should stub the econnect call directly, not hit a real cursor")

    def commit(self):
        pass

    def rollback(self):
        pass


@contextmanager
def _fake_read_connection(company):
    yield _FakeConn()


@contextmanager
def _fake_connection(company):
    yield _FakeConn()


@pytest.fixture(autouse=True)
def _no_real_sql(monkeypatch):
    monkeypatch.setattr(db, "get_read_connection", _fake_read_connection)
    monkeypatch.setattr(db, "get_connection", _fake_connection)


@pytest.fixture(autouse=True)
def _served(serving):
    """Every handler calls ops.check_company_served first, and the served set is discovered from GP
    (companies.py) rather than configured - so a dispatch test has to say what this relay found."""
    serving(["TUBC", "UBC", "UCSH"])


def test_list_vendors_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_vendors", lambda conn, active_only=True: [{"vendor_id": "V1"}])
    reply = channel._dispatch("list_vendors", "TUBC", {})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "vendors": [{"vendor_id": "V1"}]}}


def test_list_buyers_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["mira", "donr"])
    reply = channel._dispatch("list_buyers", "TUBC", {})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "buyers": ["mira", "donr"]}}


def test_list_cost_codes_requires_job():
    reply = channel._dispatch("list_cost_codes", "TUBC", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_job"


def test_list_cost_codes_routes_to_econnect_and_strips_job(monkeypatch):
    seen = {}

    def _fake(conn, job):
        seen["job"] = job
        return [{"cost_code": "210-200"}]

    monkeypatch.setattr(econnect, "list_cost_codes", _fake)
    reply = channel._dispatch("list_cost_codes", "TUBC", {"job": " 80003 "})
    assert seen["job"] == "80003"
    assert _body(reply) == {
        "ok": True,
        "result": {"company": "TUBC", "job": "80003", "cost_codes": [{"cost_code": "210-200"}]},
    }


def test_list_cost_code_master_requires_division():
    # The division is not a filter on the list - it is what decides the GL account each code would be
    # provisioned with (JC40302), so there is no sensible answer without one.
    reply = channel._dispatch("list_cost_code_master", "TUBC", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_division"


def test_list_cost_code_master_routes_to_econnect_and_strips_division(monkeypatch):
    seen = {}

    def _fake(conn, division):
        seen["division"] = division
        return [{"cost_code": "210-200", "cost_element": 2, "mapped": True}]

    monkeypatch.setattr(econnect, "list_cost_code_master", _fake)
    reply = channel._dispatch("list_cost_code_master", "TUBC", {"division": " VANCOUVER "})
    assert seen["division"] == "VANCOUVER"
    assert _body(reply) == {
        "ok": True,
        "result": {
            "company": "TUBC",
            "division": "VANCOUVER",
            "cost_codes": [{"cost_code": "210-200", "cost_element": 2, "mapped": True}],
        },
    }


def test_list_jobs_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_jobs", lambda conn: [{"job_number": "80003", "job_name": "Test"}])
    reply = channel._dispatch("list_jobs", "TUBC", {})
    assert _body(reply) == {
        "ok": True,
        "result": {"company": "TUBC", "jobs": [{"job_number": "80003", "job_name": "Test"}]},
    }


def test_read_po_totals_requires_po_number():
    reply = channel._dispatch("read_po_totals", "TUBC", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_po_number"


def test_read_po_totals_routes_to_econnect_and_strips_number(monkeypatch):
    seen = {}

    def _fake(conn, po_number):
        seen["po"] = po_number
        return {"po_number": po_number, "subtotal": 20.0, "freight": 0.0, "miscellaneous": 0.0, "tax_amount": 0.0}

    monkeypatch.setattr(econnect, "read_po_totals", _fake)
    reply = channel._dispatch("read_po_totals", "TUBC", {"po_number": "  PO0000056  "})
    assert seen["po"] == "PO0000056"
    assert reply["result"]["totals"]["subtotal"] == 20.0


def test_read_po_totals_passes_through_none_when_not_found(monkeypatch):
    monkeypatch.setattr(econnect, "read_po_totals", lambda conn, po_number: None)
    reply = channel._dispatch("read_po_totals", "TUBC", {"po_number": "PO-NOPE"})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "totals": None}}


def test_unknown_op_returns_a_clean_error():
    reply = channel._dispatch("not_a_real_op", "TUBC", {})
    assert _body(reply) == {
        "ok": False,
        "error": {"error": "unknown_op", "message": "unknown op 'not_a_real_op'", "context": {}},
    }


def test_missing_company_returns_a_clean_error():
    reply = channel._dispatch("list_vendors", "", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_company"


def test_company_not_allowed_returns_a_clean_error():
    reply = channel._dispatch("list_vendors", "NOT-A-SANDBOX", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed"


_PO_PAYLOAD = {
    "header": {"vendor_id": "ING100", "confirm_with": "mira", "doc_date": "2026-01-01"},
    "lines": [{"item_number": "I1", "item_description": "d", "quantity": 1, "unit_cost": 1}],
}

_RECEIPT_PAYLOAD = {
    "po_number": "PO0000001",
    "lines": [{"po_line_ord": 16384, "quantity": 1, "rack_location": "A1"}],
}


def test_create_po_relay_op_error_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise ops.RelayOpError("buyer_unresolved", "no buyer")

    monkeypatch.setattr(ops, "create_po_op", _raise)
    reply = channel._dispatch("create_po", "TUBC", _PO_PAYLOAD)
    assert _body(reply) == {"ok": False, "error": {"error": "buyer_unresolved", "message": "no buyer", "context": {}}}


def test_create_po_success_returns_the_response_body(monkeypatch):
    from datetime import date
    from decimal import Decimal

    from ucnexus_relay.models import CreatePoResponse

    def _fake(conn, *, company, request):
        return CreatePoResponse(
            po_number="PO0000001", company=company, lines_created=1, subtotal=Decimal("1"), doc_date=date(2026, 1, 1),
            vendor_id="ING100",
        )

    monkeypatch.setattr(ops, "create_po_op", _fake)
    reply = channel._dispatch("create_po", "TUBC", _PO_PAYLOAD)
    assert reply["ok"] is True
    assert reply["result"]["po_number"] == "PO0000001"


def test_create_receipt_econnect_error_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise econnect.EConnectError("boom", proc="taPopRcptHdrInsert", error_state=0)

    monkeypatch.setattr(ops, "create_receipt_op", _raise)
    reply = channel._dispatch("create_receipt", "TUBC", _RECEIPT_PAYLOAD)
    assert reply["ok"] is False
    assert reply["error"]["error"] == "econnect_error"


def test_create_receipt_invalid_payload_translates_cleanly():
    reply = channel._dispatch("create_receipt", "TUBC", {"po_number": "PO1"})  # missing required lines
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


# --- create-job ops (issue #380) ---

_JOB_PAYLOAD = {
    "job_number": "NEXUS-380-T1",
    "job_name": "Test job",
    "division": "VANCOUVER",
    "customer_number": "ELL100",
    "job_address_code": "MAIN",
    "billto_address_code": "MAIN",
    "tax_schedule_id": "GST 5%",
    "created_date": "2025-09-15",
}


def test_list_customers_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_customers", lambda conn: [{"customer_number": "ELL100"}])
    reply = channel._dispatch("list_customers", "TUBC", {})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "customers": [{"customer_number": "ELL100"}]}}


def test_list_customer_addresses_requires_customer():
    reply = channel._dispatch("list_customer_addresses", "TUBC", {})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_customer"


def test_list_customer_addresses_routes_to_econnect_and_strips_customer(monkeypatch):
    seen = {}

    def _fake(conn, customer):
        seen["customer"] = customer
        return [{"address_code": "MAIN"}]

    monkeypatch.setattr(econnect, "list_customer_addresses", _fake)
    reply = channel._dispatch("list_customer_addresses", "TUBC", {"customer": "  ELL100  "})
    assert seen["customer"] == "ELL100"
    assert _body(reply) == {
        "ok": True,
        "result": {"company": "TUBC", "customer": "ELL100", "addresses": [{"address_code": "MAIN"}]},
    }


def test_list_tax_schedules_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_tax_schedules", lambda conn: [{"tax_schedule_id": "GST 5%"}])
    reply = channel._dispatch("list_tax_schedules", "TUBC", {})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "tax_schedules": [{"tax_schedule_id": "GST 5%"}]}}


def test_list_employees_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(
        econnect,
        "list_employees",
        lambda conn, active_only=True: [{"employee_id": "IANB", "first_name": "Ian", "last_name": "Brown"}],
    )
    reply = channel._dispatch("list_employees", "TUBC", {})
    assert _body(reply) == {
        "ok": True,
        "result": {
            "company": "TUBC",
            "employees": [{"employee_id": "IANB", "first_name": "Ian", "last_name": "Brown"}],
        },
    }


def test_list_employees_forwards_active_only(monkeypatch):
    # The proc validates against all of UPR00100, so an inactive employee is still a legal estimator -
    # the override has to be reachable through the op, not just present on the econnect function.
    seen = {}

    def _fake(conn, active_only=True):
        seen["active_only"] = active_only
        return []

    monkeypatch.setattr(econnect, "list_employees", _fake)
    channel._dispatch("list_employees", "TUBC", {"active_only": False})
    assert seen["active_only"] is False


def test_list_divisions_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(econnect, "list_divisions", lambda conn: ["VANCOUVER"])
    reply = channel._dispatch("list_divisions", "TUBC", {})
    assert _body(reply) == {"ok": True, "result": {"company": "TUBC", "divisions": ["VANCOUVER"]}}


def test_create_job_success_returns_the_response_body(monkeypatch):
    from ucnexus_relay.models import CreateJobResponse

    def _fake(conn, *, company, request):
        return CreateJobResponse(job_number=request.job_number, job_name=request.job_name, company=company)

    monkeypatch.setattr(ops, "create_job_op", _fake)
    reply = channel._dispatch("create_job", "TUBC", _JOB_PAYLOAD)
    assert reply["ok"] is True
    # cost_codes_provisioned rides along on every create_job reply (#448); 0 when none were selected.
    assert reply["result"] == {
        "job_number": "NEXUS-380-T1",
        "job_name": "Test job",
        "company": "TUBC",
        "cost_codes_provisioned": 0,
    }


def test_create_job_already_exists_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise ops.RelayOpError("job_already_exists", "job 'NEXUS-380-T1' already exists in GP company TUBC")

    monkeypatch.setattr(ops, "create_job_op", _raise)
    reply = channel._dispatch("create_job", "TUBC", _JOB_PAYLOAD)
    assert reply["ok"] is False
    assert reply["error"]["error"] == "job_already_exists"


def test_create_job_invalid_payload_translates_cleanly():
    reply = channel._dispatch("create_job", "TUBC", {"job_number": "NEXUS-380-T1"})  # missing the rest
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


# --- buyer ops (issue #409) ---


def test_list_buyers_detailed_routes_to_econnect(monkeypatch):
    monkeypatch.setattr(
        econnect,
        "list_buyers_detailed",
        lambda conn: [{"buyer_id": "donr", "description": "Don Roberton"}],
    )
    reply = channel._dispatch("list_buyers_detailed", "TUBC", {})
    assert _body(reply) == {
        "ok": True,
        "result": {"company": "TUBC", "buyers": [{"buyer_id": "donr", "description": "Don Roberton"}]},
    }


def test_create_buyer_success_returns_the_response_body(monkeypatch):
    from ucnexus_relay.models import CreateBuyerResponse

    def _fake(conn, *, company, request):
        return CreateBuyerResponse(company=company, buyer_id=request.buyer_id, description=request.description)

    monkeypatch.setattr(ops, "create_buyer_op", _fake)
    reply = channel._dispatch("create_buyer", "TUBC", {"buyer_id": "newbuyer", "description": "New Buyer"})
    assert reply["ok"] is True
    assert reply["result"] == {"company": "TUBC", "buyer_id": "newbuyer", "description": "New Buyer"}


def test_create_buyer_already_exists_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise ops.RelayOpError("buyer_already_exists", "buyer 'donr' is already registered in GP company TUBC")

    monkeypatch.setattr(ops, "create_buyer_op", _raise)
    reply = channel._dispatch("create_buyer", "TUBC", {"buyer_id": "donr"})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "buyer_already_exists"


def test_create_buyer_invalid_payload_translates_cleanly():
    reply = channel._dispatch("create_buyer", "TUBC", {"buyer_id": "   "})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


# --- customer address create (issue #444) ---
#
# The customer key is the whole of what this handler decides. `customer` is what the read op takes and
# what the backend sends; `customer_number` is what the model and the proc parameter call it. Both are
# accepted, they must agree, and neither being usable is a clean missing_customer rather than a pydantic
# dump - the read half of this same picker answers that way and the write half should not differ.

_ADDRESS_PAYLOAD = {
    "address_code": "TOWER5",
    "address1": "1055 Dunsmuir St",
    "city": "Vancouver",
}


def _stub_address_op(monkeypatch) -> list:
    """Record the request the handler built, and answer with a response shaped off it."""
    from ucnexus_relay.models import CreateCustomerAddressResponse, CustomerAddressOut

    seen: list = []

    def _fake(conn, *, company, request):
        seen.append(request)
        return CreateCustomerAddressResponse(
            company=company,
            customer=request.customer_number,
            address=CustomerAddressOut(
                address_code=request.address_code,
                address1=request.address1,
                city=request.city,
                state=request.state or None,
            ),
        )

    monkeypatch.setattr(ops, "create_customer_address_op", _fake)
    return seen


def test_create_customer_address_takes_the_customer_key_the_read_op_uses(monkeypatch):
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch("create_customer_address", "TUBC", {**_ADDRESS_PAYLOAD, "customer": "ELL100"})
    assert reply["ok"] is True
    assert seen[0].customer_number == "ELL100"
    assert reply["result"]["customer"] == "ELL100"


def test_create_customer_address_also_takes_customer_number(monkeypatch):
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch(
        "create_customer_address", "TUBC", {**_ADDRESS_PAYLOAD, "customer_number": "ELL100"}
    )
    assert reply["ok"] is True
    assert seen[0].customer_number == "ELL100"


def test_create_customer_address_accepts_both_keys_when_they_agree(monkeypatch):
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch(
        "create_customer_address",
        "TUBC",
        {**_ADDRESS_PAYLOAD, "customer": " ELL100 ", "customer_number": "ELL100"},
    )
    assert reply["ok"] is True
    assert seen[0].customer_number == "ELL100"


def test_create_customer_address_refuses_two_customers_that_disagree(monkeypatch):
    # Not a preference to resolve: a caller that has lost track of which customer it is filing this
    # address under would otherwise put a job site on somebody else's account in GP.
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch(
        "create_customer_address",
        "TUBC",
        {**_ADDRESS_PAYLOAD, "customer": "ELL100", "customer_number": "BOSA01"},
    )
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"
    assert "disagree" in reply["error"]["message"]
    assert seen == []


def test_create_customer_address_requires_a_customer(monkeypatch):
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch("create_customer_address", "TUBC", dict(_ADDRESS_PAYLOAD))
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_customer"
    assert seen == []


def test_create_customer_address_refuses_a_blank_customer(monkeypatch):
    # Same answer _run_list_customer_addresses gives, rather than a multi-line pydantic dump.
    seen = _stub_address_op(monkeypatch)
    reply = channel._dispatch("create_customer_address", "TUBC", {**_ADDRESS_PAYLOAD, "customer": "   "})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "missing_customer"
    assert seen == []


def test_create_customer_address_invalid_payload_translates_cleanly(monkeypatch):
    # An unknown key is refused by the model (extra="forbid"), not silently dropped.
    _stub_address_op(monkeypatch)
    reply = channel._dispatch(
        "create_customer_address", "TUBC", {**_ADDRESS_PAYLOAD, "customer": "ELL100", "address3": "Floor 3"}
    )
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


def test_hello_frame_advertises_build_and_the_full_op_set():
    # Issue #315: the relay's connect frame carries its build tag and exact op-set so the backend can gate
    # a call for an op this build lacks. The op list must mirror channel._OPS - a new op added there is
    # automatically advertised, closing the parity gap that stranded list_tax_details on an old build.
    frame = channel._hello_frame()
    assert frame["type"] == "hello"
    assert frame["ops"] == sorted(channel._OPS)
    assert "list_tax_details" in frame["ops"]
    assert isinstance(frame["build"], str) and frame["build"]  # 'dev' in a checkout, a tag in a CI build
    assert isinstance(frame["version"], str) and frame["version"]


def test_hello_frame_names_the_companies_this_workstation_serves(serving):
    # ops.check_company_served refuses anything this relay did not find in GP, so a backend that does
    # not know the set can only find that out by making the call and being told no. Discovery itself is
    # covered in test_companies.py.
    serving(["TUBC", "UBC"], {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"})
    frame = channel._hello_frame()
    assert frame["companies"] == ["TUBC", "UBC"]
    assert frame["company_names"] == {"TUBC": "Test Upper Canada", "UBC": "Upper Canada"}
    assert frame["companies_error"] is None


def test_hello_frame_advertises_the_channels_feature():
    # How the backend knows this build will accept a pushed preview-channel list rather than treating
    # the frame as an unknown job.
    assert channel._hello_frame()["features"] == ["channels"]


# --- push a project's site details onto its GP job (issue #497) ---


def test_update_job_site_success_returns_the_response_body(monkeypatch):
    from ucnexus_relay.models import UpdateJobSiteResponse

    def _fake(conn, *, company, request):
        return UpdateJobSiteResponse(
            job_number=request.job_number,
            job_name=request.job_name or "",
            company=company,
            address_code="SITE-23093",
            address_created=True,
        )

    monkeypatch.setattr(ops, "update_job_site_op", _fake)
    reply = channel._dispatch(
        "update_job_site",
        "TUBC",
        {"job_number": "23093", "job_name": "Cowichan", "address1": "123 Main St", "city": "Duncan"},
    )
    assert reply["ok"] is True
    assert reply["result"] == {
        "job_number": "23093",
        "job_name": "Cowichan",
        "company": "TUBC",
        "address_code": "SITE-23093",
        "address_created": True,
    }


def test_update_job_site_needs_a_job_number():
    reply = channel._dispatch("update_job_site", "TUBC", {"job_name": "Cowichan"})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


def test_update_job_site_refuses_half_an_address():
    """A street with no city is not something GP can ship to, and writing it would leave an address
    on the job that looks filled in and is not."""
    reply = channel._dispatch("update_job_site", "TUBC", {"job_number": "23093", "address1": "123 Main St"})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "invalid_payload"


def test_update_job_site_missing_job_translates_cleanly(monkeypatch):
    def _raise(conn, *, company, request):
        raise ops.RelayOpError("job_not_found", "Job '23093' is not in TUBC")

    monkeypatch.setattr(ops, "update_job_site_op", _raise)
    reply = channel._dispatch("update_job_site", "TUBC", {"job_number": "23093", "job_name": "Cowichan"})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "job_not_found"


# --- the PO mirror's two reads --------------------------------------------------------------------


def test_sync_pos_forwards_the_open_only_page(monkeypatch):
    seen = {}

    def _fake(conn, *, cursor, page_size, modified_since, open_only):
        seen.update(cursor=cursor, page_size=page_size, modified_since=modified_since, open_only=open_only)
        return {"pos": [], "next_cursor": "PO000011"}

    monkeypatch.setattr(econnect, "sync_pos", _fake)
    reply = channel._dispatch("sync_pos", "TUBC", {"open_only": True, "cursor": "PO000010", "page_size": 50})
    assert seen == {"cursor": "PO000010", "page_size": 50, "modified_since": None, "open_only": True}
    assert reply["result"] == {"company": "TUBC", "pos": [], "next_cursor": "PO000011"}


def test_sync_pos_without_the_flag_is_still_the_backfill(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        econnect,
        "sync_pos",
        lambda conn, **kw: (seen.update(kw), {"pos": [], "next_cursor": None})[1],
    )
    channel._dispatch("sync_pos", "TUBC", {"cursor": "PO000010"})
    assert seen["open_only"] is False


def test_read_pos_by_number_routes_to_econnect(monkeypatch):
    seen = {}

    def _fake(conn, po_numbers):
        seen["po_numbers"] = po_numbers
        return {"pos": [{"po_number": "PO000005"}], "missing": ["PO000099"]}

    monkeypatch.setattr(econnect, "read_pos_by_number", _fake)
    reply = channel._dispatch("read_pos_by_number", "TUBC", {"po_numbers": ["PO000005", "PO000099"]})
    assert seen["po_numbers"] == ["PO000005", "PO000099"]
    assert reply["result"] == {
        "company": "TUBC",
        "pos": [{"po_number": "PO000005"}],
        "missing": ["PO000099"],
    }


def test_read_pos_by_number_refuses_more_than_one_batch():
    # The budget is bounded work per request. A batch bigger than a batch is refused rather than
    # quietly becoming the unbounded read this replaced.
    asked = [f"PO{i:06d}" for i in range(econnect.MAX_PO_NUMBERS + 1)]
    reply = channel._dispatch("read_pos_by_number", "TUBC", {"po_numbers": asked})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "too_many_po_numbers"
    assert reply["error"]["context"] == {"asked": 101, "maximum": econnect.MAX_PO_NUMBERS}


def test_read_pos_by_number_wants_a_list():
    reply = channel._dispatch("read_pos_by_number", "TUBC", {"po_numbers": "PO000005"})
    assert reply["error"]["error"] == "invalid_payload"


def test_read_pos_by_number_with_no_numbers_reads_nothing(monkeypatch):
    monkeypatch.setattr(econnect, "read_pos_by_number", lambda conn, po_numbers: {"pos": [], "missing": []})
    assert channel._dispatch("read_pos_by_number", "TUBC", {})["ok"] is True


def test_the_relay_advertises_the_new_read():
    # The backend refuses to call an op an older relay does not advertise, so the hello frame is what
    # lets it switch from the unpaged incremental read to the paged pair.
    ops_advertised = channel._hello_frame()["ops"]
    assert "read_pos_by_number" in ops_advertised
    assert ops_advertised == sorted(ops_advertised)


# --- job_setup_health: one job, a batch, or the whole company -------------------------------------


def _health_stub(monkeypatch, seen):
    def _fake(conn, job_number=None, job_numbers=None):
        seen.append({"job": job_number, "jobs": job_numbers})
        return [{"job_number": "23090", "ok": True, "active_cost_code_count": 3, "issues": []}]

    monkeypatch.setattr(econnect, "job_setup_health", _fake)


def test_job_setup_health_forwards_the_batch(monkeypatch):
    seen = []
    _health_stub(monkeypatch, seen)
    reply = channel._dispatch("job_setup_health", "TUBC", {"jobs": [" 23090 ", "23093", "23090"]})
    assert seen == [{"job": None, "jobs": ["23090", "23093"]}]  # trimmed and de-duplicated
    # `job` stays None for the list form - it means "the caller asked about ONE job".
    assert reply["result"]["job"] is None
    assert reply["result"]["company"] == "TUBC"
    assert reply["result"]["jobs"][0]["job_number"] == "23090"


def test_job_setup_health_batch_wins_over_the_single_job(monkeypatch):
    seen = []
    _health_stub(monkeypatch, seen)
    channel._dispatch("job_setup_health", "TUBC", {"job": "23099", "jobs": ["23090"]})
    assert seen == [{"job": None, "jobs": ["23090"]}]


def test_job_setup_health_still_answers_one_job(monkeypatch):
    seen = []
    _health_stub(monkeypatch, seen)
    reply = channel._dispatch("job_setup_health", "TUBC", {"job": " 23093 "})
    assert seen == [{"job": "23093", "jobs": None}]
    assert reply["result"]["job"] == "23093"


def test_job_setup_health_with_no_filter_is_still_the_whole_company(monkeypatch):
    # An older backend sends neither key and must keep getting the sweep it asks for.
    seen = []
    _health_stub(monkeypatch, seen)
    reply = channel._dispatch("job_setup_health", "TUBC", {})
    assert seen == [{"job": None, "jobs": None}]
    assert reply["result"]["job"] is None


def test_an_empty_batch_opens_no_connection(monkeypatch):
    opened = []

    @contextmanager
    def _counting(company):
        opened.append(company)
        yield _FakeConn()

    monkeypatch.setattr(db, "get_read_connection", _counting)
    reply = channel._dispatch("job_setup_health", "TUBC", {"jobs": []})
    assert reply["result"]["jobs"] == []
    assert opened == []  # the caller named no jobs, so GP is not touched at all


def test_job_setup_health_refuses_more_than_one_batch():
    asked = [f"J{i:05d}" for i in range(econnect.MAX_JOB_NUMBERS + 1)]
    reply = channel._dispatch("job_setup_health", "TUBC", {"jobs": asked})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "too_many_job_numbers"
    assert reply["error"]["context"] == {"asked": 101, "maximum": econnect.MAX_JOB_NUMBERS}


def test_job_setup_health_wants_a_list():
    reply = channel._dispatch("job_setup_health", "TUBC", {"jobs": "23090"})
    assert reply["error"]["error"] == "invalid_payload"
