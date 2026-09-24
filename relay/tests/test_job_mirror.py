"""The full job record, the job's GP state, update_job, and the refusal every job write now makes (#730).

No GP: the reads run against a fake cursor that records the SQL and hands back canned rows, and the ops
run with the econnect calls around them stubbed, recording what would have been written - so a refusal
test can assert that nothing was."""

from collections import namedtuple
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ucnexus_relay import channel, db, econnect, models, ops
from ucnexus_relay.ops import RelayOpError

_JobRow = namedtuple(
    "_JobRow",
    "job_number job_name inactive customer_number customer_name job_address_code billto_address_code "
    "address1 address2 city state zip_code country division tax_schedule_id use_tax_schedule_id "
    "estimator_id estimator_first estimator_last ws_manager_id manager_first manager_last "
    "created_date schedule_start_date scheduled_completion_date bid_due_date "
    "orig_contract_amount contract_to_date total_actual_cost billed_amount_ttd retention_amount_ttd "
    "net_billed_ttd closed close_date close_user",
)

_GP_BLANK = datetime(1900, 1, 1)


def _job_row(**overrides) -> _JobRow:
    fields = dict(
        job_number="22004",
        job_name="Cowichan Hospital",
        inactive=0,
        customer_number="ELL100",
        customer_name="Ellis Don",
        job_address_code="MAIN",
        billto_address_code="BILL",
        address1="123 Main St",
        address2=None,
        city="Duncan",
        state="BC",
        zip_code="V9L 1A1",
        country="Canada",
        division="VANCOUVER",
        tax_schedule_id="GST 5%",
        use_tax_schedule_id="",
        estimator_id="",
        estimator_first=None,
        estimator_last=None,
        ws_manager_id="JSMITH",
        manager_first="Jane",
        manager_last="Smith",
        created_date=datetime(2025, 9, 15),
        schedule_start_date=_GP_BLANK,
        scheduled_completion_date=datetime(2026, 12, 1),
        bid_due_date=None,
        orig_contract_amount=Decimal("150000.00"),
        contract_to_date=Decimal("152500.50"),
        total_actual_cost=Decimal("40000.00"),
        billed_amount_ttd=Decimal("50000.00"),
        retention_amount_ttd=Decimal("5000.00"),
        net_billed_ttd=Decimal("45000.00"),
        closed=0,
        close_date=None,
        close_user=None,
    )
    fields.update(overrides)
    return _JobRow(**fields)


class _ReadCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchall(self):
        return self._conn.rows

    def fetchone(self):
        return self._conn.rows[0] if self._conn.rows else None


class _ReadConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _ReadCursor(self)


class _NoSqlConn:
    """For the op tests: every econnect call they reach is stubbed, so touching a cursor is a bug."""

    def cursor(self):
        raise AssertionError("test should stub the econnect call directly, not hit a real cursor")

    def commit(self):
        pass

    def rollback(self):
        pass


# --- list_jobs / get_job: the record ---------------------------------------------------------------


def test_list_jobs_maps_a_job_master_row_to_the_full_record():
    conn = _ReadConn([_job_row()])
    assert econnect.list_jobs(conn) == [
        {
            "job_number": "22004",
            "job_name": "Cowichan Hospital",
            "gp_job_state": "active",
            "closed_date": None,
            "closed_by": None,
            "customer_number": "ELL100",
            "customer_name": "Ellis Don",
            "job_address_code": "MAIN",
            "billto_address_code": "BILL",
            "address1": "123 Main St",
            "address2": None,
            "city": "Duncan",
            "state": "BC",
            "zip_code": "V9L 1A1",
            "country": "Canada",
            "division": "VANCOUVER",
            "tax_schedule_id": "GST 5%",
            "use_tax_schedule_id": None,
            "estimator_id": None,
            "estimator_name": None,
            "ws_manager_id": "JSMITH",
            "ws_manager_name": "Jane Smith",
            "created_date": "2025-09-15",
            # GP's blank date is 1900-01-01, which is "no date", not a date in 1900.
            "schedule_start_date": None,
            "scheduled_completion_date": "2026-12-01",
            "bid_due_date": None,
            "orig_contract_amount": 150000.0,
            "contract_to_date": 152500.5,
            "total_actual_cost": 40000.0,
            "billed_amount_ttd": 50000.0,
            "retention_amount_ttd": 5000.0,
            "net_billed_ttd": 45000.0,
        }
    ]


