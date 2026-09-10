"""The reads that feed the PO dialog: the company's shipping methods, sites and units of measure
(econnect.list_po_entry_options), one vendor's address codes (econnect.list_vendor_addresses), and
the three GP defaults list_vendors now carries per vendor.

No GP: a fake cursor records the SQL and answers rows off whichever table the statement names, the
same convention test_cost_codes.py follows. What the assertions pin is the table and columns each
read goes to, the null-a-blank row assembly the dialog relies on, and the unit-of-measure fallback -
which exists because the Purchase Order Processing Setup column naming the schedule is unverified,
so a read that fails must still answer rather than break PO entry."""

from collections import namedtuple

from ucnexus_relay.econnect import list_po_entry_options, list_vendor_addresses, list_vendors

_Ship = namedtuple("_Ship", "id description")
_Site = namedtuple("_Site", "code description")
_Schedule = namedtuple("_Schedule", "schedule")
_Uofm = namedtuple("_Uofm", "uofm")
_Vendor = namedtuple("_Vendor", "vendor_id vendor_name vendor_class status currency shipping_method "
                                "purchase_address_code contact")
_Address = namedtuple("_Address", "code contact address1 address2 address3 city state postal_code "
                                  "country phone")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._sql = sql
        self._conn.calls.append((sql, params))
        if self._conn.fail_on and f"dbo.{self._conn.fail_on}" in sql:
            raise RuntimeError(f"Invalid column name in {self._conn.fail_on}")
        return self

    def fetchall(self):
        return self._conn.answer(self._sql)

    def fetchone(self):
        rows = self._conn.answer(self._sql)
        return rows[0] if rows else None


class _FakeConn:
    """Answers by table. Every read here names exactly one GP table, so the fake picks its rows off
    that name; a table it was given no rows for answers empty, which is what a company with none has.
    fail_on makes one table refuse, standing in for a column that is not there."""

    def __init__(self, rows=None, *, fail_on=None):
        self.rows = rows or {}
        self.fail_on = fail_on
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def answer(self, sql):
        for table, rows in self.rows.items():
            if f"dbo.{table}" in sql:
                return rows
        return []

    def sql_for(self, table):
        return next(sql for sql, _ in self.calls if f"dbo.{table}" in sql)

    def touched(self, table):
        return any(f"dbo.{table}" in sql for sql, _ in self.calls)


def _options_conn(**overrides):
    rows = {
        "SY03000": [_Ship("LOCAL DELIVERY", "Local delivery"), _Ship("PICKUP", "")],
        "IV40700": [_Site("VANCOUVER", "Vancouver warehouse")],
        "POP40100": [_Schedule("PURCHASE")],
        "IV40202": [_Uofm("Each"), _Uofm("Box")],
    }
    rows.update(overrides)
    return rows


# --- list_po_entry_options ---

def test_shipping_methods_come_from_the_shipping_method_master():
    conn = _FakeConn(_options_conn())
    result = list_po_entry_options(conn)
    assert "RTRIM(SHIPMTHD) AS id" in conn.sql_for("SY03000")
    assert "RTRIM(SHMTHDSC) AS description" in conn.sql_for("SY03000")
    # a method with no description is offered by id alone rather than with a blank label
    assert result["shipping_methods"] == [
        {"id": "LOCAL DELIVERY", "description": "Local delivery"},
        {"id": "PICKUP", "description": None},
    ]


def test_sites_come_from_the_site_master():
    conn = _FakeConn(_options_conn())
    result = list_po_entry_options(conn)
    assert "RTRIM(LOCNCODE) AS code" in conn.sql_for("IV40700")
    assert "RTRIM(LOCNDSCR) AS description" in conn.sql_for("IV40700")
    assert result["sites"] == [{"code": "VANCOUVER", "description": "Vancouver warehouse"}]


def test_units_of_measure_are_the_rows_of_the_schedule_po_setup_names():
    conn = _FakeConn(_options_conn())
    assert list_po_entry_options(conn)["units_of_measure"] == ["Each", "Box"]
    # the schedule id is read from PO setup and used as the key into the schedule's rows
    assert conn.calls[-1][1] == ("PURCHASE",)
    assert "dbo.IV40202" in conn.calls[-1][0]


def test_units_of_measure_fall_back_when_the_setup_read_refuses():
    # the Purchase Order Processing Setup column is a candidate, not a confirmed name, so a refusal
    # there must leave PO entry working on the value every line has carried to date.
    conn = _FakeConn(_options_conn(), fail_on="POP40100")
    assert list_po_entry_options(conn)["units_of_measure"] == ["Each"]


