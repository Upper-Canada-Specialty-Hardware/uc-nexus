"""create_po_line writes the captured manufacturer onto taPoLine USRDEFND1 (issue #233) and binds an
explicit @I_vORD (issue #538). No real GP: a fake cursor records each EXEC's SQL + params and answers
the defensive read-back COUNT, so the tests assert USRDEFND1 is bound (RTRIM + capped at 50), blank
when no manufacturer is sent, that ORD is bound and the read-back is keyed on it rather than on the
item number, and that the err=0-but-no-row read-back guard still fires."""

from collections import namedtuple
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay.econnect import EConnectError, create_po_line

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_CountRow = namedtuple("_CountRow", "n")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        # taPoLine EXEC returns (error_state, err_string); the read-back is a COUNT(*) FROM POP10110.
        if "taPoLine" in self._sql:
            return _ExecRow(self._conn.error_state, self._conn.err_string)
        return _CountRow(self._conn.verify_count)


class _FakeConn:
    """Hands out a fresh cursor per call (like pyodbc) and records every (sql, params) executed."""

    def __init__(self, *, error_state=0, err_string="", verify_count=1):
        self.error_state = error_state
        self.err_string = err_string
        self.verify_count = verify_count
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def tapoline_call(self):
        return next(c for c in self.calls if "taPoLine" in c[0])

    def readback_call(self):
        return next(c for c in self.calls if "COUNT(*)" in c[0])


def _create(conn, **overrides):
    kwargs = dict(
        po_number="PO0000001",
        doc_date=date(2026, 7, 13),
        vendor_id="ING100",
        item_number="ML2010",
        item_description="AB123 HINGE",
        quantity=Decimal("2"),
        unit_cost=Decimal("12.50"),
        line_ord=16384,
    )
    kwargs.update(overrides)
    create_po_line(conn, **kwargs)


def test_manufacturer_binds_usrdefnd1():
    conn = _FakeConn()
    _create(conn, manufacturer="SCHLAGE")
    sql, params = conn.tapoline_call()
    assert "@I_vUSRDEFND1" in sql
    assert params[-1] == "SCHLAGE"


def test_no_manufacturer_leaves_usrdefnd1_blank():
    conn = _FakeConn()
    _create(conn)  # manufacturer defaults to None
    sql, params = conn.tapoline_call()
    assert "@I_vUSRDEFND1" in sql
    assert params[-1] == ""


def test_manufacturer_over_50_is_truncated():
    conn = _FakeConn()
    _create(conn, manufacturer="M" * 60)
    _, params = conn.tapoline_call()
    assert params[-1] == "M" * 50


def test_manufacturer_is_rtrimmed():
    conn = _FakeConn()
    _create(conn, manufacturer="SCHLAGE   ")
    _, params = conn.tapoline_call()
    assert params[-1] == "SCHLAGE"


def test_read_back_guard_still_fires_on_silent_failure():
    # taPoLine can return err=0 yet insert no POP10110 row; the read-back COUNT=0 must still raise
    # (regression guard - adding USRDEFND1 must not disturb it).
    conn = _FakeConn(verify_count=0)
    with pytest.raises(EConnectError):
        _create(conn, manufacturer="SCHLAGE")


def test_line_ord_is_bound_to_the_ord_parameter():
    # issue #538: without @I_vORD, eConnect resolves the line by item number and a repeated ITEMNMBR
    # overwrites the previous line instead of adding one.
    conn = _FakeConn()
    _create(conn, line_ord=49152)
    sql, params = conn.tapoline_call()
    assert "@I_vORD" in sql
    assert 49152 in params


def test_read_back_is_keyed_on_ord_not_item_number():
    # keying the read-back on ITEMNMBR lets the OTHER line of a truncation collision satisfy it, which
    # is precisely the overwrite #538 is about. ORD is unique per line, so the guard has to use it.
    conn = _FakeConn()
    _create(conn, line_ord=32768, item_number="DUPLICATE")
    sql, params = conn.readback_call()
    assert "ORD = ?" in sql
    assert "ITEMNMBR" not in sql
    assert params == ("PO0000001", 32768)


def test_lines_sharing_an_item_number_get_distinct_ords():
    # the PO-REQ-053 shape: three part numbers that truncate to one ITEMNMBR must still be three lines.
    conn = _FakeConn()
    for idx in (1, 2, 3):
        _create(conn, line_ord=idx * 16384, item_number="56 LC LX SG 36 8204 LSJ US32D ")
    ords = [params[4] for sql, params in conn.calls if "taPoLine" in sql]
    assert ords == [16384, 32768, 49152]


def test_line_ord_is_required():
    conn = _FakeConn()
    with pytest.raises(TypeError):
        create_po_line(
            conn,
            po_number="PO0000001",
            doc_date=date(2026, 7, 13),
            vendor_id="ING100",
            item_number="ML2010",
            item_description="AB123 HINGE",
            quantity=Decimal("2"),
            unit_cost=Decimal("12.50"),
        )