def test_list_jobs_reads_both_tables_in_one_statement():
    # GP READ LIMIT: one statement per company per pass, whichever table a job is in.
    conn = _ReadConn([])
    econnect.list_jobs(conn)
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "dbo.JC00102" in sql
    assert "dbo.JC30001" in sql
    assert "UNION ALL" in sql
    assert params == ()
    # Everything named off the job row is a LEFT JOIN, so a job with a blank estimator or a dangling
    # address code is still listed.
    for table in ("RM00101", "RM00102", "UPR00100"):
        assert f"LEFT JOIN dbo.{table}" in sql
    assert " JOIN " not in sql.replace("LEFT JOIN", "")


def test_list_jobs_marks_an_inactive_job():
    conn = _ReadConn([_job_row(inactive=1)])
    assert econnect.list_jobs(conn)[0]["gp_job_state"] == "inactive"


def test_list_jobs_serves_a_closed_job_from_the_history_table_with_its_close_stamp():
    conn = _ReadConn([_job_row(closed=1, inactive=0, close_date=datetime(2026, 9, 1), close_user="sa")])
    record = econnect.list_jobs(conn)[0]
    assert record["gp_job_state"] == "closed"
    assert record["closed_date"] == "2026-09-01"
    assert record["closed_by"] == "sa"


def test_list_jobs_closed_wins_over_the_inactive_flag():
    # JC30001 carries WS_Inactive too; a job moved there is closed whatever that flag says.
    conn = _ReadConn([_job_row(closed=1, inactive=1, close_date=_GP_BLANK, close_user="")])
    record = econnect.list_jobs(conn)[0]
    assert record["gp_job_state"] == "closed"
    assert record["closed_date"] is None
    assert record["closed_by"] is None


def test_list_jobs_names_an_employee_with_only_one_name_part():
    conn = _ReadConn([_job_row(estimator_id="BOB", estimator_first="", estimator_last="Builder")])
    assert econnect.list_jobs(conn)[0]["estimator_name"] == "Builder"


def test_get_job_filters_both_halves_and_prefers_the_job_master():
    conn = _ReadConn([_job_row()])
    record = econnect.get_job(conn, "  22004 ")
    assert record["job_number"] == "22004"
    # The older callers' four keys are still there.
    assert {"job_number", "job_name", "customer_number", "job_address_code"} <= set(record)
    sql, params = conn.calls[0]
    assert params == ("22004", "22004")
    assert sql.count("WHERE RTRIM(j.WS_Job_Number) = ?") == 2
    assert sql.rstrip().endswith("ORDER BY closed")


def test_get_job_answers_none_for_a_job_in_neither_table():
    assert econnect.get_job(_ReadConn([]), "NOPE") is None


def test_get_job_reads_a_closed_job():
    conn = _ReadConn([_job_row(closed=1, close_date=datetime(2026, 9, 1), close_user="sa")])
    assert econnect.get_job(conn, "22004")["gp_job_state"] == "closed"


# --- job_state ---------------------------------------------------------------------------------------

_StateRow = namedtuple("_StateRow", "inactive closed")


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (_StateRow(0, 0), "active"),
        (_StateRow(1, 0), "inactive"),
        (_StateRow(None, 1), "closed"),
        (_StateRow(None, 0), None),
        # A number in both tables: the job master row is the one accounting can still see and edit.
        (_StateRow(0, 1), "active"),
    ],
)
def test_job_state(row, expected):
    conn = _ReadConn([row])
    assert econnect.job_state(conn, " 22004 ") == expected
    sql, params = conn.calls[0]
    assert "dbo.JC00102" in sql and "dbo.JC30001" in sql
    assert params == ("22004", "22004")


# --- the refusal: create_po ---------------------------------------------------------------------------


def _job_cost_po() -> models.CreatePoRequest:
    return models.CreatePoRequest(
        company="TUBC",
        header=models.POHeader(
            vendor_id="ING100", buyer_id="MIRA", confirm_with="mira", doc_date=date(2026, 9, 24), site="VANCOUVER"
        ),
        lines=[
            models.POLine(
                item_number="ML2010",
                item_description="ML2010 LOCK",
                quantity=Decimal("2"),
                unit_cost=Decimal("12.50"),
                product_indicator=2,
                job_number="22004",
                cost_code="210-200-2",
            )
        ],
    )


