"""create_job / create_job_op (issue #380). No real GP: a fake cursor records each EXEC's SQL + params
and answers with a settable (error_state, err_string).

What matters here is that the EXEC carries ONLY the fields the caller set - the proc takes 217
parameters, all 215 inputs defaulted, and sending an unset one as NULL is not the same as leaving it
defaulted - and that the op runs OnlyValidate=1 before the real create."""

from collections import namedtuple
from datetime import date

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import EConnectError, create_job

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_CountRow = namedtuple("_CountRow", "n")

REQUIRED = {
    "job_number": "NEXUS-380-T1",
    "job_name": "Test job",
    "division": "VANCOUVER",
    "customer_number": "ELL100",
    "job_address_code": "MAIN",
    "billto_address_code": "MAIN",
    "tax_schedule_id": "GST 5%",
    "created_date": date(2025, 9, 15),
}


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        if "wsiJCJobMaster" in self._sql:
            return _ExecRow(self._conn.error_state, self._conn.err_string)
        return _CountRow(self._conn.job_count)  # the job_exists pre-check


class _FakeConn:
    def __init__(self, *, error_state=0, err_string="", job_count=0):
        self.error_state = error_state
        self.err_string = err_string
        self.job_count = job_count
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def proc_calls(self):
        return [c for c in self.calls if "wsiJCJobMaster" in c[0]]


# --- econnect.create_job: parameter assembly ---


def test_only_supplied_parameters_reach_the_exec():
    conn = _FakeConn()
    create_job(conn, **REQUIRED)
    sql, params = conn.proc_calls()[0]

    for param in (
        "@I_vWSJobNumber",
        "@I_vWSJobName",
        "@I_vDivisions",
        "@I_vCustomerNumber",
        "@I_vJobAddressCode",
        "@I_vJobBilltoAddressCode",
        "@I_vTaxScheduleID",
        "@I_vCreatedDate",
    ):
        assert param in sql
    # none of the untouched optional parameters may appear - absent means "leave GP's default"
    for param in (
        "@I_vEstimatorID",
        "@I_vWSManagerID",
        "@I_vWSProjectNumber",
        "@I_vBillCustomerNumber",
        "@I_vUseTaxSchedule",
        "@I_vScheduleStartDate",
        "@I_vScheduledCompletionDate",
        "@I_vBidDueDate",
    ):
        assert param not in sql
    # 8 required values + the trailing OnlyValidate flag
    assert params == (
        "NEXUS-380-T1", "Test job", "VANCOUVER", "ELL100", "MAIN", "MAIN", "GST 5%", date(2025, 9, 15), 0,
    )


def test_supplied_optional_parameters_are_added_in_order():
    conn = _FakeConn()
    create_job(conn, **REQUIRED, estimator_id="EST1", bid_due_date=date(2025, 8, 1))
    sql, params = conn.proc_calls()[0]
    assert "@I_vEstimatorID" in sql
    assert "@I_vBidDueDate" in sql
    assert "@I_vWSManagerID" not in sql  # still unset
    assert params[8:] == ("EST1", date(2025, 8, 1), 0)


def test_return_error_text_is_always_requested():
    conn = _FakeConn()
    create_job(conn, **REQUIRED)
    sql, _ = conn.proc_calls()[0]
    assert "@I_vReturnErrorText = 1" in sql


def test_only_validate_flag_is_bound_last():
    conn = _FakeConn()
    create_job(conn, only_validate=True, **REQUIRED)
    sql, params = conn.proc_calls()[0]
    assert "@I_vOnlyValidate" in sql
    assert params[-1] == 1


def test_unknown_field_is_rejected_before_any_sql():
    conn = _FakeConn()
    with pytest.raises(EConnectError, match="unknown create_job field"):
        create_job(conn, **REQUIRED, nonsense="x")
    assert conn.calls == []


def test_a_required_field_arriving_as_none_is_rejected_not_dropped():
    # Dropping it would leave the proc on its own default, i.e. validate and then create something
    # other than what was asked for.
    conn = _FakeConn()
    with pytest.raises(EConnectError, match="missing required field"):
        create_job(conn, **{**REQUIRED, "division": None})
    assert conn.calls == []


def test_a_bare_call_is_rejected_before_building_sql():
    # Also covers the empty-parameter case: with no fields at all the required check fires, so the
    # EXEC is never assembled from an empty map (which would be a bare syntax error).
    conn = _FakeConn()
    with pytest.raises(EConnectError, match="missing required field"):
        create_job(conn)
    assert conn.calls == []


