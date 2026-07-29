"""create_buyer / create_buyer_op (issue #409). No real GP: a fake cursor records each EXEC's SQL +
params and answers with a settable (error_state, err_string).

What matters here is that the EXEC carries ONLY BUYERID and DSCRIPTN - taCreateBuyer's other inputs
are defaulted, and sending them as explicit NULLs is not the same thing - and that the op's own
duplicate pre-check runs before the proc, so a re-register reads as a sentence rather than as GP's
error state 2684."""

from collections import namedtuple

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import EConnectError, create_buyer

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_CountRow = namedtuple("_CountRow", "n")
_BuyerRow = namedtuple("_BuyerRow", "buyer_id description")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        if "taCreateBuyer" in self._sql:
            return _ExecRow(self._conn.error_state, self._conn.err_string)
        if "COUNT(*)" in self._sql:
            return _CountRow(self._conn.buyer_count)  # the buyer_exists pre-check
        # the get_buyer read-back
        return None if self._conn.buyer_row is None else _BuyerRow(*self._conn.buyer_row)


class _FakeConn:
    def __init__(self, *, error_state=0, err_string="", buyer_count=0, buyer_row=None):
        self.error_state = error_state
        self.err_string = err_string
        self.buyer_count = buyer_count
        self.buyer_row = buyer_row
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def proc_calls(self):
        return [c for c in self.calls if "taCreateBuyer" in c[0]]


# --- econnect.create_buyer ---


def test_only_buyerid_and_description_reach_the_exec():
    # The proc's other inputs (RequesterTrx, USRDEFND1-5) carry defaults; sending them as explicit
    # NULLs is not the same as leaving them defaulted.
    conn = _FakeConn()
    create_buyer(conn, buyer_id="donr", description="Don Roberton")
    sql, params = conn.proc_calls()[0]

    assert "@I_vBUYERID" in sql
    assert "@I_vDSCRIPTN" in sql
    for param in ("@I_vRequesterTrx", "@I_vUSRDEFND1", "@I_vUSRDEFND2"):
        assert param not in sql
    assert params == ("donr", "Don Roberton")


def test_blank_description_is_still_sent():
    # DSCRIPTN has no meaningful GP default to preserve, so a buyer registered without one is created
    # with a blank description rather than being rejected.
    conn = _FakeConn()
    create_buyer(conn, buyer_id="donr")
    _, params = conn.proc_calls()[0]
    assert params == ("donr", "")


def test_proc_error_raises_carrying_the_error_state():
    # No proc_message here, unlike wsiJCJobMaster: taCreateBuyer IS a taXxx proc, so its error states
    # are taErrorCode entries and errors.econnect_error_body resolves a real GP description for them.
    # 2683 is that table's "Unable to insert into the Buyer Master Table - POP00101".
    conn = _FakeConn(error_state=2683, err_string="")
    with pytest.raises(EConnectError) as exc:
        create_buyer(conn, buyer_id="donr", description="Don")
    assert exc.value.proc == "taCreateBuyer"
    assert exc.value.error_state == 2683
    assert exc.value.proc_message is None


# --- econnect.buyer_exists / get_buyer ---


def test_buyer_exists_strips_the_argument():
    # BUYERID is char(15); the column is RTRIM'd, so the argument must be too or a padded id read out
    # of a dropdown fails a pre-check against the row it came from.
    conn = _FakeConn(buyer_count=1)
    assert econnect.buyer_exists(conn, "  donr  ") is True
    _, params = conn.calls[0]
    assert params == ("donr",)


def test_buyer_exists_is_false_when_absent():
    conn = _FakeConn(buyer_count=0)
    assert econnect.buyer_exists(conn, "nobody") is False


def test_get_buyer_matches_the_id_in_sql_like_the_pre_check_does():
    # The read-back has to normalize the id the SAME way buyer_exists does - RTRIM'd column, stripped
    # argument, comparison left to SQL - or the two gates disagree about what is the same buyer and a
    # create that worked gets rolled back as "reported success but not in POP00101".
    conn = _FakeConn(buyer_row=("donr", "Don Roberton"))
    assert econnect.get_buyer(conn, "  donr  ") == {"buyer_id": "donr", "description": "Don Roberton"}
    sql, params = conn.calls[0]
    assert "RTRIM(BUYERID) = ?" in sql
    assert params == ("donr",)