@pytest.fixture
def po_writes(monkeypatch):
    """Everything create_po_op reads before the job check, stubbed to pass; everything it writes,
    recorded. Returns the record of writes."""
    writes: list[str] = []
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["MIRA"])
    monkeypatch.setattr(econnect, "shipping_method_exists", lambda conn, method: True)
    monkeypatch.setattr(econnect, "site_exists", lambda conn, site: True)
    monkeypatch.setattr(econnect, "vendor_address_exists", lambda conn, vendor, code: True)
    monkeypatch.setattr(econnect, "get_vendor_currency", lambda conn, vendor_id: "CAD")
    monkeypatch.setattr(econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "BUY"})
    monkeypatch.setattr(econnect, "cost_code_on_job", lambda conn, job, code: True)
    monkeypatch.setattr(econnect, "get_next_po_number", lambda conn: writes.append("number") or "PO1")
    monkeypatch.setattr(econnect, "create_po_header", lambda conn, **kw: writes.append("header"))
    monkeypatch.setattr(econnect, "create_po_line", lambda conn, **kw: writes.append("line"))
    return writes


@pytest.mark.parametrize(
    ("state", "code", "message"),
    [
        ("inactive", "job_inactive", "job 22004 is inactive in GP"),
        ("closed", "job_closed", "job 22004 is closed in GP"),
        (None, "job_not_registered", "job '22004' is not a registered GP job (JC00102) for TUBC"),
    ],
)
def test_create_po_refuses_a_job_gp_would_not_take_before_writing(monkeypatch, po_writes, state, code, message):
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: state)
    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_job_cost_po())
    assert excinfo.value.code == code
    assert excinfo.value.message == message
    assert excinfo.value.context["job_number"] == "22004"
    assert po_writes == []


# --- the refusal: create_receipt ------------------------------------------------------------------------


def _receipt_context(jobs_by_ord: dict[int, str]):
    lines = {
        ord_: {
            "item": "ML2010",
            "itemdesc": "ML2010 LOCK",
            "vendor": "ING100",
            "job": job,
            "jobname": None,
            "locn": "VANCOUVER",
            "noninven": 1,
            "uofm": "Each",
            "vnditnum": "ML2010",
            "qtyorder": Decimal("5"),
            "unitcost": Decimal("12.50"),
            "polnesta": 2,
            "prev_received": Decimal("0"),
        }
        for ord_, job in jobs_by_ord.items()
    }
    return "ING100", "Ingersoll", lines


def _receipt_request(*ords) -> models.ReceiptRequest:
    return models.ReceiptRequest(
        company="TUBC",
        po_number="PO1",
        lines=[models.ReceiptLine(po_line_ord=o, quantity=Decimal("1"), rack_location="A1") for o in ords],
    )


@pytest.fixture
def receipt_writes(monkeypatch):
    writes: list[str] = []
    monkeypatch.setattr(econnect, "po_lines_with_dangling_account", lambda conn, po: [])
    monkeypatch.setattr(econnect, "get_next_receipt_number", lambda conn: writes.append("number") or "RCT1")
    monkeypatch.setattr(econnect, "create_receipt_line", lambda conn, **kw: writes.append("line"))
    monkeypatch.setattr(econnect, "create_receipt_header", lambda conn, **kw: writes.append("header"))
    return writes


def test_create_receipt_refuses_a_closed_job_on_a_line_being_received(monkeypatch, receipt_writes):
    monkeypatch.setattr(
        econnect, "read_po_receipt_context", lambda conn, po: _receipt_context({16384: "22004", 32768: "23093"})
    )
    states = {"22004": "active", "23093": "closed"}
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: states[job])

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_receipt_op(_NoSqlConn(), company="TUBC", request=_receipt_request(16384, 32768))

    assert excinfo.value.code == "job_closed"
    assert excinfo.value.message == "job 23093 is closed in GP"
    assert receipt_writes == []