def test_units_of_measure_fall_back_when_po_setup_names_no_schedule():
    conn = _FakeConn(_options_conn(POP40100=[_Schedule("   ")]))
    assert list_po_entry_options(conn)["units_of_measure"] == ["Each"]
    # nothing to key on, so the schedule's rows are not read at all
    assert not conn.touched("IV40202")


def test_units_of_measure_fall_back_when_the_schedule_holds_no_rows():
    conn = _FakeConn(_options_conn(IV40202=[]))
    assert list_po_entry_options(conn)["units_of_measure"] == ["Each"]


def test_units_of_measure_fall_back_when_the_schedule_read_refuses():
    conn = _FakeConn(_options_conn(), fail_on="IV40202")
    assert list_po_entry_options(conn)["units_of_measure"] == ["Each"]


def test_the_three_lists_are_answered_together():
    # one op, because the dialog needs all three the moment it opens.
    result = list_po_entry_options(_FakeConn(_options_conn()))
    assert sorted(result) == ["shipping_methods", "sites", "units_of_measure"]


# --- list_vendor_addresses ---

def test_vendor_addresses_are_scoped_to_the_vendor():
    # ADRSCODE is unique per vendor, not globally: 'PRIMARY' exists under nearly every vendor, so an
    # unscoped read would offer address codes that belong to somebody else.
    conn = _FakeConn({"PM00300": []})
    list_vendor_addresses(conn, "  ING100  ")
    sql, params = conn.calls[0]
    assert "dbo.PM00300" in sql
    assert "RTRIM(VENDORID) = ?" in sql
    assert params == ("ING100",)


def test_vendor_address_row_assembly_nulls_the_blanks():
    conn = _FakeConn({"PM00300": [
        _Address("PRIMARY", "Jane Doe", "1 Main St", "", "", "Vancouver", "BC", "V5K 0A1", "CANADA", "604-555-0100"),
    ]})
    assert list_vendor_addresses(conn, "ING100") == [
        {
            "code": "PRIMARY",
            "contact": "Jane Doe",
            "address1": "1 Main St",
            "address2": None,
            "address3": None,
            "city": "Vancouver",
            "state": "BC",
            "postal_code": "V5K 0A1",
            "country": "CANADA",
            "phone": "604-555-0100",
        }
    ]


# --- the three GP defaults list_vendors now carries ---

def _vendor(**overrides):
    fields = dict(
        vendor_id="ING100",
        vendor_name="Ingersoll Rand",
        vendor_class="HARDWARE",
        status=1,
        currency="CAD",
        shipping_method="LOCAL DELIVERY",
        purchase_address_code="PRIMARY",
        contact="Jane Doe",
    )
    fields.update(overrides)
    return _Vendor(**fields)


def test_list_vendors_reads_the_vendors_own_po_defaults():
    conn = _FakeConn({"PM00200": [_vendor()]})
    rows = list_vendors(conn)
    sql = conn.sql_for("PM00200")
    assert "RTRIM(SHIPMTHD) AS shipping_method" in sql
    assert "RTRIM(VADCDPAD) AS purchase_address_code" in sql
    assert "RTRIM(VNDCNTCT) AS contact" in sql
    assert rows[0]["shipping_method"] == "LOCAL DELIVERY"
    assert rows[0]["purchase_address_code"] == "PRIMARY"
    assert rows[0]["contact"] == "Jane Doe"


def test_a_vendor_with_no_defaults_reports_null_rather_than_blank():
    # null is the dialog's cue to fall back to its own default; a blank sent to GP would be refused.
    conn = _FakeConn({"PM00200": [_vendor(shipping_method="", purchase_address_code="  ", contact=None)]})
    row = list_vendors(conn)[0]
    assert row["shipping_method"] is None
    assert row["purchase_address_code"] is None
    assert row["contact"] is None


def test_the_existing_vendor_fields_are_unchanged():
    # the vendor sync reads these, so widening the row must not disturb them.
    row = list_vendors(_FakeConn({"PM00200": [_vendor(currency="")]}))[0]
    assert row["vendor_id"] == "ING100"
    assert row["vendor_name"] == "Ingersoll Rand"
    assert row["vendor_class"] == "HARDWARE"
    assert row["status"] == 1
    assert row["currency"] == "CAD"
