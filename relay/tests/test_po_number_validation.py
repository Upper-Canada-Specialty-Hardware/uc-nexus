"""PO-number availability: the read-only POP10100 / POP30100 / POP30300 check /po runs so a
client-supplied PO number already used ANYWHERE in GP (active or history) is rejected
(po_number_taken) instead of colliding mid-orchestration. No real SQL - a fake cursor returns a
canned COUNT per table and records the SQL + params for assertions."""

from collections import namedtuple

from ucnexus_relay.econnect import po_number_in_use

_Row = namedtuple("_Row", "n")


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.sqls.append(sql)
        self._conn.params.append(params)
        return self

    def fetchone(self):
        # COUNT = counts[<table>] for the query naming that table (the table tokens are distinct, so
        # at most one matches a given query), else 0.
        n = 0
        for table, count in self._conn.counts.items():
            if table in self._sql:
                n = count
        return _Row(n)


class _Conn:
    def __init__(self, counts):
        self.counts = counts
        self.sqls = []
        self.params = []

    def cursor(self):
        return _Cursor(self)


def test_free_number_checks_all_three_tables_on_the_right_columns():
    conn = _Conn({})  # present in none
    assert po_number_in_use(conn, "PO000123") is None
    assert len(conn.sqls) == 3
    assert "POP10100" in conn.sqls[0] and "PONUMBER" in conn.sqls[0]
    assert "POP30100" in conn.sqls[1] and "PONUMBER" in conn.sqls[1]
    assert "POP30300" in conn.sqls[2] and "VNDDOCNM" in conn.sqls[2]
    # the candidate PO number is bound (parameterized) on every check, never interpolated
    assert conn.params == [("PO000123",), ("PO000123",), ("PO000123",)]


def test_active_po_is_rejected():
    assert po_number_in_use(_Conn({"POP10100": 1}), "PO1") == "an active PO (POP10100.PONUMBER)"


def test_historical_po_is_rejected():
    # not active, but present in the PO history header POP30100
    assert po_number_in_use(_Conn({"POP30100": 1}), "PO1") == "a historical PO (POP30100.PONUMBER)"


def test_posted_receipt_po_is_rejected():
    # present only as a posted receipt's vendor-doc number in POP30300
    assert po_number_in_use(_Conn({"POP30300": 1}), "PO1") == "a posted PO receipt (POP30300.VNDDOCNM)"


def test_active_match_short_circuits_before_history_reads():
    # found in the very first table -> only one query runs (no needless POP30100/POP30300 reads)
    conn = _Conn({"POP10100": 1, "POP30100": 1})
    assert po_number_in_use(conn, "PO1") == "an active PO (POP10100.PONUMBER)"
    assert len(conn.sqls) == 1