def test_create_receipt_checks_each_job_once_and_skips_lines_with_no_job(monkeypatch, receipt_writes):
    monkeypatch.setattr(
        econnect,
        "read_po_receipt_context",
        lambda conn, po: _receipt_context({16384: "22004", 32768: "22004", 49152: ""}),
    )
    asked: list[str] = []
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: asked.append(job) or "active")

    response = ops.create_receipt_op(_NoSqlConn(), company="TUBC", request=_receipt_request(16384, 32768, 49152))

    assert asked == ["22004"]
    assert response.receipt_number == "RCT1"


def test_create_receipt_ignores_an_inactive_job_on_a_line_nobody_is_receiving(monkeypatch, receipt_writes):
    monkeypatch.setattr(
        econnect, "read_po_receipt_context", lambda conn, po: _receipt_context({16384: "22004", 32768: "23093"})
    )
    states = {"22004": "active", "23093": "inactive"}
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: states[job])

    response = ops.create_receipt_op(_NoSqlConn(), company="TUBC", request=_receipt_request(16384))
    assert response.lines_received == 1


# --- update_job ---------------------------------------------------------------------------------------


@pytest.fixture
def job_writes(monkeypatch):
    """The reads update_job_op and update_job_site_op make, answering with an active job under ELL100,
    and every write they could make, recorded in order."""
    writes: list[tuple] = []
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: "active")
    monkeypatch.setattr(
        econnect,
        "get_job",
        lambda conn, job: {
            "job_number": job,
            "job_name": "Cowichan Hospital",
            "customer_number": "ELL100",
            "job_address_code": "MAIN",
        },
    )
    monkeypatch.setattr(econnect, "customer_address_exists", lambda conn, customer, code: False)
    monkeypatch.setattr(
        econnect, "create_customer_address", lambda conn, fields: writes.append(("address", dict(fields)))
    )
    monkeypatch.setattr(
        econnect,
        "update_job",
        lambda conn, *, only_validate=False, **fields: writes.append(("job", only_validate, dict(fields))),
    )
    return writes


def _update(**fields) -> models.UpdateJobRequest:
    return models.UpdateJobRequest(company="TUBC", job_number="22004", **fields)


@pytest.mark.parametrize(
    ("state", "code"), [("inactive", "job_inactive"), ("closed", "job_closed"), (None, "job_not_registered")]
)
def test_update_job_refuses_before_writing(monkeypatch, job_writes, state, code):
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: state)
    with pytest.raises(RelayOpError) as excinfo:
        ops.update_job_op(
            _NoSqlConn(), company="TUBC", request=_update(job_name="Renamed", address1="1 A St", city="X")
        )
    assert excinfo.value.code == code
    assert excinfo.value.context["job_number"] == "22004"
    assert job_writes == []


def test_update_job_sends_only_what_the_request_set(job_writes):
    response = ops.update_job_op(
        _NoSqlConn(),
        company="TUBC",
        request=_update(job_name="Renamed", use_tax_schedule_id="PST", bid_due_date=date(2026, 10, 1)),
    )
    expected = {
        "job_number": "22004",
        "job_name": "Renamed",
        # The proc builder's name for @I_vUseTaxSchedule.
        "use_tax_schedule": "PST",
        "bid_due_date": date(2026, 10, 1),
    }
    # Validate, then write, with the exact same fields.
    assert job_writes == [("job", True, expected), ("job", False, expected)]
    assert response.model_dump(mode="json")["job"]["job_number"] == "22004"


def test_update_job_treats_a_blank_field_as_absent(job_writes):
    ops.update_job_op(_NoSqlConn(), company="TUBC", request=_update(job_name="Renamed", estimator_id="   "))
    assert "estimator_id" not in job_writes[0][2]


def test_update_job_with_nothing_to_change_writes_nothing(job_writes):
    response = ops.update_job_op(_NoSqlConn(), company="TUBC", request=_update())
    assert job_writes == []
    assert response.job["job_number"] == "22004"


def test_update_job_mints_a_site_address_the_way_update_job_site_does(job_writes):
    ops.update_job_op(_NoSqlConn(), company="TUBC", request=_update(address1="1 Trunk Rd", city="Duncan"))
    assert job_writes[0] == (
        "address",
        {
            "customer_number": "ELL100",
            "address_code": "SITE-22004",
            "address1": "1 Trunk Rd",
            "address2": "",
            "city": "Duncan",
            "state": "",
            "zip_code": "",
            "country": "",
        },
    )
    assert job_writes[1] == ("job", True, {"job_number": "22004", "job_address_code": "SITE-22004"})


