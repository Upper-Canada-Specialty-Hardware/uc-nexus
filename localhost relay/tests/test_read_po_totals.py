"""econnect.read_po_totals: coercion of the POP10100 amounts and the work -> history (POP30100)
fallback, driven by a fake pyodbc cursor so no test touches GP."""

from ucnexus_relay import econnect


class _Row:
    def __init__(self, po, subtotal, freight, misc, tax):
        self.po = po
        self.subtotal = subtotal
        self.freight = freight
        self.misc = misc
        self.tax = tax


class _Cursor:
    """Returns rows_by_table[table] for each execute(), where table is inferred from the SQL text."""

    def __init__(self, rows_by_table):
        self._rows = rows_by_table
        self._table = None

    def execute(self, sql, po_number):
        self._table = "POP10100" if "POP10100" in sql else "POP30100"
        return self

    def fetchone(self):
        return self._rows.get(self._table)


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_reads_work_table_and_coerces_amounts():
    row = _Row("PO0000056", 20, 100, 50, 75)
    conn = _Conn(_Cursor({"POP10100": row}))
    out = econnect.read_po_totals(conn, "PO0000056")
    assert out == {
        "po_number": "PO0000056",
        "subtotal": 20.0,
        "freight": 100.0,
        "miscellaneous": 50.0,
        "tax_amount": 75.0,
    }


def test_null_amounts_coerce_to_zero():
    row = _Row("PO1", None, None, None, None)
    conn = _Conn(_Cursor({"POP10100": row}))
    out = econnect.read_po_totals(conn, "PO1")
    assert out["subtotal"] == 0.0 and out["freight"] == 0.0 and out["tax_amount"] == 0.0


def test_falls_back_to_history_table():
    row = _Row("PO-HIST", 5, 0, 0, 0)
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": row}))
    out = econnect.read_po_totals(conn, "PO-HIST")
    assert out["po_number"] == "PO-HIST" and out["subtotal"] == 5.0


def test_returns_none_when_not_in_either_table():
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": None}))
    assert econnect.read_po_totals(conn, "PO-NOPE") is None
