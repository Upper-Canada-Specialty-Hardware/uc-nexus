"""Cost-code provisioning for a job created from Nexus (issue #448): the JC40202/JC40302 master read,
the wsiJCJobDetailMSTR write, and the create_job_op step that ties them together.

The failure being fixed is that wsiJCJobMaster writes the JC00102 row and nothing else, so a job
created from Nexus had zero JC00701 cost codes - an empty register-PO dropdown, and job_setup_health's
first rule ("has at least one active cost code") failing, which quarantines the project on sight
(#425). No real GP here: a fake cursor records the SQL and answers each query in turn.

The rule these pin hardest is provenance (#427/#430): the request names WHICH cost codes the job gets,
and every value actually written - alias, description, profit/transaction type, and above all the GL
account index - is read out of GP's own master. A caller that could send an account index could post a
job's costs anywhere in the chart.
"""

from collections import namedtuple
from datetime import date

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import EConnectError, create_job_cost_code, list_cost_code_master
from ucnexus_relay.ops import RelayOpError

_MasterRow = namedtuple("_MasterRow", "cc1 cc2 alias descr elem ptype ttype account_index resolved")
_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_CountRow = namedtuple("_CountRow", "n")

REQUIRED = {
    "job_number": "NEXUS-448-T1",
    "job_name": "Test job",
    "division": "VANCOUVER",
    "customer_number": "ELL100",
    "job_address_code": "MAIN",
    "billto_address_code": "MAIN",
    "tax_schedule_id": "GST 5%",
    "created_date": date(2026, 7, 30),
}


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.calls.append((sql, params))
        return self

    def fetchall(self):
        return self._conn.rows

    def fetchone(self):
        if "JC00701" in self._sql:
            return _CountRow(self._conn.active_cost_codes)  # the provisioning read-back
        return _ExecRow(self._conn.error_state, self._conn.err_string)


class _FakeConn:
    """Answers the master read from `rows`, any proc EXEC with (error_state, err_string) and the
    JC00701 read-back with `active_cost_codes`. Keeps every (sql, params) for assertions."""

    def __init__(self, *rows, error_state=0, err_string="", active_cost_codes=0):
        self.rows = list(rows)
        self.error_state = error_state
        self.err_string = err_string
        self.active_cost_codes = active_cost_codes
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def sql(self, i=0):
        return self.calls[i][0]


def _master_row(**overrides):
    base = {
        "cc1": "210",
        "cc2": "200",
        "alias": "HOLLOW MTL",
        "descr": "Hollow metal",
        "elem": 2,
        "ptype": 1,
        "ttype": 3,
        "account_index": 96,
        "resolved": 96,
    }
    return _MasterRow(**{**base, **overrides})


# --- econnect.list_cost_code_master: the read ---


def test_the_master_read_joins_the_division_mapping_and_the_chart():
    conn = _FakeConn(_master_row())
    list_cost_code_master(conn, "VANCOUVER")
    sql = conn.sql()
    assert "dbo.JC40202" in sql
    # JC40302 is the ONLY legitimate source of the account index; JC40202's own ACTINDX is 0 on every
    # row in this company and is not the mapping.
    assert "LEFT JOIN dbo.JC40302 a ON RTRIM(a.Divisions) = ? AND a.Cost_Element = m.Cost_Element" in sql
    # ... and the chart join is what stops a sandbox whose division mapping itself dangles from
    # provisioning fresh #425 rows.
    assert "LEFT JOIN dbo.GL00105 g ON g.ACTINDX = a.ACTINDX" in sql


def test_the_division_is_bound_stripped():
    # Same normalization list_divisions applies, so a division read out of that picker matches here.
    conn = _FakeConn(_master_row())
    list_cost_code_master(conn, "  VANCOUVER ")
    assert conn.calls[0][1] == ("VANCOUVER",)