def test_update_job_mints_the_site_under_the_new_customer(job_writes):
    ops.update_job_op(
        _NoSqlConn(),
        company="TUBC",
        request=_update(customer_number="SCO100", billto_address_code="PRIMARY", address1="1 Trunk Rd", city="Duncan"),
    )
    assert job_writes[0][1]["customer_number"] == "SCO100"
    assert job_writes[1][2] == {
        "job_number": "22004",
        "customer_number": "SCO100",
        "job_address_code": "SITE-22004",
        "billto_address_code": "PRIMARY",
    }


def test_update_job_request_needs_both_address_codes_with_a_new_customer():
    with pytest.raises(ValidationError, match="billto_address_code"):
        _update(customer_number="SCO100", job_address_code="MAIN")
    with pytest.raises(ValidationError, match="job_address_code or a new site address"):
        _update(customer_number="SCO100", billto_address_code="MAIN")
    # A new site address stands in for the job address code, never for the bill-to.
    _update(customer_number="SCO100", billto_address_code="MAIN", address1="1 Trunk Rd", city="Duncan")
    with pytest.raises(ValidationError, match="billto_address_code"):
        _update(customer_number="SCO100", address1="1 Trunk Rd", city="Duncan")
    _update(customer_number="SCO100", job_address_code="MAIN", billto_address_code="MAIN")


def test_update_job_request_refuses_half_an_address_and_a_code_beside_a_new_address():
    with pytest.raises(ValidationError, match="together"):
        _update(address1="1 Trunk Rd")
    with pytest.raises(ValidationError, match="not both"):
        _update(job_address_code="MAIN", address1="1 Trunk Rd", city="Duncan")


def test_update_job_request_refuses_unknown_and_over_length_fields():
    with pytest.raises(ValidationError):
        _update(created_date=date(2026, 1, 1))
    with pytest.raises(ValidationError, match="31"):
        _update(job_name="x" * 32)


# --- update_job_site keeps working, and refuses the same jobs ---------------------------------------------


@pytest.mark.parametrize(("state", "code"), [("inactive", "job_inactive"), ("closed", "job_closed")])
def test_update_job_site_refuses_before_writing(monkeypatch, job_writes, state, code):
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: state)
    request = models.UpdateJobSiteRequest(
        company="TUBC", job_number="22004", job_name="Renamed", address1="1 Trunk Rd", city="Duncan"
    )
    with pytest.raises(RelayOpError) as excinfo:
        ops.update_job_site_op(_NoSqlConn(), company="TUBC", request=request)
    assert excinfo.value.code == code
    assert job_writes == []


def test_update_job_site_still_mints_and_repoints(job_writes):
    request = models.UpdateJobSiteRequest(
        company="TUBC", job_number="22004", address_code="site-x", address1="1 Trunk Rd", city="Duncan"
    )
    response = ops.update_job_site_op(_NoSqlConn(), company="TUBC", request=request)
    assert job_writes[0][1]["address_code"] == "SITE-X"
    assert job_writes[1] == ("job", True, {"job_number": "22004", "job_address_code": "SITE-X"})
    assert response.address_created is True


# --- a second site edit: the job's own code is rewritten in place, nobody else's ever is ---------------


_STORED = {
    "address1": "1 Trunk Rd",
    "address2": "",
    "city": "Duncan",
    "state": "",
    "zip_code": "",
    "country": "",
}


@pytest.fixture
def existing_site(monkeypatch, job_writes):
    """The address code already exists and holds _STORED; in-place rewrites are recorded with the rest."""
    monkeypatch.setattr(econnect, "customer_address_exists", lambda conn, customer, code: True)
    monkeypatch.setattr(econnect, "get_customer_address_lines", lambda conn, customer, code: dict(_STORED))
    monkeypatch.setattr(
        econnect,
        "update_job_site_customer_address",
        lambda conn, fields: job_writes.append(("address_update", dict(fields))),
    )
    return job_writes


