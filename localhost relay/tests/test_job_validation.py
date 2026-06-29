"""Job + cost-code GP validation: the split_cost_code parse, and the JC00102/JC00701
read-only pre-checks /po runs so a bad job or cost code returns a clean relay error
(job_not_registered / cost_code_not_on_job) instead of a raw eConnect one. No real SQL —
a fake cursor records the SQL + params and returns a canned COUNT row."""

from collections import namedtuple

from ucnexus_relay.econnect import cost_code_on_job, job_exists, split_cost_code

_Row = namedtuple("_Row", "n")


class _FakeCursor:
    def __init__(self, count):
        self._count = count
        self.sql = None
        self.params = None

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        return _Row(self._count)


class _FakeConn:
    """Returns COUNT = `count` for the next query; keeps the cursor for assertions."""

    def __init__(self, count):
        self.cursor_obj = _FakeCursor(count)

    def cursor(self):
        return self.cursor_obj


# --- split_cost_code (the parse shared by the wsi call and the pre-check) ---

def test_split_full_phase_step_element():
    assert split_cost_code("210-200-2") == ("210", "200", "", "", 2)


def test_split_trailing_digit_is_cost_element_not_costtype():
    # '510-000-5' -> Cost_Element 5, cc3/cc4 always blank at this customer
    assert split_cost_code("510-000-5") == ("510", "000", "", "", 5)


def test_split_missing_element_defaults_to_zero():
    assert split_cost_code("210-200") == ("210", "200", "", "", 0)


def test_split_non_numeric_element_falls_back_to_zero():
    assert split_cost_code("210-200-x") == ("210", "200", "", "", 0)


# --- job_exists (JC00102) ---

def test_job_exists_true_when_row_found():
    conn = _FakeConn(1)
    assert job_exists(conn, "80003") is True
    assert "JC00102" in conn.cursor_obj.sql
    assert "WS_Job_Number = ?" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("80003",)


def test_job_exists_false_when_no_row():
    conn = _FakeConn(0)
    assert job_exists(conn, "NOPE") is False


# --- cost_code_on_job (JC00701) ---

def test_cost_code_on_job_matches_six_column_key():
    conn = _FakeConn(1)
    assert cost_code_on_job(conn, "80003", "210-200-2") is True
    # the split feeds the JC00701 key in WS_Job_Number, cc1..cc4, Cost_Element order
    assert "JC00701" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("80003", "210", "200", "", "", 2)


def test_cost_code_not_on_job_when_no_row():
    conn = _FakeConn(0)
    assert cost_code_on_job(conn, "80003", "999-999-9") is False