def test_a_row_assembles_the_shape_the_picker_and_the_write_both_need():
    conn = _FakeConn(_master_row())
    assert list_cost_code_master(conn, "VANCOUVER") == [
        {
            "cost_code": "210-200",
            "alias": "HOLLOW MTL",
            "description": "Hollow metal",
            "cost_element": 2,
            "profit_type_number": 1,
            "type_of_transaction": 3,
            "account_index": 96,
            "mapped": True,
        }
    ]


def test_a_blank_alias_or_description_comes_back_as_none():
    conn = _FakeConn(_master_row(alias="", descr=""))
    row = list_cost_code_master(conn, "VANCOUVER")[0]
    assert row["alias"] is None
    assert row["description"] is None


def test_a_cost_element_with_no_division_mapping_is_unmapped():
    """No JC40302 row for the element: there is nothing to provision the code with, so the picker must
    not offer it. account_index None distinguishes this from a mapping that exists and says 0."""
    conn = _FakeConn(_master_row(account_index=None, resolved=None))
    row = list_cost_code_master(conn, "VANCOUVER")[0]
    assert row["account_index"] is None
    assert row["mapped"] is False


def test_a_mapped_account_index_of_zero_is_usable():
    # 0 is "GP picks the account at posting time", which eConnect honours - the same rule
    # account_index_exists applies. Treating it as unmapped would hide most of the master.
    conn = _FakeConn(_master_row(account_index=0, resolved=None))
    row = list_cost_code_master(conn, "VANCOUVER")[0]
    assert row["account_index"] == 0
    assert row["mapped"] is True


def test_an_index_that_resolves_in_the_chart_is_mapped():
    conn = _FakeConn(_master_row(account_index=1401, resolved=1401))
    row = list_cost_code_master(conn, "VANCOUVER")[0]
    assert row["account_index"] == 1401
    assert row["mapped"] is True


def test_a_non_zero_index_absent_from_the_chart_is_unmapped():
    """The stale-sandbox defence: the division mapping itself points at an account this company does
    not have. Provisioning off it would manufacture exactly the dangling JC00701 rows #425 is about."""
    conn = _FakeConn(_master_row(account_index=1617, resolved=None))
    row = list_cost_code_master(conn, "VANCOUVER")[0]
    assert row["account_index"] == 1617
    assert row["mapped"] is False


def test_unmapped_codes_are_returned_not_filtered_out():
    # The picker greys them with a reason; a shorter list than GP's own would just look wrong.
    conn = _FakeConn(_master_row(), _master_row(cc2="300", account_index=None, resolved=None))
    assert [r["mapped"] for r in list_cost_code_master(conn, "VANCOUVER")] == [True, False]


# --- econnect.create_job_cost_code: the write ---


def _write_kwargs(**overrides):
    base = {
        "job_number": "NEXUS-448-T1",
        "cost_code_number_1": "210",
        "cost_code_number_2": "200",
        "alias": "HOLLOW MTL",
        "description": "Hollow metal",
        "cost_element": 2,
        "account_index": 96,
        "profit_type_number": 1,
        "type_of_transaction": 3,
    }
    return {**base, **overrides}


def test_update_if_exists_is_a_literal_one():
    """Not a caller parameter: every value written comes from the master, so a retry after a lost reply
    rewrites the identical row instead of failing on a duplicate."""
    conn = _FakeConn()
    create_job_cost_code(conn, **_write_kwargs())
    assert "@I_vUpdateIfExists      = 1," in conn.sql()


def test_the_error_text_is_always_requested():
    conn = _FakeConn()
    create_job_cost_code(conn, **_write_kwargs())
    assert "@I_vReturnErrorText     = 1," in conn.sql()


def test_only_validate_is_bound_and_defaults_to_a_real_write():
    conn = _FakeConn()
    create_job_cost_code(conn, **_write_kwargs())
    assert "@I_vOnlyValidate        = ?," in conn.sql()
    assert conn.calls[0][1][-1] == 0

    dry = _FakeConn()
    create_job_cost_code(dry, only_validate=True, **_write_kwargs())
    assert dry.calls[0][1][-1] == 1


