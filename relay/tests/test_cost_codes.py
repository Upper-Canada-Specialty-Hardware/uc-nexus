"""Auth gate + required-param checks for /cost-codes, plus the usable-code filter in
econnect.list_cost_codes. The 401 short-circuits before any SQL, so the auth tests never touch GP;
the missing-job 422 fires on param validation before the body runs. The filter tests use a fake
cursor that records the SQL - what they pin is that the dropdown query hides exactly what the
create_po guards would refuse (inactive codes, and codes whose account index dangles, #425)."""

from collections import namedtuple

from fastapi.testclient import TestClient

from ucnexus_relay.config import get_settings
from ucnexus_relay.econnect import list_cost_codes
from ucnexus_relay.main import create_app

client = TestClient(create_app())
TOKEN = get_settings().auth.shared_secret


def test_cost_codes_requires_token():
    assert client.get("/cost-codes?job=80003").status_code == 401


def test_cost_codes_rejects_bad_token():
    assert client.get("/cost-codes?job=80003", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_cost_codes_requires_job():
    # `job` is a required query param. With a valid token, a missing job is a 422 from param
    # validation - before the endpoint body opens any SQL connection.
    r = client.get("/cost-codes", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 422


# --- the usable-code filter in econnect.list_cost_codes ---

_Code = namedtuple("_Code", "cc1 cc2 elem descr")


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


def test_list_cost_codes_hides_codes_whose_account_index_dangles():
    """The dropdown must not offer a code the create_po cost_code_account_invalid guard would
    refuse (#425): a PO on it registers cleanly and then fails forever at receipt with eConnect
    4612. The filter lives in the WHERE clause, so what these assertions pin is the predicate -
    the GL00105 join plus 'index is 0 OR resolves', the same rule as account_index_exists."""
    conn = _FakeConn([])
    list_cost_codes(conn, "23093")
    assert "LEFT JOIN dbo.GL00105 a ON a.ACTINDX = c.WS_Account_Index_1" in conn.sql()
    assert "(c.WS_Account_Index_1 = 0 OR a.ACTINDX IS NOT NULL)" in conn.sql()


def test_list_cost_codes_still_reads_only_active_codes():
    # The account filter is IN ADDITION to WS_Inactive = 0, not instead of it.
    conn = _FakeConn([])
    list_cost_codes(conn, "23093")
    assert "WS_Inactive = 0" in conn.sql()
    assert conn.calls[0][1] == ("23093",)


def test_list_cost_codes_row_assembly_is_unchanged():
    # The filter must not change the response shape the dropdown and /po already rely on.
    conn = _FakeConn([_Code("470", "000", 4, "Supply & Install WR Partitions"), _Code("900", "000", 9, "")])
    assert list_cost_codes(conn, "23093") == [
        {"cost_code": "470-000", "description": "Supply & Install WR Partitions", "cost_element": 4},
        {"cost_code": "900-000", "description": None, "cost_element": 9},
    ]
