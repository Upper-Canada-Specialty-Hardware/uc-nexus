"""The four live GP reads that feed the create-job form (issue #380). A fake cursor returns canned rows
and records the SQL, so these assert the shape each read returns and the table/filter it reads from -
without touching GP."""

from collections import namedtuple

from ucnexus_relay.econnect import (
    list_customer_addresses,
    list_customers,
    list_divisions,
    list_tax_schedules,
)


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchall(self):
        return self._conn.rows


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def sql(self):
        return self.calls[0][0]


def test_list_customers_returns_number_and_name():
    Row = namedtuple("Row", "customer_number customer_name")
    conn = _FakeConn([Row("ELL100", "Ellis Don"), Row("SCO100", "Scott Construction")])
    assert list_customers(conn) == [
        {"customer_number": "ELL100", "customer_name": "Ellis Don"},
        {"customer_number": "SCO100", "customer_name": "Scott Construction"},
    ]
    assert "RM00101" in conn.sql()


def test_list_customers_maps_a_blank_name_to_none():
    Row = namedtuple("Row", "customer_number customer_name")
    conn = _FakeConn([Row("ELL100", "")])
    assert list_customers(conn)[0]["customer_name"] is None


def test_list_customer_addresses_is_scoped_to_the_customer():
    Row = namedtuple("Row", "address_code address1 city state")
    conn = _FakeConn([Row("MAIN", "1 Main St", "Vancouver", "BC")])
    assert list_customer_addresses(conn, "ELL100") == [
        {"address_code": "MAIN", "address1": "1 Main St", "city": "Vancouver", "state": "BC"}
    ]
    sql, params = conn.calls[0]
    assert "RM00102" in sql
    assert "CUSTNMBR" in sql
    assert params == ("ELL100",)


def test_list_customer_addresses_strips_the_customer():
    Row = namedtuple("Row", "address_code address1 city state")
    conn = _FakeConn([Row("MAIN", None, None, None)])
    list_customer_addresses(conn, "  ELL100  ")
    assert conn.calls[0][1] == ("ELL100",)


def test_list_tax_schedules_reads_the_schedule_master_not_the_details():
    Row = namedtuple("Row", "tax_schedule_id description")
    conn = _FakeConn([Row("GST 5%", "Federal GST 5%")])
    assert list_tax_schedules(conn) == [{"tax_schedule_id": "GST 5%", "description": "Federal GST 5%"}]
    sql = conn.sql()
    assert "TX00101" in sql
    assert "TX00201" not in sql  # that's list_tax_details, a different thing


def test_list_divisions_filters_to_divisions_with_accounts():
    Row = namedtuple("Row", "division")
    conn = _FakeConn([Row("VANCOUVER")])
    assert list_divisions(conn) == ["VANCOUVER"]
    sql = conn.sql()
    assert "JCDivisionSETP" in sql
    # the accounts filter is what keeps un-creatable divisions out of the dropdown
    assert "JCDivisionAccountsSETP" in sql
    assert "EXISTS" in sql