def test_the_nine_inputs_are_bound_in_the_procs_parameter_order():
    conn = _FakeConn()
    create_job_cost_code(conn, **_write_kwargs())
    sql, params = conn.calls[0]
    assert "dbo.wsiJCJobDetailMSTR" in sql
    assert params == ("NEXUS-448-T1", "210", "200", "HOLLOW MTL", "Hollow metal", 2, 96, 1, 3, 0)


def test_a_proc_error_raises_with_the_procs_own_message():
    conn = _FakeConn(error_state=51000, err_string="The cost code already exists on this job.")
    with pytest.raises(EConnectError) as exc:
        create_job_cost_code(conn, **_write_kwargs())
    assert exc.value.proc == "wsiJCJobDetailMSTR"
    assert exc.value.error_state == 51000
    # The WennSoft procs number their states independently of taErrorCode, so the proc's own text is
    # what has to survive to the user (see EConnectError).
    assert exc.value.proc_message == "The cost code already exists on this job."
    assert "NEXUS-448-T1" in str(exc.value)
    assert "210-200-2" in str(exc.value)


def test_a_validation_pass_failure_says_validation():
    conn = _FakeConn(error_state=1, err_string="Invalid account index.")
    with pytest.raises(EConnectError, match="validation failed"):
        create_job_cost_code(conn, only_validate=True, **_write_kwargs())


# --- ops.create_job_op: provisioning ---


def _request(cost_codes=None, **overrides):
    return models.CreateJobRequest(
        company="TUBC", **{**REQUIRED, **overrides}, cost_codes=cost_codes or []
    )


def _stub_job_create(monkeypatch):
    """Everything create_job_op does before provisioning, stubbed to succeed."""
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: None)
    monkeypatch.setattr(
        econnect, "get_job", lambda c, j: {"job_number": REQUIRED["job_number"], "job_name": "Test job"}
    )


def _stub_master(monkeypatch, *rows):
    seen: list = []

    def _fake(conn, division):
        seen.append(division)
        return list(rows)

    monkeypatch.setattr(econnect, "list_cost_code_master", _fake)
    return seen


def _stub_writes(monkeypatch):
    written: list[dict] = []
    monkeypatch.setattr(
        econnect,
        "create_job_cost_code",
        lambda c, *, only_validate=False, **kw: written.append({"only_validate": only_validate, **kw}),
    )
    return written


def _mapped(cost_code="210-200", element=2, **overrides):
    base = {
        "cost_code": cost_code,
        "alias": "HOLLOW MTL",
        "description": "Hollow metal",
        "cost_element": element,
        "profit_type_number": 1,
        "type_of_transaction": 3,
        "account_index": 96,
        "mapped": True,
    }
    return {**base, **overrides}


def test_no_cost_codes_provisions_nothing(monkeypatch):
    """Every pre-#448 caller sends none, and for them the create path must be exactly what it was."""
    conn = _FakeConn()
    _stub_job_create(monkeypatch)
    seen = _stub_master(monkeypatch)
    written = _stub_writes(monkeypatch)

    response = ops.create_job_op(conn, company="TUBC", request=_request())

    assert response.cost_codes_provisioned == 0
    assert seen == []  # the master is not even read
    assert written == []
    assert conn.calls == []  # and no read-back either


def test_every_validation_pass_precedes_the_first_real_write(monkeypatch):
    """The eleventh code failing after ten were written leaves a half-provisioned job that only a
    rollback saves; validating the whole selection first is what makes the rollback unnecessary."""
    conn = _FakeConn(active_cost_codes=2)
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped(), _mapped(cost_code="310-000", element=3))
    written = _stub_writes(monkeypatch)

    request = _request(
        cost_codes=[
            {"cost_code": "210-200", "cost_element": 2},
            {"cost_code": "310-000", "cost_element": 3},
        ]
    )
    response = ops.create_job_op(conn, company="TUBC", request=request)

    assert [w["only_validate"] for w in written] == [True, True, False, False]
    assert [w["cost_code_number_2"] for w in written] == ["200", "000", "200", "000"]
    assert response.cost_codes_provisioned == 2


