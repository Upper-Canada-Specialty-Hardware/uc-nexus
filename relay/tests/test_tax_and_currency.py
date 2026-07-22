"""Issue #257 GP-first currency + purchase tax-detail reads. No real SQL - a fake cursor records the
SQL + params and returns canned rows. The write procs (taPoHdr charges, taPopIvcTaxInsert) and the
ops currency guard / tax computation are verified live against TUBC; these cover the read helpers'
SQL shape and normalization."""

from collections import namedtuple
from decimal import Decimal

from ucnexus_relay.econnect import (
    get_mc_setup,
    get_tax_detail_percent,
    get_vendor_currency,
    list_tax_details,
    list_vendors,
)


class _FakeCursor:
    def __init__(self, *, one=None, many=None):
        self._one = one
        self._many = many if many is not None else []
        self.sql = None
        self.params = None

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class _FakeConn:
    def __init__(self, *, one=None, many=None):
        self.cursor_obj = _FakeCursor(one=one, many=many)

    def cursor(self):
        return self.cursor_obj


# --- get_vendor_currency (PM00200.CURNCYID, GP-first PO currency) ---

_CurRow = namedtuple("_CurRow", "cur")


def test_vendor_currency_returns_uppercased_value():
    conn = _FakeConn(one=_CurRow("USD"))
    assert get_vendor_currency(conn, "SEL101") == "USD"
    assert "PM00200" in conn.cursor_obj.sql
    assert "CURNCYID" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("SEL101",)


def test_vendor_currency_normalizes_case_and_whitespace():
    assert get_vendor_currency(_FakeConn(one=_CurRow("  cad ")), "ING100") == "CAD"


def test_vendor_currency_blank_falls_back_to_cad():
    # 3 active TUBC vendors have a blank currency -> GP functional currency (CAD)
    assert get_vendor_currency(_FakeConn(one=_CurRow("")), "V1") == "CAD"


def test_vendor_currency_missing_row_falls_back_to_cad():
    assert get_vendor_currency(_FakeConn(one=None), "GHOST") == "CAD"


# --- get_mc_setup (MC40000: functional currency + default purchasing rate type) ---

_McRow = namedtuple("_McRow", "functional purchase_rate_type")


def test_mc_setup_reads_functional_and_purchase_rate_type():
    conn = _FakeConn(one=_McRow("CAD", "BUY"))
    out = get_mc_setup(conn)
    assert out == {"functional": "CAD", "purchase_rate_type": "BUY"}
    assert "MC40000" in conn.cursor_obj.sql


def test_mc_setup_blank_purchase_rate_type_is_none():
    assert get_mc_setup(_FakeConn(one=_McRow("CAD", ""))) == {"functional": "CAD", "purchase_rate_type": None}


def test_mc_setup_no_row_defaults_to_cad_single_currency():
    # a single-currency company has no MC40000 row -> functional CAD, no rate type
    assert get_mc_setup(_FakeConn(one=None)) == {"functional": "CAD", "purchase_rate_type": None}


# --- list_tax_details (TX00201 purchase details, TXDTLTYP=2) ---

_TaxRow = namedtuple("_TaxRow", "tax_detail_id description percent")


def test_list_tax_details_filters_to_purchases_and_maps_rows():
    conn = _FakeConn(many=[
        _TaxRow("ON HST - P", "ON HST on Purchases", 13.0),
        _TaxRow("PST 7%", "", 7.0),
    ])
    out = list_tax_details(conn)
    assert "TX00201" in conn.cursor_obj.sql
    assert "TXDTLTYP = 2" in conn.cursor_obj.sql
    assert out[0] == {"tax_detail_id": "ON HST - P", "description": "ON HST on Purchases", "percent": 13.0}
    # a blank GP description maps to None, not an empty string
    assert out[1]["description"] is None


# --- get_tax_detail_percent (rate used to compute the PO tax) ---

_PctRow = namedtuple("_PctRow", "pct")


def test_tax_detail_percent_returns_decimal_for_a_purchase_detail():
    conn = _FakeConn(one=_PctRow(13))
    assert get_tax_detail_percent(conn, "ON HST - P") == Decimal("13")
    assert "TXDTLTYP = 2" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("ON HST - P",)


def test_tax_detail_percent_none_when_not_a_purchase_detail():
    # a sales-only detail (or unknown id) returns None -> ops raises a clean tax_detail_not_found
    assert get_tax_detail_percent(_FakeConn(one=None), "BC HST") is None


# --- list_vendors now carries the vendor's currency ---

_VendRow = namedtuple("_VendRow", "vendor_id vendor_name vendor_class status currency")


def test_list_vendors_includes_currency_blank_defaults_to_cad():
    conn = _FakeConn(many=[
        _VendRow("SEL101", "SELECT PRODUCTS", "USA", 1, "USD"),
        _VendRow("V2", "BLANK CUR VENDOR", "CAN", 1, ""),
    ])
    out = list_vendors(conn)
    assert out[0]["currency"] == "USD"
    assert out[1]["currency"] == "CAD"
