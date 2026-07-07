"""Job + cost-code GP validation: the split_cost_code parse, and the JC00102/JC00701
read-only pre-checks create_po runs so a bad job or cost code returns a clean relay error
(job_not_registered / cost_code_not_on_job) instead of a raw eConnect one. Also list_jobs
(JC00102 x JC00901). No real SQL — fake cursors return canned rows and record SQL + params."""

from collections import namedtuple

from ucnexus_relay.econnect import cost_code_on_job, job_exists, list_jobs, split_cost_code

_Row = namedtuple("_Row", "n")
_JobRow = namedtuple("_JobRow", "job_number job_name inactive")


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
    # RTRIM the column so this matches list_cost_codes' normalization (not a bare '=')
    assert "RTRIM(WS_Job_Number) = ?" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("80003",)


def test_job_exists_false_when_no_row():
    conn = _FakeConn(0)
    assert job_exists(conn, "NOPE") is False


def test_job_exists_strips_whitespace_like_the_dropdown():
    # /cost-codes strips its job param and RTRIMs the column; job_exists must too, or a job the
    # dropdown loaded fails the /po pre-check on surrounding whitespace.
    conn = _FakeConn(1)
    assert job_exists(conn, "  80003 ") is True
    assert conn.cursor_obj.params == ("80003",)


# --- cost_code_on_job (JC00701) ---

def test_cost_code_on_job_matches_six_column_key():
    conn = _FakeConn(1)
    assert cost_code_on_job(conn, "80003", "210-200-2") is True
    # the split feeds the JC00701 key in WS_Job_Number, cc1..cc4, Cost_Element order
    assert "JC00701" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("80003", "210", "200", "", "", 2)


def test_cost_code_on_job_filters_inactive_codes():
    # must match list_cost_codes (WS_Inactive = 0): an inactive code the dropdown hides should not
    # pass the pre-check, or the wsi proc rejects it mid-orchestration with a raw eConnect error.
    conn = _FakeConn(1)
    assert cost_code_on_job(conn, "  80003 ", "210-200-2") is True
    assert "WS_Inactive = 0" in conn.cursor_obj.sql
    assert "RTRIM(WS_Job_Number) = ?" in conn.cursor_obj.sql
    assert conn.cursor_obj.params == ("80003", "210", "200", "", "", 2)


def test_cost_code_not_on_job_when_no_row():
    conn = _FakeConn(0)
    assert cost_code_on_job(conn, "80003", "999-999-9") is False


# --- list_jobs (JC00102 left-joined to JC00901 for WS_Inactive) ---


class _JobsCursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = None

    def execute(self, sql, *params):
        self.sql = sql
        return self

    def fetchall(self):
        return self._rows


class _JobsConn:
    def __init__(self, rows):
        self.cursor_obj = _JobsCursor(rows)

    def cursor(self):
        return self.cursor_obj


def test_list_jobs_reads_job_number_and_name():
    conn = _JobsConn([_JobRow("80003", "Signature Tower", 0)])
    jobs = list_jobs(conn)
    assert jobs == [{"job_number": "80003", "job_name": "Signature Tower", "status": "active"}]
    assert "JC00102" in conn.cursor_obj.sql
    assert "JC00901" in conn.cursor_obj.sql


def test_list_jobs_marks_inactive_from_jc00901():
    conn = _JobsConn([_JobRow("80099", "Old Job", 1)])
    assert list_jobs(conn) == [{"job_number": "80099", "job_name": "Old Job", "status": "inactive"}]


def test_list_jobs_defaults_to_active_with_no_jc00901_row():
    # LEFT JOIN with no matching JC00901 row comes back NULL/None, not every job has one
    conn = _JobsConn([_JobRow("80005", "No Status Row", None)])
    assert list_jobs(conn) == [{"job_number": "80005", "job_name": "No Status Row", "status": "active"}]


def test_list_jobs_blank_name_becomes_none():
    conn = _JobsConn([_JobRow("80006", "", 0)])
    assert list_jobs(conn)[0]["job_name"] is None
