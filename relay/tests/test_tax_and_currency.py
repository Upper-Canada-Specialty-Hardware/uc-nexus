"""Issue #257 GP-first currency + purchase tax-detail reads, and issue #762's tax write shape. No real
SQL - a fake cursor records the SQL + params and returns canned rows. The read helpers' SQL shape and
normalization come first; the second half pins the tax arithmetic to figures read back from GP and
asserts the rows the op sends, in order, through a recording connection. The proc shapes themselves
were verified live: TUBC for the #257 charges, TUCSH PO097492 for the #762 row shape."""

import re
from collections import namedtuple
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import econnect, models, ops, po_tax
from ucnexus_relay.channel import CREATE_PO_TAX_ROWS_FEATURE, _hello_frame
from ucnexus_relay.econnect import (
    get_charge_tax_schedules,
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

_VendRow = namedtuple(
    "_VendRow",
    "vendor_id vendor_name vendor_class status currency shipping_method purchase_address_code contact",
)


def test_list_vendors_includes_currency_blank_defaults_to_cad():
    conn = _FakeConn(many=[
        _VendRow("SEL101", "SELECT PRODUCTS", "USA", 1, "USD", "LOCAL DELIVERY", "PRIMARY", "Jane"),
        _VendRow("V2", "BLANK CUR VENDOR", "CAN", 1, "", "LOCAL DELIVERY", "PRIMARY", "Jane"),
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


def _stub_header_lists(monkeypatch):
    """The header's shipping method, site and vendor address code are pre-checked against GP before
    the currency block runs, so a test about the currency ordering has to let them pass. They are not
    what these tests are about; each has its own coverage in test_po_header_fields.py."""
    monkeypatch.setattr(ops.econnect, "shipping_method_exists", lambda conn, method: True)
    monkeypatch.setattr(ops.econnect, "site_exists", lambda conn, site: True)
    monkeypatch.setattr(ops.econnect, "vendor_address_exists", lambda conn, vendor, code: True)


def _usd_po_request():
    return models.CreatePoRequest(
        company="TUBC",
        header=models.POHeader(
            vendor_id="SEL101",
            buyer_id="BUYER1",
            confirm_with="test",
            doc_date=date(2026, 8, 26),
            site="VANCOUVER",
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
    _stub_header_lists(monkeypatch)
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
    _stub_header_lists(monkeypatch)
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
    _stub_header_lists(monkeypatch)
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


# =====================================================================================================
# Issue #762: the tax a PO REGISTRATION writes, the way GP writes it on an office PO.
#
# The arithmetic is pinned to figures read back from GP itself: TUCSH PO097492 (the live validation
# of this shape - two details, freight), UBC office PO502338 (one detail, freight), and the two UCSH
# office POs with a trade discount, PO098214 (one line) and PO032858 (seven lines), whose line bases
# show how GP spreads the discount. The write shape is then asserted through a fake connection that
# records every EXEC the op sends, in order: a tax row per line per detail, a freight and a misc row
# per detail, never an ORD 0 summary row (taPopIvcTaxInsert builds that itself and doubles a
# caller-written one), and a final header whose totals are the sums of those rows.
# =====================================================================================================


_GST = po_tax.TaxDetail("BC GST 5% - P", Decimal("5"))
_PST = po_tax.TaxDetail("BC PST 7% PURCH", Decimal("7"))
_HST = po_tax.TaxDetail("ON HST - P", Decimal("13"))


# --- po_tax.plan_po_tax: the figures GP holds ---


def test_plan_matches_tucsh_po097492_two_details_and_freight():
    # Two lines 100.00 and 250.00, freight 20.00, GST 5% plus PST 7%, read back from POP10110 and
    # POP10160 after the live validation run.
    plan = po_tax.plan_po_tax(
        lines=[(16384, Decimal("100.00")), (32768, Decimal("250.00"))],
        details=[_GST, _PST],
        freight_amount=Decimal("20.00"),
    )
    assert [line.taxable_base for line in plan.lines] == [Decimal("100.00"), Decimal("250.00")]
    assert plan.lines[0].tax_by_detail == {"BC GST 5% - P": Decimal("5.00"), "BC PST 7% PURCH": Decimal("7.00")}
    assert plan.lines[1].tax_by_detail == {"BC GST 5% - P": Decimal("12.50"), "BC PST 7% PURCH": Decimal("17.50")}
    # POP10110.TAXAMNT per line: the line's total across both details
    assert [line.total for line in plan.lines] == [Decimal("12.00"), Decimal("30.00")]
    assert plan.freight_tax_by_detail == {"BC GST 5% - P": Decimal("1.00"), "BC PST 7% PURCH": Decimal("1.40")}
    # the header: TAXAMNT 44.40, FRTTXAMT 2.40, no misc
    assert plan.goods_tax_amount == Decimal("42.00")
    assert plan.freight_tax_amount == Decimal("2.40")
    assert plan.misc_tax_amount == Decimal(0)
    assert plan.tax_amount == Decimal("44.40")
    assert plan.taxed and plan.freight_taxed and plan.misc_taxed


def test_plan_matches_ubc_office_po502338_one_detail_and_freight():
    # The office reference the live run was compared against: goods 2035.00, freight 60.00 at 5% -
    # summary 101.75, freight row 3.00, header 104.75 and 3.00.
    plan = po_tax.plan_po_tax(
        lines=[(16384, Decimal("2035.00"))], details=[_GST], freight_amount=Decimal("60.00")
    )
    assert plan.goods_tax_amount == Decimal("101.75")
    assert plan.freight_tax_amount == Decimal("3.00")
    assert plan.tax_amount == Decimal("104.75")


def test_plan_taxes_misc_at_the_goods_rate_under_the_goods_detail():
    plan = po_tax.plan_po_tax(
        lines=[(16384, Decimal("100.00"))], details=[_HST], misc_amount=Decimal("10.00")
    )
    assert plan.misc_tax_by_detail == {"ON HST - P": Decimal("1.30")}
    assert plan.misc_tax_amount == Decimal("1.30")
    assert plan.freight_tax_by_detail == {}
    assert plan.tax_amount == Decimal("14.30")


def test_plan_nets_the_trade_discount_before_tax_as_ucsh_po098214_does():
    # one line 1395.20, discount 160.00, 5 percent: GP's line row carries 61.76 on 1235.20.
    plan = po_tax.plan_po_tax(
        lines=[(16384, Decimal("1395.20"))], details=[_GST], trade_discount=Decimal("160.00")
    )
    assert plan.lines[0].taxable_base == Decimal("1235.20")
    assert plan.tax_amount == Decimal("61.76")


def test_plan_spreads_the_discount_pro_rata_by_extended_cost_as_ucsh_po032858_does():
    # seven lines, a 25 percent discount (2572.50 on 10290.00), 13 percent: every line row's base is
    # 75 percent of its extended cost and the header tax is 1003.29.
    ext = ["1960.00", "0.00", "1470.00", "1960.00", "1470.00", "490.00", "2940.00"]
    plan = po_tax.plan_po_tax(
        lines=[(16384 * (i + 1), Decimal(e)) for i, e in enumerate(ext)],
        details=[_HST],
        trade_discount=Decimal("2572.50"),
    )
    assert [str(line.taxable_base) for line in plan.lines] == [
        "1470.00", "0.00", "1102.50", "1470.00", "1102.50", "367.50", "2205.00"
    ]
    assert [str(line.total) for line in plan.lines] == [
        "191.10", "0.00", "143.33", "191.10", "143.33", "47.78", "286.65"
    ]
    assert plan.tax_amount == Decimal("1003.29")


def test_discount_spread_lands_the_rounding_on_the_last_costed_line():
    # three equal lines and a discount that does not split into cents: the bases still add up to the
    # discounted subtotal exactly, so the rows the header is checked against sum to the cent.
    bases = po_tax.spread_trade_discount([Decimal("10.00")] * 3, Decimal("1.00"))
    assert bases == [Decimal("9.67"), Decimal("9.67"), Decimal("9.66")]
    assert sum(bases) == Decimal("29.00")
    # a trailing zero-cost line is not where the residue goes
    bases = po_tax.spread_trade_discount([Decimal("10.00")] * 3 + [Decimal(0)], Decimal("1.00"))
    assert bases == [Decimal("9.67"), Decimal("9.67"), Decimal("9.66"), Decimal("0.00")]


def test_plan_with_no_detail_is_no_tax_and_the_charges_are_not_taxable():
    plan = po_tax.plan_po_tax(
        lines=[(16384, Decimal("100.00"))],
        details=[],
        freight_amount=Decimal("20.00"),
        misc_amount=Decimal("5.00"),
        trade_discount=Decimal("10.00"),
    )
    assert plan.taxed is False
    assert plan.freight_taxed is False and plan.misc_taxed is False
    assert plan.tax_amount == Decimal(0)
    assert plan.lines[0].tax_by_detail == {}
    assert plan.lines[0].taxable_base == Decimal("90.00")


# --- the write shape, through a fake connection that records every EXEC ---


class _Row:
    error_state = 0
    err_string = ""
    n = 1  # create_po_line's ORD read-back


class _RecordingCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        return _Row()


class _RecordingConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _RecordingCursor(self)

    def matching(self, needle):
        return [c for c in self.calls if needle in c[0]]


def _bound(sql: str, params: tuple) -> dict:
    """{param name: bound value} for one EXEC, pairing each `@I_vNAME = ?` with its value in order."""
    names = re.findall(r"@I_v(\w+)\s*=\s*\?", sql)
    assert len(names) == len(params), (names, params)
    return dict(zip(names, params))


def _po_request(*, header: dict | None = None, lines=None) -> models.CreatePoRequest:
    fields = dict(
        vendor_id="107-CANINC.",
        buyer_id="BUYER1",
        confirm_with="test",
        doc_date=date(2026, 9, 21),
        site="MARKHAM",
    )
    fields.update(header or {})
    lines = lines or [("761TEST1", Decimal("2"), Decimal("50.00")), ("761TEST2", Decimal("1"), Decimal("250.00"))]
    return models.CreatePoRequest(
        company="TUCSH",
        header=models.POHeader(**fields),
        lines=[
            models.POLine(item_number=item, item_description=f"{item} line", quantity=qty, unit_cost=cost)
            for item, qty, cost in lines
        ],
    )


_PERCENTS = {"BC GST 5% - P": Decimal("5"), "BC PST 7% PURCH": Decimal("7"), "ON HST - P": Decimal("13")}


@pytest.fixture
def gp(monkeypatch):
    """The GP masters around the write, all stubbed to what TUCSH holds; the writes themselves stay
    real so their SQL lands in the recording connection. Returns the dict of charge schedules so a
    test can blank the chain."""
    schedules = {"freight": "ONHST 13%", "misc": "ONHST 13%"}
    _stub_header_lists(monkeypatch)
    monkeypatch.setattr(ops.econnect, "list_buyers", lambda conn: ["BUYER1"])
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "CAD")
    monkeypatch.setattr(ops.econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "BUY"})
    monkeypatch.setattr(ops.econnect, "get_tax_detail_percent", lambda conn, tid: _PERCENTS.get(tid))
    monkeypatch.setattr(ops.econnect, "get_charge_tax_schedules", lambda conn, vendor_id: dict(schedules))
    monkeypatch.setattr(ops.econnect, "po_number_in_use", lambda conn, po_number: None)
    monkeypatch.setattr(ops.econnect, "get_next_po_number", lambda conn: "PO097492")
    monkeypatch.setattr(ops.econnect, "apply_wennsoft_integration", lambda conn, **kw: None)
    return schedules


def _two_detail_freight_header():
    return {"tax_detail_ids": ["BC GST 5% - P", "BC PST 7% PURCH"], "freight_amount": Decimal("20.00")}


def test_a_two_detail_po_writes_the_row_shape_of_tucsh_po097492(gp):
    conn = _RecordingConn()

    response = ops.create_po_op(conn, company="TUCSH", request=_po_request(header=_two_detail_freight_header()))

    assert response.tax_amount == Decimal("44.40")
    # every line carries its total across both details on taPoLine
    lines = [_bound(sql, params) for sql, params in conn.matching("taPoLine")]
    assert [(b["ORD"], b["TAXAMNT"]) for b in lines] == [(16384, Decimal("12.00")), (32768, Decimal("30.00"))]
    # per detail: a row at each line's ORD, then the freight row - six rows, and NO ORD 0 row
    rows = [_bound(sql, params) for sql, params in conn.matching("taPopIvcTaxInsert")]
    assert [(r["TAXDTLID"], r["ORD"], r["TAXAMNT"], r["TAXPURCH"], r["FRTTXAMT"]) for r in rows] == [
        ("BC GST 5% - P", 16384, Decimal("5.00"), Decimal("100.00"), Decimal(0)),
        ("BC GST 5% - P", 32768, Decimal("12.50"), Decimal("250.00"), Decimal(0)),
        ("BC GST 5% - P", po_tax.FREIGHT_TAX_ORD, Decimal(0), Decimal("20.00"), Decimal("1.00")),
        ("BC PST 7% PURCH", 16384, Decimal("7.00"), Decimal("100.00"), Decimal(0)),
        ("BC PST 7% PURCH", 32768, Decimal("17.50"), Decimal("250.00"), Decimal(0)),
        ("BC PST 7% PURCH", po_tax.FREIGHT_TAX_ORD, Decimal(0), Decimal("20.00"), Decimal("1.40")),
    ]
    assert all(r["ORD"] != 0 for r in rows)
    assert all(r["TOTPURCH"] == r["TAXPURCH"] for r in rows)
    # the final header: the totals the rows sum to, the freight taxed and its schedule named
    create, final = [_bound(sql, params) for sql, params in conn.matching("taPoHdr")]
    assert final["SUBTOTAL"] == Decimal("350.00")
    assert final["FRTAMNT"] == Decimal("20.00")
    assert final["TAXAMNT"] == Decimal("44.40")
    assert final["FRTTXAMT"] == Decimal("2.40")
    assert final["MSCTXAMT"] == Decimal(0)
    assert final["Purchase_Freight_Taxable"] == 1
    assert final["Purchase_Misc_Taxable"] == 1
    assert final["USINGHEADERLEVELTAXES"] == 1
    assert final["FRTSCHID"] == "ONHST 13%"
    assert "MSCSCHID" not in final  # no misc, no misc tax, nothing for 889 to want
    # two details: the header schedule is blank on both calls, as the office's 12 percent POs carry
    assert create["TAXSCHID"] == "" and final["TAXSCHID"] == ""


def test_the_tax_rows_land_after_the_lines_and_before_the_final_header(gp):
    conn = _RecordingConn()

    ops.create_po_op(conn, company="TUCSH", request=_po_request(header=_two_detail_freight_header()))

    kinds = []
    for sql, _ in conn.calls:
        for proc in ("taPoHdr", "taPoLine", "taPopIvcTaxInsert"):
            if proc in sql:
                kinds.append(proc)
    assert kinds == ["taPoHdr"] + ["taPoLine"] * 2 + ["taPopIvcTaxInsert"] * 6 + ["taPoHdr"]


def test_a_single_detail_po_keeps_gps_default_header_schedule(gp):
    conn = _RecordingConn()

    ops.create_po_op(
        conn, company="TUCSH", request=_po_request(header={"tax_detail_ids": ["ON HST - P"]})
    )

    create, final = [_bound(sql, params) for sql, params in conn.matching("taPoHdr")]
    assert "TAXSCHID" not in create and "TAXSCHID" not in final
    rows = [_bound(sql, params) for sql, params in conn.matching("taPopIvcTaxInsert")]
    assert [(r["ORD"], r["TAXAMNT"]) for r in rows] == [(16384, Decimal("13.00")), (32768, Decimal("32.50"))]
    assert final["TAXAMNT"] == Decimal("45.50")
    # no freight and no misc on this PO: flagged taxable (a detail is picked), nothing to carry
    assert final["FRTTXAMT"] == Decimal(0) and "FRTSCHID" not in final
    assert final["Purchase_Freight_Taxable"] == 1


def test_freight_discount_and_misc_on_one_detail(gp):
    # the TUBC live check shape: 13 percent, one detail, freight and a discount (and misc here too)
    conn = _RecordingConn()
    header = {
        "tax_detail_ids": ["ON HST - P"],
        "freight_amount": Decimal("25.00"),
        "misc_amount": Decimal("10.00"),
        "trade_discount": Decimal("35.00"),
    }

    response = ops.create_po_op(conn, company="TUBC", request=_po_request(header=header))

    rows = [_bound(sql, params) for sql, params in conn.matching("taPopIvcTaxInsert")]
    # bases net of the discount, spread pro rata: 100 -> 90.00, 250 -> 225.00
    assert [(r["ORD"], r["TAXPURCH"], r["TAXAMNT"], r["FRTTXAMT"], r["MSCTXAMT"]) for r in rows] == [
        (16384, Decimal("90.00"), Decimal("11.70"), Decimal(0), Decimal(0)),
        (32768, Decimal("225.00"), Decimal("29.25"), Decimal(0), Decimal(0)),
        (po_tax.FREIGHT_TAX_ORD, Decimal("25.00"), Decimal(0), Decimal("3.25"), Decimal(0)),
        (po_tax.MISC_TAX_ORD, Decimal("10.00"), Decimal(0), Decimal(0), Decimal("1.30")),
    ]
    final = _bound(*conn.matching("taPoHdr")[1])
    assert final["TRDISAMT"] == Decimal("35.00")
    assert final["TAXAMNT"] == Decimal("45.50")  # 11.70 + 29.25 + 3.25 + 1.30
    assert final["FRTTXAMT"] == Decimal("3.25")
    assert final["MSCTXAMT"] == Decimal("1.30")
    assert final["FRTSCHID"] == "ONHST 13%" and final["MSCSCHID"] == "ONHST 13%"
    assert response.tax_amount == Decimal("45.50")


def test_a_po_with_no_detail_writes_no_rows_and_flags_the_charges_not_taxable(gp):
    conn = _RecordingConn()

    response = ops.create_po_op(
        conn, company="TUCSH", request=_po_request(header={"freight_amount": Decimal("20.00")})
    )

    assert response.tax_amount == Decimal(0)
    assert conn.matching("taPopIvcTaxInsert") == []
    assert [_bound(sql, p)["TAXAMNT"] for sql, p in conn.matching("taPoLine")] == [Decimal(0), Decimal(0)]
    final = _bound(*conn.matching("taPoHdr")[1])
    assert final["TAXAMNT"] == Decimal(0) and final["FRTTXAMT"] == Decimal(0)
    assert final["USINGHEADERLEVELTAXES"] == 0
    # GP's flag is 1 taxable / 2 not taxable; 0 is not a value GP has
    assert final["Purchase_Freight_Taxable"] == 2 and final["Purchase_Misc_Taxable"] == 2
    assert "FRTSCHID" not in final and "TAXSCHID" not in final


def test_a_usd_po_is_unchanged_no_details_no_rows_blank_schedule(gp, monkeypatch):
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "USD")
    monkeypatch.setattr(ops.econnect, "has_exchange_rate", lambda conn, **kw: True)
    conn = _RecordingConn()

    response = ops.create_po_op(
        conn, company="TUCSH", request=_po_request(header={"freight_amount": Decimal("20.00")})
    )

    assert response.currency == "USD" and response.tax_amount == Decimal(0)
    assert conn.matching("taPopIvcTaxInsert") == []
    create, final = [_bound(sql, params) for sql, params in conn.matching("taPoHdr")]
    assert create["TAXSCHID"] == "" and final["TAXSCHID"] == ""
    assert final["RATETPID"] == "BUY"
    assert final["Purchase_Freight_Taxable"] == 2


def test_a_usd_po_still_refuses_a_tax_detail(gp, monkeypatch):
    monkeypatch.setattr(ops.econnect, "get_vendor_currency", lambda conn, vid: "USD")
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(_RecordingConn(), company="TUCSH", request=_po_request(header={"tax_detail_ids": ["ON HST - P"]}))
    assert exc.value.code == "tax_detail_on_foreign_po"


def test_a_detail_gp_does_not_hold_is_refused_before_a_number_is_reserved(gp, monkeypatch):
    reserved = []
    monkeypatch.setattr(ops.econnect, "get_next_po_number", lambda conn: reserved.append(1))
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(
            _RecordingConn(), company="TUCSH", request=_po_request(header={"tax_detail_ids": ["BC HST 12%"]})
        )
    assert exc.value.code == "tax_detail_not_found"
    assert reserved == []


def test_a_taxed_charge_with_no_schedule_anywhere_is_refused_before_a_number_is_reserved(gp, monkeypatch):
    gp["freight"] = None
    reserved = []
    monkeypatch.setattr(ops.econnect, "get_next_po_number", lambda conn: reserved.append(1))
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(_RecordingConn(), company="TUCSH", request=_po_request(header=_two_detail_freight_header()))
    assert exc.value.code == "charge_tax_schedule_unresolved"
    assert exc.value.context["charge"] == "freight"
    assert reserved == []


def test_the_schedule_chain_is_not_read_when_no_charge_is_taxed(gp, monkeypatch):
    def _boom(conn, vendor_id):
        raise AssertionError("no taxed charge, so nothing should ask for a charge schedule")

    monkeypatch.setattr(ops.econnect, "get_charge_tax_schedules", _boom)
    ops.create_po_op(_RecordingConn(), company="TUCSH", request=_po_request(header={"tax_detail_ids": ["ON HST - P"]}))


def test_a_discount_larger_than_the_subtotal_is_refused(gp):
    with pytest.raises(ops.RelayOpError) as exc:
        ops.create_po_op(
            _RecordingConn(), company="TUCSH", request=_po_request(header={"trade_discount": Decimal("400.00")})
        )
    assert exc.value.code == "trade_discount_exceeds_subtotal"


def test_the_pre_762_scalar_detail_is_read_as_a_one_detail_list(gp):
    # a registration queued on PENDING GP WRITES before the backend changed shape replays with the
    # old key, and must register with the tax it asked for
    conn = _RecordingConn()
    ops.create_po_op(conn, company="TUCSH", request=_po_request(header={"tax_detail_id": "ON HST - P"}))
    rows = [_bound(sql, params) for sql, params in conn.matching("taPopIvcTaxInsert")]
    assert [r["TAXDTLID"] for r in rows] == ["ON HST - P", "ON HST - P"]
    assert _bound(*conn.matching("taPoHdr")[1])["TAXAMNT"] == Decimal("45.50")


def test_the_header_folds_and_dedupes_the_two_fields():
    header = models.POHeader(
        vendor_id="V", confirm_with="c", doc_date=date(2026, 9, 21), site="S",
        tax_detail_ids=[" BC GST 5% - P ", "BC PST 7% PURCH", "BC GST 5% - P"], tax_detail_id="BC PST 7% PURCH",
    )
    assert header.tax_detail_ids == ["BC GST 5% - P", "BC PST 7% PURCH"]
    assert header.tax_detail_id is None


@pytest.mark.parametrize("bad", [[""], ["   "], ["A" * 16]])
def test_a_blank_or_overlong_detail_id_is_refused_at_the_model(bad):
    with pytest.raises(ValueError):
        models.POHeader(vendor_id="V", confirm_with="c", doc_date=date(2026, 9, 21), site="S", tax_detail_ids=bad)


def test_a_retry_that_finds_the_po_answers_the_full_tax_and_writes_no_row(gp, monkeypatch):
    monkeypatch.setattr(ops.econnect, "find_po_by_registration_note", lambda conn, **kw: "PO097492")
    conn = _RecordingConn()
    request = models.CreatePoRequest(
        **{**_po_request(header=_two_detail_freight_header()).model_dump(), "idempotency_key": "key-1"}
    )

    response = ops.create_po_op(conn, company="TUCSH", request=request)

    assert response.existing is True
    assert response.tax_amount == Decimal("44.40")
    assert conn.matching("taPopIvcTaxInsert") == [] and conn.matching("taPoLine") == [] and conn.matching("taPoHdr") == []


# --- econnect.get_charge_tax_schedules: the fallback chain for FRTSCHID / MSCSCHID ---

_SetupRow = namedtuple("_SetupRow", "freight misc purchase")
_VendorRow = namedtuple("_VendorRow", "schedule")


class _ChainConn:
    """Answers the setup read first and the vendor read second, as the function issues them."""

    def __init__(self, setup, vendor):
        self._rows = [setup, vendor]
        self.sql: list[str] = []

    def cursor(self):
        return self

    def execute(self, sql, *params):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return self._rows.pop(0)


def test_charge_schedules_prefer_the_companys_own_charge_schedules():
    conn = _ChainConn(_SetupRow("BC HST 5%", "BC MISC", "ALL DETAILS"), _VendorRow("ONHST 13%"))
    assert get_charge_tax_schedules(conn, "V1") == {"freight": "BC HST 5%", "misc": "BC MISC"}
    assert "POP40100" in conn.sql[0] and "PM00200" in conn.sql[1]


def test_charge_schedules_fall_back_to_the_vendor_then_the_company_default():
    # both sandboxes: blank POP40100 schedules, a vendor schedule
    conn = _ChainConn(_SetupRow("", "", ""), _VendorRow("ONHST 13%"))
    assert get_charge_tax_schedules(conn, "107-CANINC.") == {"freight": "ONHST 13%", "misc": "ONHST 13%"}
    conn = _ChainConn(_SetupRow("", "", "ALL DETAILS"), _VendorRow(""))
    assert get_charge_tax_schedules(conn, "V1") == {"freight": "ALL DETAILS", "misc": "ALL DETAILS"}


def test_charge_schedules_are_none_when_the_whole_chain_is_blank():
    conn = _ChainConn(_SetupRow("", "", ""), None)
    assert get_charge_tax_schedules(conn, "GHOST") == {"freight": None, "misc": None}


# --- what the relay says about it ---


def test_the_hello_advertises_the_tax_rows_feature():
    # How the backend knows it may send `tax_detail_ids` at all: an older relay ignores the field and
    # would register a CAD PO with no tax.
    assert CREATE_PO_TAX_ROWS_FEATURE == "create_po_tax_rows"
    assert CREATE_PO_TAX_ROWS_FEATURE in _hello_frame()["features"]


def test_insert_po_tax_row_binds_the_charge_taxes_and_never_ord_zero_by_itself():
    conn = _RecordingConn()
    econnect.insert_po_tax_row(
        conn, po_number="PO1", vendor_id="V", tax_detail_id="D", line_ord=po_tax.MISC_TAX_ORD,
        tax_amount=Decimal(0), taxable_purchase=Decimal("10.00"), misc_tax=Decimal("1.30"),
    )
    bound = _bound(*conn.calls[0])
    assert bound["ORD"] == 2147483645
    assert bound["MSCTXAMT"] == Decimal("1.30") and bound["FRTTXAMT"] == Decimal(0)
    assert "@I_vTAXTYPE    = 0" in conn.calls[0][0] and "@I_vBKOUTTAX   = 0" in conn.calls[0][0]