def test_the_master_is_read_for_the_jobs_own_division(monkeypatch):
    # The same cost element resolves to a different account in a different division, so the division
    # is what decides the account, not a filter on the list.
    conn = _FakeConn(active_cost_codes=1)
    _stub_job_create(monkeypatch)
    seen = _stub_master(monkeypatch, _mapped())
    _stub_writes(monkeypatch)

    ops.create_job_op(
        conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
    )

    assert seen == ["VANCOUVER"]


def test_every_written_value_comes_from_the_master(monkeypatch):
    """Provenance (#427/#430): the request names which codes, GP's configuration says what they mean.
    The account index especially - a caller that could send one could post a job's costs anywhere."""
    conn = _FakeConn(active_cost_codes=1)
    _stub_job_create(monkeypatch)
    _stub_master(
        monkeypatch,
        _mapped(
            alias="FROM GP",
            description="What GP has on file",
            account_index=1401,
            profit_type_number=2,
            type_of_transaction=4,
        ),
    )
    written = _stub_writes(monkeypatch)

    ops.create_job_op(
        conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
    )

    assert written[0] == {
        "only_validate": True,
        "job_number": "NEXUS-448-T1",
        "cost_code_number_1": "210",
        "cost_code_number_2": "200",
        "alias": "FROM GP",
        "description": "What GP has on file",
        "cost_element": 2,
        "account_index": 1401,
        "profit_type_number": 2,
        "type_of_transaction": 4,
    }


def test_a_code_that_is_not_in_the_master_is_refused(monkeypatch):
    conn = _FakeConn()
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped())
    written = _stub_writes(monkeypatch)

    with pytest.raises(RelayOpError) as exc:
        ops.create_job_op(
            conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "999-999", "cost_element": 9}])
        )

    assert exc.value.code == "cost_code_not_in_master"
    assert "999-999" in exc.value.message
    assert "JC40202" in exc.value.message
    assert "TUBC" in exc.value.message
    assert written == []


def test_the_same_code_under_a_different_element_is_a_different_code(monkeypatch):
    # cost_element is part of the identity, not a detail: 210-200 element 2 and element 5 are separate
    # JC00701 rows with separate accounts.
    conn = _FakeConn()
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped(element=2))
    _stub_writes(monkeypatch)

    with pytest.raises(RelayOpError) as exc:
        ops.create_job_op(
            conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 5}])
        )

    assert exc.value.code == "cost_code_not_in_master"


def test_a_code_with_no_usable_account_is_refused(monkeypatch):
    """Provisioning it would manufacture the dangling JC00701 row #425 is about: the job would register
    POs and then fail forever at receipt with eConnect 4612."""
    conn = _FakeConn()
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped(account_index=1617, mapped=False))
    written = _stub_writes(monkeypatch)

    with pytest.raises(RelayOpError) as exc:
        ops.create_job_op(
            conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
        )

    assert exc.value.code == "cost_code_unmapped"
    assert "210-200" in exc.value.message
    assert "VANCOUVER" in exc.value.message
    assert "JC40302" in exc.value.message
    assert written == []


def test_nothing_is_written_when_a_later_selection_is_bad(monkeypatch):
    # The whole selection is checked against the master before any pass runs, so one bad code cannot
    # get ten good ones written first.
    conn = _FakeConn()
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped())
    written = _stub_writes(monkeypatch)

    with pytest.raises(RelayOpError):
        ops.create_job_op(
            conn,
            company="TUBC",
            request=_request(
                cost_codes=[
                    {"cost_code": "210-200", "cost_element": 2},
                    {"cost_code": "999-999", "cost_element": 9},
                ]
            ),
        )

    assert written == []


def test_the_read_back_counts_the_rows_that_actually_landed(monkeypatch):
    conn = _FakeConn(active_cost_codes=1)
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped())
    _stub_writes(monkeypatch)

    ops.create_job_op(
        conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
    )

    sql, params = conn.calls[-1]
    assert "SELECT COUNT(*) AS n FROM dbo.JC00701" in sql
    assert "WS_Inactive = 0" in sql
    assert params == ("NEXUS-448-T1",)