def test_get_buyer_is_none_when_the_row_never_landed():
    conn = _FakeConn(buyer_row=None)
    assert econnect.get_buyer(conn, "nobody") is None


# --- ops.create_buyer_op: pre-check, create, read back ---


def _request(**overrides):
    return models.CreateBuyerRequest(
        company="TUBC", **{"buyer_id": "newbuyer", "description": "New Buyer", **overrides}
    )


def _stub_read_back(monkeypatch, buyer_id="newbuyer", description="New Buyer"):
    monkeypatch.setattr(econnect, "get_buyer", lambda c, b: {"buyer_id": buyer_id, "description": description})


def test_op_creates_then_reads_back(monkeypatch):
    conn = _FakeConn()
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(econnect, "buyer_exists", lambda c, b: False)
    monkeypatch.setattr(econnect, "create_buyer", lambda c, *, buyer_id, description: seen.append((buyer_id, description)))
    _stub_read_back(monkeypatch)

    response = ops.create_buyer_op(conn, company="TUBC", request=_request())

    assert seen == [("newbuyer", "New Buyer")]
    assert response.buyer_id == "newbuyer"
    assert response.company == "TUBC"


def test_op_answers_with_gps_stored_description_not_the_request(monkeypatch):
    # DSCRIPTN is char(30) on the proc, so a longer description is truncated on write and the request
    # no longer describes the row.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "buyer_exists", lambda c, b: False)
    monkeypatch.setattr(econnect, "create_buyer", lambda c, **k: None)
    _stub_read_back(monkeypatch, description="What GP Actually Kept")

    response = ops.create_buyer_op(conn, company="TUBC", request=_request())

    assert response.description == "What GP Actually Kept"


def test_op_refuses_a_duplicate_without_calling_the_proc(monkeypatch):
    # The proc would reject it too (error state 2684), but from inside itself. Pre-empting it is what
    # turns a re-register into a sentence the dialog can show, and what makes a retry after an
    # ambiguous failure read as "already registered" rather than as a raw eConnect state.
    conn = _FakeConn()
    called = []
    monkeypatch.setattr(econnect, "buyer_exists", lambda c, b: True)
    monkeypatch.setattr(econnect, "create_buyer", lambda c, **k: called.append(k))

    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_buyer_op(conn, company="TUBC", request=_request(buyer_id="donr"))

    assert exc.value.code == "buyer_already_exists"
    assert called == []


def test_op_raises_when_the_row_never_landed(monkeypatch):
    # err=0 with no row: the silent-failure class create_po_line and create_job_op guard against.
    conn = _FakeConn()
    monkeypatch.setattr(econnect, "buyer_exists", lambda c, b: False)
    monkeypatch.setattr(econnect, "create_buyer", lambda c, **k: None)
    monkeypatch.setattr(econnect, "get_buyer", lambda c, b: None)

    with pytest.raises(EConnectError, match="not in POP00101"):
        ops.create_buyer_op(conn, company="TUBC", request=_request())


# --- CreateBuyerRequest normalization ---


def test_request_trims_both_fields():
    request = _request(buyer_id="  donr  ", description="  Don Roberton  ")
    assert request.buyer_id == "donr"
    assert request.description == "Don Roberton"


def test_request_rejects_a_whitespace_only_buyer_id():
    # It would land in POP00101 as the blank buyer list_buyers filters out: registered, invisible,
    # unusable.
    with pytest.raises(ValueError, match="buyer_id is required"):
        _request(buyer_id="   ")


def test_request_rejects_an_over_length_buyer_id():
    with pytest.raises(ValueError):
        _request(buyer_id="x" * 16)


def test_request_rejects_an_over_length_description():
    with pytest.raises(ValueError):
        _request(description="x" * 31)
