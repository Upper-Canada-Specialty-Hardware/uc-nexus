"""Issue #500's vendor contact read, and #1685's fix for GPs whose SY01200.EmailToAddress is a `text`
column. No real SQL - a fake cursor records the SQL + params and returns a canned row. RTRIM on a text
column is refused by SQL Server when the statement is prepared (8116), so the shape of the SQL is the
thing pinned here."""

import re
from collections import namedtuple

from ucnexus_relay.econnect import get_vendor_contact

_Row = namedtuple("_Row", "email_to inet1 contact_name vendor_name")


class _FakeCursor:
    def __init__(self, one):
        self._one = one
        self.sql = None
        self.params = None

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        return self._one


class _FakeConn:
    def __init__(self, one=None):
        self.cursor_obj = _FakeCursor(one)

    def cursor(self):
        return self.cursor_obj


def test_email_to_address_is_cast_before_it_is_trimmed():
    conn = _FakeConn(_Row("orders@acme.example.com", "", "Pat", "Acme"))
    get_vendor_contact(conn, "ACME")
    sql = conn.cursor_obj.sql
    assert "CAST(i.EmailToAddress AS varchar(max))" in sql
    # Nothing trims the raw text column, wrapped in ISNULL or not.
    assert not re.search(r"RTRIM\(\s*(ISNULL\(\s*)?i\.EmailToAddress", sql)
    assert conn.cursor_obj.params == (("ACME",),)


def test_email_to_address_wins_over_inet1():
    conn = _FakeConn(_Row("orders@acme.example.com", "legacy@acme.example.com", "Pat", "Acme"))
    assert get_vendor_contact(conn, "ACME") == {
        "vendor_id": "ACME",
        "vendor_name": "Acme",
        "contact_name": "Pat",
        "email": "orders@acme.example.com",
    }


def test_inet1_is_used_when_email_to_address_is_blank():
    conn = _FakeConn(_Row("  ", "legacy@acme.example.com", "", "Acme"))
    contact = get_vendor_contact(conn, "ACME")
    assert contact["email"] == "legacy@acme.example.com"
    assert contact["contact_name"] is None


def test_a_vendor_with_no_internet_row_has_no_email():
    # LEFT JOIN with no SY01200 row: ISNULL turns both columns into ''.
    contact = get_vendor_contact(_FakeConn(_Row("", "", "", "Acme")), "ACME")
    assert contact["email"] is None


def test_the_purchase_address_row_is_read_first_then_the_primary():
    """#1864: SY01200 holds one row per vendor address, and an unordered TOP 1 took any of them. The
    ranking is pinned here, since only GP can run it: a row with an email, then the purchase address,
    then the primary, then the rest by code - a total order, so the same vendor reads the same email."""
    conn = _FakeConn(_Row("orders@acme.example.com", "", "Pat", "Acme"))
    get_vendor_contact(conn, "ACME")
    sql = " ".join(conn.cursor_obj.sql.split())
    assert sql.startswith("SELECT TOP 1 ")
    order_by = sql.split("ORDER BY", 1)[1]
    has_email = order_by.index("<> ''")
    purchase = order_by.index("i.ADRSCODE = v.VADCDPAD THEN 0")
    primary = order_by.index("i.ADRSCODE = v.VADDCDPR THEN 1")
    assert has_email < purchase < primary
    assert order_by.rstrip().endswith("i.ADRSCODE")
    # the blank test casts the text column too, never trims it raw (#1685)
    assert "ISNULL(CAST(i.EmailToAddress AS varchar(max)), '') <> ''" in order_by
    assert not re.search(r"RTRIM\(\s*(ISNULL\(\s*)?i\.EmailToAddress", sql)


def test_an_unknown_vendor_reads_as_none():
    assert get_vendor_contact(_FakeConn(None), "NOBODY") is None