@pytest.mark.parametrize("address_code", [None, "site-22004"])
def test_update_job_site_rewrites_the_jobs_own_code_in_place(existing_site, address_code):
    request = models.UpdateJobSiteRequest(
        company="TUBC", job_number="22004", address_code=address_code, address1="9 New Rd", city="Duncan"
    )
    response = ops.update_job_site_op(_NoSqlConn(), company="TUBC", request=request)
    assert existing_site[0] == (
        "address_update",
        {**_STORED, "address1": "9 New Rd", "customer_number": "ELL100", "address_code": "SITE-22004"},
    )
    assert existing_site[1] == ("job", True, {"job_number": "22004", "job_address_code": "SITE-22004"})
    assert response.address_created is False


def test_update_job_rewrites_the_jobs_own_code_in_place(existing_site):
    ops.update_job_op(_NoSqlConn(), company="TUBC", request=_update(address1="9 New Rd", city="Victoria"))
    kind, fields = existing_site[0]
    assert kind == "address_update"
    assert (fields["address_code"], fields["address1"], fields["city"]) == ("SITE-22004", "9 New Rd", "Victoria")


def test_an_identical_re_push_writes_no_address(existing_site):
    request = models.UpdateJobSiteRequest(company="TUBC", job_number="22004", address1="1 Trunk Rd", city="Duncan")
    ops.update_job_site_op(_NoSqlConn(), company="TUBC", request=request)
    assert [w[0] for w in existing_site] == ["job", "job"]


def test_any_other_existing_code_is_never_rewritten(existing_site, monkeypatch):
    # A caller-named code that is not the job's own is an address accounting keeps, maybe shared.
    monkeypatch.setattr(
        econnect,
        "get_customer_address_lines",
        lambda conn, customer, code: pytest.fail("another code's contents must not even be compared"),
    )
    request = models.UpdateJobSiteRequest(
        company="TUBC", job_number="22004", address_code="MAIN", address1="9 New Rd", city="Duncan"
    )
    ops.update_job_site_op(_NoSqlConn(), company="TUBC", request=request)
    assert [w[0] for w in existing_site] == ["job", "job"]
    assert existing_site[0][2] == {"job_number": "22004", "job_address_code": "MAIN"}


class _ProcCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        return namedtuple("_ExecRow", "error_state err_string")(0, "")


class _ProcConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _ProcCursor(self)


def test_the_own_site_rewrite_is_the_create_statement_with_update_if_exists_one():
    fields = {**_STORED, "customer_number": "ELL100", "address_code": "SITE-22004"}
    create, rewrite = _ProcConn(), _ProcConn()
    econnect.create_customer_address(create, fields)
    econnect.update_job_site_customer_address(rewrite, fields)
    (create_sql, create_params), (rewrite_sql, rewrite_params) = create.calls[0], rewrite.calls[0]
    assert "@I_vUpdateIfExists = 0" in create_sql
    assert "@I_vUpdateIfExists = 1" in rewrite_sql
    assert rewrite_sql.replace("@I_vUpdateIfExists = 1", "@I_vUpdateIfExists = 0") == create_sql
    assert rewrite_params == create_params


# --- the channel ---------------------------------------------------------------------------------------------


@pytest.fixture
def served(monkeypatch, serving):
    @contextmanager
    def _connection(company):
        yield _NoSqlConn()

    monkeypatch.setattr(db, "get_connection", _connection)
    serving(["TUBC"])


def test_hello_frame_advertises_the_job_mirror_feature():
    assert channel.JOB_MIRROR_FEATURE == "job_mirror"
    frame = channel._hello_frame()
    assert "job_mirror" in frame["features"]
    assert "update_job" in frame["ops"]


def test_update_job_dispatch_returns_the_job_record(served, job_writes):
    reply = channel._dispatch("update_job", "TUBC", {"job_number": "22004", "job_name": "Renamed"})
    assert reply["ok"] is True
    assert reply["result"]["job"]["job_number"] == "22004"


def test_update_job_dispatch_translates_a_refusal(served, job_writes, monkeypatch):
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: "inactive")
    reply = channel._dispatch("update_job", "TUBC", {"job_number": "22004", "job_name": "Renamed"})
    assert reply["ok"] is False
    assert reply["error"]["error"] == "job_inactive"
    assert job_writes == []