def test_a_short_read_back_raises_naming_both_counts(monkeypatch):
    """taPoLine has a known err=0-but-no-row mode and this is the same class of proc, so a success
    report is not evidence a row landed."""
    conn = _FakeConn(active_cost_codes=1)
    _stub_job_create(monkeypatch)
    _stub_master(monkeypatch, _mapped(), _mapped(cost_code="310-000", element=3))
    _stub_writes(monkeypatch)

    request = _request(
        cost_codes=[
            {"cost_code": "210-200", "cost_element": 2},
            {"cost_code": "310-000", "cost_element": 3},
        ]
    )
    with pytest.raises(EConnectError) as exc:
        ops.create_job_op(conn, company="TUBC", request=request)

    assert exc.value.proc == "wsiJCJobDetailMSTR"
    assert "has 1 active" in str(exc.value)
    assert "expected 2" in str(exc.value)


def test_provisioning_runs_only_after_the_job_itself_landed(monkeypatch):
    """A cost code on a job that is not in JC00102 is not a thing GP can hold, and the read-back is
    what proves the job landed at all."""
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: None)
    monkeypatch.setattr(econnect, "get_job", lambda c, j: None)
    _stub_master(monkeypatch, _mapped())
    written = _stub_writes(monkeypatch)

    with pytest.raises(EConnectError, match="not in JC00102"):
        ops.create_job_op(
            conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
        )

    assert written == []


def test_the_job_proc_never_receives_the_cost_code_selection(monkeypatch):
    """cost_codes is a provisioning instruction for step 5, not a wsiJCJobMaster field. If it leaks
    into the kwargs create_job_op builds for econnect.create_job, that function's unknown-field guard
    refuses EVERY create - and the permissive `lambda c, **k` stubs in the other tests would never
    notice, which is exactly how the bug shipped once already."""
    received: list[set] = []
    monkeypatch.setattr(econnect, "job_exists", lambda c, j: False)
    monkeypatch.setattr(econnect, "create_job", lambda c, **k: received.append(set(k)))
    monkeypatch.setattr(
        econnect, "get_job", lambda c, j: {"job_number": REQUIRED["job_number"], "job_name": "Test job"}
    )
    _stub_master(monkeypatch, _mapped())
    _stub_writes(monkeypatch)
    conn = _FakeConn(active_cost_codes=1)

    ops.create_job_op(
        conn, company="TUBC", request=_request(cost_codes=[{"cost_code": "210-200", "cost_element": 2}])
    )

    assert len(received) == 2  # the dry run and the real call
    for kwargs in received:
        assert "cost_codes" not in kwargs


# --- CreateJobRequest / JobCostCodeSelection validation ---


def test_a_cost_code_selected_twice_is_rejected():
    # UpdateIfExists=1 means the second write would land on the same JC00701 row and succeed, and the
    # read-back would then fail a create that actually worked.
    with pytest.raises(ValueError, match="more than once"):
        _request(
            cost_codes=[
                {"cost_code": "210-200", "cost_element": 2},
                {"cost_code": "210-200", "cost_element": 2},
            ]
        )


def test_the_same_code_under_two_elements_is_not_a_duplicate():
    request = _request(
        cost_codes=[
            {"cost_code": "210-200", "cost_element": 2},
            {"cost_code": "210-200", "cost_element": 5},
        ]
    )
    assert len(request.cost_codes) == 2


def test_a_blank_cost_code_is_rejected():
    with pytest.raises(ValueError, match="cost_code is required"):
        _request(cost_codes=[{"cost_code": "   ", "cost_element": 2}])


def test_a_cost_code_is_trimmed():
    request = _request(cost_codes=[{"cost_code": "  210-200 ", "cost_element": 2}])
    assert request.cost_codes[0].cost_code == "210-200"


def test_cost_codes_default_to_none_selected():
    assert _request().cost_codes == []
