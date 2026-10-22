"""econnect.read_po_totals: coercion of the POP10100 amounts and the work -> history (POP30100)
fallback, driven by a fake pyodbc cursor so no test touches GP."""

from datetime import date, datetime
from decimal import Decimal

from ucnexus_relay import econnect


class _Row:
    def __init__(self, po, subtotal, freight, misc, tax, trade_discount=0):
        self.po = po
        self.subtotal = subtotal
        self.freight = freight
        self.misc = misc
        self.tax = tax
        self.trade_discount = trade_discount


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
    row = _Row("PO0000056", 20, 100, 50, 75, 4)
    conn = _Conn(_Cursor({"POP10100": row}))
    out = econnect.read_po_totals(conn, "PO0000056")
    assert out == {
        "po_number": "PO0000056",
        "subtotal": 20.0,
        "freight": 100.0,
        "miscellaneous": 50.0,
        "tax_amount": 75.0,
        "trade_discount": 4.0,
    }


def test_null_amounts_coerce_to_zero():
    row = _Row("PO1", None, None, None, None, None)
    conn = _Conn(_Cursor({"POP10100": row}))
    out = econnect.read_po_totals(conn, "PO1")
    assert out["subtotal"] == 0.0 and out["freight"] == 0.0 and out["tax_amount"] == 0.0
    assert out["trade_discount"] == 0.0


def test_reads_the_trade_discount_from_history_too():
    # #1236: a fully processed PO keeps its discount in POP30100, and the document still needs it.
    row = _Row("PO-HIST", 1000, 0, 0, 117, 100)
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": row}))
    assert econnect.read_po_totals(conn, "PO-HIST")["trade_discount"] == 100.0


def test_falls_back_to_history_table():
    row = _Row("PO-HIST", 5, 0, 0, 0)
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": row}))
    out = econnect.read_po_totals(conn, "PO-HIST")
    assert out["po_number"] == "PO-HIST" and out["subtotal"] == 5.0


def test_returns_none_when_not_in_either_table():
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": None}))
    assert econnect.read_po_totals(conn, "PO-NOPE") is None


# --- #858: the header fields the generated PO document prints ------------------------------------


class _HeaderRow:
    def __init__(self, **overrides):
        values = {
            "shipping_method": "UPS GROUND     ",
            "vendor_address_code": "PRIMARY",
            "buyer_id": "JAYP",
            "currency": "",
            "v_name": "Ace Hardware Co",
            "v_contact": "",
            "v_addr1": "1 Main St",
            "v_addr2": "",
            "v_addr3": None,
            "v_city": "Toronto",
            "v_state": "ON",
            "v_zip": "M1M 1M1",
            "v_country": "Canada",
            "ship_to_code": "WAREHOUSE",
            "s_name": "Upper Canada",
            "s_contact": "Receiving",
            "s_addr1": "2 Dock Rd",
            "s_addr2": "",
            "s_addr3": "",
            "s_city": "Vancouver",
            "s_state": "BC",
            "s_zip": "V5V 5V5",
            "s_country": "",
        }
        values.update(overrides)
        self.__dict__.update(values)


def test_read_po_header_trims_and_blanks_to_none():
    out = econnect.read_po_header(_Conn(_Cursor({"POP10100": _HeaderRow()})), "PO1")
    assert out["shipping_method"] == "UPS GROUND"
    assert out["currency"] is None
    assert out["vendor_address"] == {
        "name": "Ace Hardware Co",
        "contact": None,
        "address1": "1 Main St",
        "address2": None,
        "address3": None,
        "city": "Toronto",
        "state": "ON",
        "postal_code": "M1M 1M1",
        "country": "Canada",
    }
    assert out["ship_to_code"] == "WAREHOUSE"
    assert out["ship_to"]["name"] == "Upper Canada" and out["ship_to"]["country"] is None


def test_read_po_header_falls_back_to_history_and_none_when_missing():
    conn = _Conn(_Cursor({"POP10100": None, "POP30100": _HeaderRow(buyer_id="SAM")}))
    assert econnect.read_po_header(conn, "PO-HIST")["buyer_id"] == "SAM"
    assert econnect.read_po_header(_Conn(_Cursor({})), "PO-NOPE") is None


# --- #1858: what a create_po retry that found its PO answers with ---------------------------------


class _StoredRow:
    def __init__(self, subtotal, tax, currency, doc_date, vendor_id):
        self.subtotal = subtotal
        self.tax = tax
        self.currency = currency
        self.doc_date = doc_date
        self.vendor_id = vendor_id


def test_read_registered_po_reads_gp_stored_figures_as_decimals():
    row = _StoredRow(Decimal("25.00000"), Decimal("1.25000"), "CAD    ", datetime(2026, 9, 16), "ING100  ")
    out = econnect.read_registered_po(_Conn(_Cursor({"POP10100": row})), "PO0012300")
    assert out == {
        "subtotal": Decimal("25"),
        "tax_amount": Decimal("1.25"),
        "currency": "CAD",
        "doc_date": date(2026, 9, 16),
        "vendor_id": "ING100",
    }


def test_read_registered_po_falls_back_to_history_and_none_when_missing():
    row = _StoredRow(None, None, "", date(2026, 9, 1), "V")
    out = econnect.read_registered_po(_Conn(_Cursor({"POP30100": row})), "PO1")
    assert out["subtotal"] == 0 and out["tax_amount"] == 0 and out["currency"] is None
    assert econnect.read_registered_po(_Conn(_Cursor({})), "PO1") is None