def test_proc_error_raises_with_the_procs_own_message():
    conn = _FakeConn(error_state=8000, err_string="Job cannot be created within a closed period")
    with pytest.raises(EConnectError) as exc:
        create_job(conn, **REQUIRED)
    assert exc.value.proc == "wsiJCJobMaster"
    assert exc.value.error_state == 8000
    # proc_message is what errors.econnect_error_body surfaces verbatim
    assert exc.value.proc_message == "Job cannot be created within a closed period"
    assert "closed period" in str(exc.value)


def test_validation_pass_failure_says_validation():
    conn = _FakeConn(error_state=1, err_string="The description field is blank.")
    with pytest.raises(EConnectError, match="validation failed"):
        create_job(conn, only_validate=True, **REQUIRED)


# --- ops.create_job_op: pre-check, then validate, then create ---


def _request(**overrides):
    return models.CreateJobRequest(company="TUBC", **{**REQUIRED, **overrides})


def _stub_read_back(monkeypatch, job_number="NEXUS-380-T1", job_name="Test job"):
    """The op reads the created row back out of JC00102; give it something to find."""
    monkeypatch.setattr(econnect, "get_job", lambda c, j: {"job_number": job_number, "job_name": job_name})


def test_op_validates_before_creating(monkeypatch):
    conn = _FakeConn()
    seen: list[bool] = []
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, *, only_validate=False, **f: seen.append(only_validate))
    _stub_read_back(monkeypatch)

    response = ops.create_job_op(conn, company="TUBC", request=_request())

    assert seen == [True, False]  # dry run first, then the real call
    assert response.job_number == "NEXUS-380-T1"
    assert response.company == "TUBC"


def test_op_answers_with_gps_stored_job_not_the_request(monkeypatch):
    # WS_Job_Name is char(31); what GP kept is what the backend snapshots onto the project, so the
    # response must carry the read-back, not the request echoed straight back.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: None)
    _stub_read_back(monkeypatch, job_name="What GP Actually Kept")

    response = ops.create_job_op(conn, company="TUBC", request=_request(job_name="What the caller typed"))

    assert response.job_name == "What GP Actually Kept"


def test_op_raises_when_the_proc_reports_success_but_no_row_landed(monkeypatch):
    # taPoLine has a known err=0-but-no-row mode; guard the job proc the same way.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: None)
    monkeypatch.setattr(econnect, "get_job", lambda c, j: None)

    with pytest.raises(EConnectError, match="not in JC00102"):
        ops.create_job_op(conn, company="TUBC", request=_request())


def test_op_sends_the_same_fields_on_both_passes(monkeypatch):
    conn = _FakeConn()
    passes: list[dict] = []
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, *, only_validate=False, **f: passes.append(f))
    _stub_read_back(monkeypatch)

    ops.create_job_op(conn, company="TUBC", request=_request(estimator_id="EST1"))

    # a dry run that validated different parameters than the real call would validate the wrong thing
    assert passes[0] == passes[1]
    assert passes[0]["estimator_id"] == "EST1"
    assert "company" not in passes[0]


def test_op_rejects_a_job_that_already_exists(monkeypatch):
    conn = _FakeConn()
    called = []
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: True)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: called.append(k))

    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_job_op(conn, company="TUBC", request=_request())

    assert exc.value.code == "job_already_exists"
    assert called == []  # the proc is never reached, so a retry cannot double-create


def test_op_lets_a_validation_failure_propagate(monkeypatch):
    conn = _FakeConn()

    def _fail(c, *, only_validate=False, **f):
        if only_validate:
            raise EConnectError("nope", proc="wsiJCJobMaster", error_state=1, proc_message="Bad division")
        raise AssertionError("the real call must not run after the dry run failed")

    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", _fail)

    with pytest.raises(EConnectError, match="nope"):
        ops.create_job_op(conn, company="TUBC", request=_request())


# --- CreateJobRequest normalization ---


def test_required_strings_are_trimmed():
    request = _request(job_number="  NEXUS-380-T2  ", job_name=" Padded ")
    assert request.job_number == "NEXUS-380-T2"
    assert request.job_name == "Padded"


def test_blank_required_string_is_rejected():
    with pytest.raises(ValueError, match="job_number is required"):
        _request(job_number="   ")


def test_blank_optional_string_becomes_unset():
    # typed-then-cleared must mean "leave GP's default", not "set it to blank"
    request = _request(estimator_id="   ")
    assert request.estimator_id is None


def test_over_length_job_number_is_rejected():
    # WS_Job_Number is char(17); SQL Server would silently truncate a longer value
    with pytest.raises(ValueError):
        _request(job_number="X" * 18)
