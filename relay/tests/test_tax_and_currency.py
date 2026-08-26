"""Issue #257 GP-first currency + purchase tax-detail reads. No real SQL - a fake cursor records the
SQL + params and returns canned rows. The write procs (taPoHdr charges, taPopIvcTaxInsert) and the
ops currency guard / tax computation are verified live against TUBC; these cover the read helpers'
SQL shape and normalization."""

from collections import namedtuple
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import models, ops
from ucnexus_relay.econnect import (
    get_mc_setup,
    get_tax_detail_percent,
    get_vendor_currency,
    has_exchange_rate,
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

# The percent column comes back under the alias `pct`, not `percent` - PERCENT is a reserved SQL Server
# keyword, so the query aliases TXDTLPCT AS pct (see the assertion below, issue #315 follow-up).
_TaxRow = namedtuple("_TaxRow", "tax_detail_id description pct")


def test_list_tax_details_filters_to_purchases_and_maps_rows():
    conn = _FakeConn(many=[
        _TaxRow("ON HST - P", "ON HST on Purchases", 13.0),
        _TaxRow("PST 7%", "", 7.0),
    ])
    out = list_tax_details(conn)
    assert "TX00201" in conn.cursor_obj.sql
    assert "TXDTLTYP = 2" in conn.cursor_obj.sql
    # Regression guard (issue #315 follow-up): PERCENT is a reserved SQL Server keyword, so a bare
    # `AS percent` throws "Incorrect syntax near the keyword 'percent'" against real GP and the dropdown
    # never loads. The alias must stay a non-reserved word (pct).
    assert "as pct" in conn.cursor_obj.sql.lower()
    assert "as percent" not in conn.cursor_obj.sql.lower()
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


# --- has_exchange_rate (#632 preflight: MC40100 table header -> MC00100 maintained rates) ---

_RateRow = namedtuple("_RateRow", "ok")


def test_has_exchange_rate_true_when_a_row_matches():
    conn = _FakeConn(one=_RateRow(1))
    assert has_exchange_rate(conn, currency="USD", rate_type="AVERAGE", on_date=date(2026, 8, 26)) is True
    sql = conn.cursor_obj.sql
    # the join GP itself resolves through: exchange table header (currency + rate type) -> rates
    assert "MC40100" in sql
    assert "MC00100" in sql
    assert "EXGTBLID" in sql
    assert conn.cursor_obj.params == ("USD", "AVERAGE", date(2026, 8, 26), date(2026, 8, 26))


def test_has_exchange_rate_false_when_no_row():
    # TUBC's live state for USD: no exchange table maintained at all
    assert has_exchange_rate(_FakeConn(one=None), currency="USD", rate_type="AVERAGE", on_date=date(2026, 8, 26)) is False


# --- create_po_op currency preflight ordering (#632) ---


def _usd_po_request():
    return models.CreatePoRequest(
        company="TUBC",
        header=models.POHeader(
            vendor_id="SEL101",
            buyer_id="BUYER1",
            confirm_with="test",
            doc_date=date(2026, 8, 26),
        ),
        lines=[
            models.POLine(
                item_number="HINGE",
                item_description="A hinge",
                quantity=Decimal(1),
                unit_cost=Decimal(1),
            )
        ],
    )


def test_create_po_raises_no_exchange_rate_before_taPoHdr(monkeypatch):
    monkeypatch.setattr(ops.econnect, "list_buyers", lambda conn: ["BUYER1"])
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "USD")
    monkeypatch.setattr(ops.econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "AVERAGE"})
    monkeypatch.setattr(ops.econnect, "has_exchange_rate", lambda conn, **kw: False)
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(object(), company="TUBC", request=_usd_po_request())
    assert exc.value.code == "no_exchange_rate"
    assert "USD" in exc.value.message
    assert "AVERAGE" in exc.value.message


def test_create_po_no_rate_type_still_raises_rate_type_unresolved(monkeypatch):
    # no purchasing rate type configured -> the older, more fundamental error; the rate lookup is
    # never attempted (it has no rate type to look up under)
    monkeypatch.setattr(ops.econnect, "list_buyers", lambda conn: ["BUYER1"])
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "USD")
    monkeypatch.setattr(ops.econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": None})

    def _boom(conn, **kw):
        raise AssertionError("has_exchange_rate must not be called without a rate type")

    monkeypatch.setattr(ops.econnect, "has_exchange_rate", _boom)
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(object(), company="TUBC", request=_usd_po_request())
    assert exc.value.code == "rate_type_unresolved"


def test_create_po_rate_present_clears_the_preflight(monkeypatch):
    # with a rate maintained the currency block passes; the op then proceeds past it (here: into the
    # header write, stubbed to stop the test at the first SQL touch)
    monkeypatch.setattr(ops.econnect, "list_buyers", lambda conn: ["BUYER1"])
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "USD")
    monkeypatch.setattr(ops.econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "AVERAGE"})
    monkeypatch.setattr(ops.econnect, "has_exchange_rate", lambda conn, **kw: True)

    class _Stop(Exception):
        pass

    def _stop(*a, **kw):
        raise _Stop()

    monkeypatch.setattr(ops.econnect, "get_next_po_number", _stop)
    with pytest.raises(_Stop):
        ops.create_po_op(object(), company="TUBC", request=_usd_po_request())
