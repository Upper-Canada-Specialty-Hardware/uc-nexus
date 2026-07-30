"""create_customer_address / create_customer_address_op (issue #444). No real GP: a fake cursor records
each EXEC's SQL + params and answers with a settable (error_state, err_string).

What matters here is that @I_vUpdateIfExists is a literal 0 in the statement - the proc would overwrite
an address accounting maintains in GP if it were 1, and no caller may reach that - and that the op's own
duplicate pre-check runs before the proc. taCreateCustomerAddress has no OnlyValidate parameter, so
unlike the job proc there is no dry-run pass behind that check: it is the entire guard.
"""

from collections import namedtuple

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import EConnectError, create_customer_address

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_CountRow = namedtuple("_CountRow", "n")
_AddressRow = namedtuple("_AddressRow", "address_code address1 city state")

FIELDS = {
    "customer_number": "ELL100",
    "address_code": "TOWER5",
    "address1": "1055 Dunsmuir St",
    "address2": "",
    "city": "Vancouver",
    "state": "BC",
    "zip_code": "V7X 1L2",
    "country": "Canada",
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
        if "taCreateCustomerAddress" in self._sql:
            return _ExecRow(self._conn.error_state, self._conn.err_string)
        if "COUNT(*)" in self._sql:
            return _CountRow(self._conn.address_count)  # the customer_address_exists pre-check
        # the get_customer_address read-back
        return None if self._conn.address_row is None else _AddressRow(*self._conn.address_row)


class _FakeConn:
    def __init__(self, *, error_state=0, err_string="", address_count=0, address_row=None):
        self.error_state = error_state
        self.err_string = err_string
        self.address_count = address_count
        self.address_row = address_row
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def proc_calls(self):
        return [c for c in self.calls if "taCreateCustomerAddress" in c[0]]


# --- econnect.create_customer_address ---


def test_the_eight_address_parameters_are_sent_in_proc_order():
    conn = _FakeConn()
    create_customer_address(conn, FIELDS)
    sql, params = conn.proc_calls()[0]

    assert sql.index("@I_vCUSTNMBR") < sql.index("@I_vADRSCODE") < sql.index("@I_vADDRESS1")
    assert sql.index("@I_vADDRESS1") < sql.index("@I_vADDRESS2") < sql.index("@I_vCITY")
    assert sql.index("@I_vCITY") < sql.index("@I_vSTATE") < sql.index("@I_vZIPCODE") < sql.index("@I_vCOUNTRY")
    assert params == (
        "ELL100", "TOWER5", "1055 Dunsmuir St", "", "Vancouver", "BC", "V7X 1L2", "Canada",
    )


def test_the_procs_other_inputs_are_left_defaulted():
    # Same treatment _exec_tapohdr gives taPoHdr's ~100: an unset optional is absent from the EXEC,
    # not an explicit NULL.
    conn = _FakeConn()
    create_customer_address(conn, FIELDS)
    sql, _ = conn.proc_calls()[0]
    for param in ("@I_vADDRESS3", "@I_vPHONE1", "@I_vSHIPMTHD", "@I_vUSRDEFND1"):
        assert param not in sql


def test_update_if_exists_is_a_hardcoded_zero():
    # The whole safety story: with 1 the proc overwrites an existing address code in place, and RM00102
    # is master data accounting maintains in GP. It must not be reachable from a caller at all.
    conn = _FakeConn()
    create_customer_address(conn, FIELDS)
    sql, params = conn.proc_calls()[0]
    assert "@I_vUpdateIfExists = 0" in sql
    assert "@I_vUpdateIfExists = ?" not in sql
    assert len(params) == 8  # no ninth value could turn it into a 1


def test_blank_optionals_are_sent_as_blanks():
    # Unlike create_job, where an unset optional means "leave GP's default": this row does not exist
    # yet, so a blank STATE is simply an address with no state.
    conn = _FakeConn()
    create_customer_address(conn, {**FIELDS, "address2": "", "state": "", "zip_code": "", "country": ""})
    _, params = conn.proc_calls()[0]
    assert params == ("ELL100", "TOWER5", "1055 Dunsmuir St", "", "Vancouver", "", "", "")


def test_a_missing_optional_key_is_sent_as_a_blank_not_a_null():
    conn = _FakeConn()
    create_customer_address(conn, {k: v for k, v in FIELDS.items() if k != "country"})
    _, params = conn.proc_calls()[0]
    assert params[-1] == ""


def test_unknown_field_is_rejected_before_any_sql():
    conn = _FakeConn()
    with pytest.raises(EConnectError, match="unknown create_customer_address field"):
        create_customer_address(conn, {**FIELDS, "nonsense": "x"})
    assert conn.calls == []


def test_a_required_field_arriving_blank_is_rejected_before_any_sql():
    conn = _FakeConn()
    with pytest.raises(EConnectError, match="missing required field"):
        create_customer_address(conn, {**FIELDS, "city": ""})
    assert conn.calls == []


def test_proc_error_raises_with_gps_own_error_string():
    # No proc_message, unlike wsiJCJobMaster: taCreateCustomerAddress IS a taXxx proc, so its states are
    # taErrorCode entries and errors.econnect_error_body resolves a real GP description for them.
    conn = _FakeConn(error_state=350, err_string="Customer Number does not exist")
    with pytest.raises(EConnectError) as exc:
        create_customer_address(conn, FIELDS)
    assert exc.value.proc == "taCreateCustomerAddress"
    assert exc.value.error_state == 350
    assert exc.value.proc_message is None
    assert "Customer Number does not exist" in str(exc.value)


# --- econnect.customer_address_exists / get_customer_address ---


def test_address_exists_is_scoped_to_the_customer_as_well_as_the_code():
    # ADRSCODE is unique PER CUSTOMER; 'MAIN' exists under nearly every customer, so a probe on the
    # code alone would refuse almost every legitimate create.
    conn = _FakeConn(address_count=1)
    assert econnect.customer_address_exists(conn, "  ELL100  ", "  MAIN  ") is True
    sql, params = conn.calls[0]
    assert "RM00102" in sql
    assert "RTRIM(CUSTNMBR) = ?" in sql
    assert "RTRIM(ADRSCODE) = ?" in sql
    assert params == ("ELL100", "MAIN")


def test_address_exists_is_false_when_absent():
    conn = _FakeConn(address_count=0)
    assert econnect.customer_address_exists(conn, "ELL100", "NOPE") is False


def test_get_customer_address_returns_a_list_shaped_row():
    conn = _FakeConn(address_row=("TOWER5", "1055 Dunsmuir St", "Vancouver", "BC"))
    assert econnect.get_customer_address(conn, "ELL100", "TOWER5") == {
        "address_code": "TOWER5",
        "address1": "1055 Dunsmuir St",
        "city": "Vancouver",
        "state": "BC",
    }
    sql, params = conn.calls[0]
    # matched the way the pre-check matches, or the two gates disagree about what is the same address
    assert "RTRIM(CUSTNMBR) = ?" in sql
    assert "RTRIM(ADRSCODE) = ?" in sql
    assert params == ("ELL100", "TOWER5")


def test_get_customer_address_maps_blanks_to_none():
    conn = _FakeConn(address_row=("TOWER5", "1055 Dunsmuir St", "", ""))
    row = econnect.get_customer_address(conn, "ELL100", "TOWER5")
    assert row["city"] is None
    assert row["state"] is None


def test_get_customer_address_is_none_when_the_row_never_landed():
    conn = _FakeConn(address_row=None)
    assert econnect.get_customer_address(conn, "ELL100", "TOWER5") is None


# --- ops.create_customer_address_op: pre-check, create, read back ---


def _request(**overrides):
    return models.CreateCustomerAddressRequest(company="TUBC", **{**FIELDS, **overrides})


def _stub_read_back(monkeypatch, **overrides):
    row = {"address_code": "TOWER5", "address1": "1055 Dunsmuir St", "city": "Vancouver", "state": "BC"}
    row.update(overrides)
    monkeypatch.setattr(econnect, "get_customer_address", lambda c, cu, a: row)


def test_op_creates_then_reads_back(monkeypatch):
    conn = _FakeConn()
    sent: list[dict] = []
    monkeypatch.setattr(econnect, "customer_address_exists", lambda c, cu, a: False)
    monkeypatch.setattr(econnect, "create_customer_address", lambda c, fields: sent.append(fields))
    _stub_read_back(monkeypatch)

    response = ops.create_customer_address_op(conn, company="TUBC", request=_request())

    assert sent[0]["customer_number"] == "ELL100"
    assert sent[0]["address_code"] == "TOWER5"
    assert "company" not in sent[0]  # the proc has no parameter for it
    assert response.company == "TUBC"
    assert response.customer == "ELL100"
    assert response.address.address_code == "TOWER5"


def test_op_answers_with_gps_stored_row_not_the_request(monkeypatch):
    # RM00102 is fixed-width char throughout, and that row is what the picker will serve on its next
    # refetch - so the response has to be the read-back, not the request echoed straight back.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "customer_address_exists", lambda c, cu, a: False)
    monkeypatch.setattr(econnect, "create_customer_address", lambda c, f: None)
    _stub_read_back(monkeypatch, address1="What GP Actually Kept", city="Burnaby")

    response = ops.create_customer_address_op(conn, company="TUBC", request=_request())

    assert response.address.address1 == "What GP Actually Kept"
    assert response.address.city == "Burnaby"


def test_op_refuses_a_duplicate_without_calling_the_proc(monkeypatch):
    # There is no OnlyValidate pass behind this check - it is the entire duplicate guard, and it is
    # what makes a retry after a lost reply safe rather than a second write attempt.
    conn = _FakeConn()
    called = []
    monkeypatch.setattr(econnect, "customer_address_exists", lambda c, cu, a: True)
    monkeypatch.setattr(econnect, "create_customer_address", lambda c, f: called.append(f))

    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_customer_address_op(conn, company="TUBC", request=_request())

    assert exc.value.code == "address_code_already_exists"
    assert "TOWER5" in exc.value.message
    assert called == []


def test_op_short_circuits_before_any_exec_of_the_proc():
    # Same guarantee as above, but through the real econnect functions rather than stubs: the fake
    # connection reports the address already there, and no EXEC may reach it.
    conn = _FakeConn(address_count=1)

    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_customer_address_op(conn, company="TUBC", request=_request())

    assert exc.value.code == "address_code_already_exists"
    assert conn.proc_calls() == []


def test_op_raises_when_the_row_never_landed(monkeypatch):
    # err=0 with no row: the silent-failure class create_po_line and create_job_op guard against.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "customer_address_exists", lambda c, cu, a: False)
    monkeypatch.setattr(econnect, "create_customer_address", lambda c, f: None)
    monkeypatch.setattr(econnect, "get_customer_address", lambda c, cu, a: None)

    with pytest.raises(EConnectError, match="not in\\s+RM00102"):
        ops.create_customer_address_op(conn, company="TUBC", request=_request())


def test_op_surfaces_a_gp_refusal_from_the_proc():
    # End to end through the real econnect path: the pre-check passes, the proc reports a state, and
    # GP's own errString is what the message carries.
    conn = _FakeConn(error_state=350, err_string="Customer Number does not exist")

    with pytest.raises(EConnectError) as exc:
        ops.create_customer_address_op(conn, company="TUBC", request=_request())

    assert exc.value.error_state == 350
    assert "Customer Number does not exist" in str(exc.value)


# --- CreateCustomerAddressRequest normalization ---


def test_required_strings_are_trimmed():
    request = _request(customer_number="  ELL100  ", address1="  1055 Dunsmuir St  ")
    assert request.customer_number == "ELL100"
    assert request.address1 == "1055 Dunsmuir St"


@pytest.mark.parametrize("field", ["customer_number", "address_code", "address1", "city"])
def test_a_blank_required_field_is_rejected(field):
    with pytest.raises(ValueError, match=f"{field} is required"):
        _request(**{field: "   "})


def test_address_code_is_uppercased():
    # GP's own codes are uppercase, and this one lands in the same picker as all of them.
    assert _request(address_code="  tower5  ").address_code == "TOWER5"


def test_blank_optionals_normalize_to_empty_strings():
    request = _request(address2=None, state="  ", zip_code=None, country=None)
    assert (request.address2, request.state, request.zip_code, request.country) == ("", "", "", "")


@pytest.mark.parametrize(
    "field,limit",
    [
        ("customer_number", 15),
        ("address_code", 15),
        ("address1", 60),
        ("address2", 60),
        ("city", 35),
        ("state", 29),
        ("zip_code", 10),
        ("country", 60),
    ],
)
def test_over_length_is_rejected_against_gps_own_width(field, limit):
    # Rejected, never truncated: the user typed this seconds ago and is looking at it, so storing
    # something other than what they saw would put a wrong address on a job nobody would re-check.
    with pytest.raises(ValueError, match=f"{field} is at most {limit} characters"):
        _request(**{field: "x" * (limit + 1)})


def test_a_value_that_trims_to_a_legal_length_is_accepted():
    # The width check runs after the trim, which is why it lives in the validator rather than in a
    # Field constraint - a Field constraint would measure the padding too.
    assert _request(address_code="  " + "X" * 15 + "  ").address_code == "X" * 15
