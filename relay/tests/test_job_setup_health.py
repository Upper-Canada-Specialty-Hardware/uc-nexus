"""GP job setup health (#425): the read that finds jobs whose JC00701 cost codes point at GL account
indexes this company does not have, plus the two write-path guards that refuse to let one through.

The failure being defended against is silent until it is expensive: a job-cost PO on such a cost code
registers perfectly, the WennSoft integration copies the dangling index onto POP10110.INVINDX, and the
receipt then fails forever with eConnect 4612 "Invalid Account Index" (the PO0000070 / index 1617 case
that opened the issue). No real GP here - a fake cursor answers each query in turn and records the SQL,
so these assert the join, the two health rules, the single-job filter, and both refusals.
"""

from collections import namedtuple
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import (
    account_index_exists,
    cost_code_account_index,
    job_setup_health,
    po_lines_with_dangling_account,
)
from ucnexus_relay.ops import RelayOpError

_Verdict = namedtuple("_Verdict", "job_number active_cost_codes broken_cost_codes")
_Detail = namedtuple("_Detail", "job_number cc1 cc2 elem account_index")
_Count = namedtuple("_Count", "n")
_Index = namedtuple("_Index", "account_index")
_PoLine = namedtuple("_PoLine", "ord item account_index job")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchall(self):
        # job_setup_health runs the verdict query then the detail query, in that order.
        return self._conn.results.pop(0)

    def fetchone(self):
        return self._conn.results.pop(0)


class _FakeConn:
    """Answers queries from `results` in call order and keeps every (sql, params) for assertions."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def sql(self, i=0):
        return self.calls[i][0]


# --- job_setup_health: the two rules ---


def test_a_job_with_active_codes_and_resolvable_accounts_is_healthy():
    conn = _FakeConn([_Verdict("23090", 14, 0)], [])
    assert job_setup_health(conn) == [
        {"job_number": "23090", "ok": True, "active_cost_code_count": 14, "issues": []}
    ]


def test_a_dangling_account_index_fails_the_job_and_is_named():
    """The PO0000070 case: job 23093 cost code 210-200-2 -> index 1617, a UCSH account absent from
    UBC/TUBC's GL00105. The verdict alone would only say "broken"; the detail row is what lets the
    quarantine banner name the code somebody has to fix."""
    conn = _FakeConn([_Verdict("23093", 14, 1)], [_Detail("23093", "210", "200", 2, 1617)])
    assert job_setup_health(conn) == [
        {
            "job_number": "23093",
            "ok": False,
            "active_cost_code_count": 14,
            "issues": [{"cost_code": "210-200-2", "account_index": 1617}],
        }
    ]


def test_a_job_with_no_active_cost_codes_fails_rule_one():
    """Driven off JC00102, so a job with nothing in JC00701 still comes back - grouped off JC00701 it
    would simply be missing, and "absent" would read as "fine"."""
    conn = _FakeConn([_Verdict("23099", 0, 0)], [])
    verdicts = job_setup_health(conn)
    assert verdicts[0]["ok"] is False
    assert verdicts[0]["active_cost_code_count"] == 0
    assert "JC00102" in conn.sql()
    assert "LEFT JOIN dbo.JC00701" in conn.sql()


def test_index_zero_never_counts_as_dangling():
    """WS_Account_Index_1 = 0 means "GP picks the account at posting time", which eConnect honours.
    The join-side predicate has to exclude it or every default-left job quarantines."""
    conn = _FakeConn([_Verdict("23091", 9, 0)], [])
    assert job_setup_health(conn)[0]["ok"] is True
    assert "c.WS_Account_Index_1 <> 0" in conn.sql()
    assert "a.ACTINDX IS NULL" in conn.sql()


def test_health_reads_only_active_cost_codes():
    conn = _FakeConn([_Verdict("23090", 14, 0)], [])
    job_setup_health(conn)
    assert "WS_Inactive = 0" in conn.sql()
    assert "GL00105" in conn.sql()


def test_the_whole_company_sweep_takes_exactly_two_queries():
    # One round trip per job over the relay socket would make the sync pass unusable at ~900 jobs.
    conn = _FakeConn(
        [_Verdict("A", 3, 0), _Verdict("B", 3, 1)],
        [_Detail("B", "310", "000", 3, 1622)],
    )
    out = job_setup_health(conn)
    assert len(conn.calls) == 2
    assert [j["ok"] for j in out] == [True, False]
    assert out[1]["issues"] == [{"cost_code": "310-000-3", "account_index": 1622}]


# --- job_setup_health: the single-job filter (the live re-check at PO submit) ---


def test_the_job_filter_scopes_both_queries():
    conn = _FakeConn([_Verdict("23093", 14, 1)], [_Detail("23093", "210", "200", 2, 1617)])
    job_setup_health(conn, "23093")
    assert conn.calls[0][1] == ("23093",)
    assert conn.calls[1][1] == ("23093",)
    assert "WHERE RTRIM(j.WS_Job_Number) = ?" in conn.sql(0)


def test_the_job_filter_strips_whitespace_like_every_other_job_read():
    conn = _FakeConn([_Verdict("23093", 14, 0)], [])
    job_setup_health(conn, "  23093 ")
    assert conn.calls[0][1] == ("23093",)


def test_a_blank_job_is_the_whole_company_sweep_not_an_error():
    conn = _FakeConn([_Verdict("A", 1, 0)], [])
    job_setup_health(conn, "   ")
    assert conn.calls[0][1] == ()


def test_an_unknown_job_yields_no_verdict_at_all():
    # Distinguishable from "healthy": the caller sees nothing to stamp rather than a passing verdict.
    conn = _FakeConn([], [])
    assert job_setup_health(conn, "NOPE") == []


# --- job_setup_health: the batch filter (the adoption pass's read budget) ---


def test_the_batch_filter_scopes_both_queries():
    """The adoption pass walks the job master in batches now. Without this filter every batch would
    re-read the whole company - N full scans for N batches, worse than the one sweep it replaced."""
    conn = _FakeConn(
        [_Verdict("23090", 14, 0), _Verdict("23093", 14, 1)],
        [_Detail("23093", "210", "200", 2, 1617)],
    )
    out = job_setup_health(conn, job_numbers=["23090", "23093"])

    assert len(conn.calls) == 2  # still two queries, whatever the batch size
    assert "WHERE RTRIM(j.WS_Job_Number) IN (?,?)" in conn.sql(0)
    assert "AND RTRIM(c.WS_Job_Number) IN (?,?)" in conn.sql(1)
    assert conn.calls[0][1] == ("23090", "23093")
    assert conn.calls[1][1] == ("23090", "23093")
    assert [j["job_number"] for j in out] == ["23090", "23093"]
    assert out[1]["issues"] == [{"cost_code": "210-200-2", "account_index": 1617}]


def test_the_batch_filter_trims_dedupes_and_skips_blanks():
    conn = _FakeConn([_Verdict("23090", 1, 0)], [])
    job_setup_health(conn, job_numbers=["  23090 ", "23090", "", None])
    assert conn.calls[0][1] == ("23090",)


def test_an_empty_batch_reads_nothing():
    # The caller named no jobs, so there is nothing to ask GP. Falling through to the whole-company
    # sweep here would turn a no-op into a full scan.
    conn = _FakeConn()
    assert job_setup_health(conn, job_numbers=[]) == []
    assert conn.calls == []


def test_a_batch_of_nothing_but_blanks_reads_nothing():
    conn = _FakeConn()
    assert job_setup_health(conn, job_numbers=["", None, "   "]) == []
    assert conn.calls == []


def test_the_batch_wins_over_the_single_job():
    conn = _FakeConn([_Verdict("23090", 1, 0)], [])
    job_setup_health(conn, "23099", job_numbers=["23090"])
    assert conn.calls[0][1] == ("23090",)  # the batch, not the single job


def test_no_batch_at_all_is_still_the_whole_company_sweep():
    # An older backend sends neither key and must keep getting the sweep it asks for.
    conn = _FakeConn([_Verdict("A", 1, 0)], [])
    job_setup_health(conn)
    assert conn.calls[0][1] == ()
    assert "WS_Job_Number IN" not in conn.sql(0)


def test_a_batch_never_reads_more_keys_than_the_cap_in_one_statement():
    keys = [f"J{i:05d}" for i in range(econnect.MAX_JOB_NUMBERS * 2 + 5)]
    # 205 keys -> 3 chunks -> a verdict + detail query per chunk, and the chunks come back unordered.
    conn = _FakeConn(
        [_Verdict("J00300", 1, 0)], [],
        [_Verdict("J00100", 1, 0)], [],
        [_Verdict("J00200", 1, 0)], [],
    )
    out = job_setup_health(conn, job_numbers=keys)

    assert len(conn.calls) == 6
    assert [len(params) for sql, params in conn.calls] == [100, 100, 100, 100, 5, 5]
    assert sum(len(p) for s, p in conn.calls) == len(keys) * 2  # every key read once per query
    # merged back into one list in job order, however many reads it took
    assert [j["job_number"] for j in out] == ["J00100", "J00200", "J00300"]


def test_a_job_in_the_batch_that_gp_does_not_have_is_simply_absent():
    # Not an error: asking about a job JC00102 does not hold is a verdict of "nothing to stamp".
    conn = _FakeConn([_Verdict("23090", 1, 0)], [])
    out = job_setup_health(conn, job_numbers=["23090", "NOPE"])
    assert [j["job_number"] for j in out] == ["23090"]


# --- the create_po guard (cost_code_account_invalid) ---


def test_cost_code_account_index_reads_the_active_row():
    conn = _FakeConn(_Index(1617))
    assert cost_code_account_index(conn, "  23093 ", "210-200-2") == 1617
    assert conn.calls[0][1] == ("23093", "210", "200", "", "", 2)
    assert "WS_Inactive = 0" in conn.sql()


def test_cost_code_account_index_is_none_when_the_row_vanished():
    assert cost_code_account_index(_FakeConn(None), "23093", "210-200-2") is None


def test_account_index_zero_short_circuits_without_a_query():
    conn = _FakeConn()
    assert account_index_exists(conn, 0) is True
    assert conn.calls == []


def test_account_index_exists_checks_gl00105():
    conn = _FakeConn(_Count(1))
    assert account_index_exists(conn, 96) is True
    assert "GL00105" in conn.sql()
    assert conn.calls[0][1] == (96,)


def test_account_index_missing_from_the_chart_is_false():
    assert account_index_exists(_FakeConn(_Count(0)), 1617) is False


def _job_cost_po():
    return models.CreatePoRequest(
        company="TUBC",
        header=models.POHeader(vendor_id="ING100", buyer_id="MIRA", confirm_with="Mira", doc_date=date(2026, 7, 30)),
        lines=[
            models.POLine(
                item_number="ML2010",
                item_description="ML2010 LOCK",
                quantity=Decimal("2"),
                unit_cost=Decimal("12.50"),
                product_indicator=2,
                job_number="23093",
                cost_code="210-200-2",
            )
        ],
    )


def _stub_create_po_prechecks(monkeypatch, *, account_index, index_exists):
    """Everything create_po_op does before the #425 guard, stubbed to pass, so the test isolates the
    guard itself. Anything AFTER it is left unstubbed on purpose: if the guard fails to raise, the op
    walks into a missing econnect stub and the test breaks loudly rather than silently passing."""
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["MIRA"])
    monkeypatch.setattr(econnect, "get_vendor_currency", lambda conn, vendor_id: "CAD")
    monkeypatch.setattr(econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "BUY"})
    monkeypatch.setattr(econnect, "job_exists", lambda conn, job: True)
    monkeypatch.setattr(econnect, "cost_code_on_job", lambda conn, job, code: True)
    monkeypatch.setattr(econnect, "cost_code_account_index", lambda conn, job, code: account_index)
    monkeypatch.setattr(econnect, "account_index_exists", lambda conn, idx: index_exists)


def test_create_po_refuses_a_cost_code_whose_account_does_not_exist(monkeypatch):
    _stub_create_po_prechecks(monkeypatch, account_index=1617, index_exists=False)

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_FakeConn(), company="TUBC", request=_job_cost_po())

    error = excinfo.value
    assert error.code == "cost_code_account_invalid"
    # The message has to be actionable in GP: which code, which index, which job.
    assert "210-200-2" in error.message
    assert "1617" in error.message
    assert "23093" in error.message
    assert error.context["account_index"] == 1617


def test_create_po_allows_a_cost_code_whose_account_resolves(monkeypatch):
    """The guard passing must not be provable by the op simply never reaching it, so this asserts the
    op got PAST the guard - it fails on the next unstubbed step, not on cost_code_account_invalid."""
    _stub_create_po_prechecks(monkeypatch, account_index=96, index_exists=True)

    with pytest.raises(Exception) as excinfo:  # noqa: B017 - anything but the guard's own error
        ops.create_po_op(_FakeConn(), company="TUBC", request=_job_cost_po())

    assert getattr(excinfo.value, "code", None) != "cost_code_account_invalid"


def test_create_po_allows_index_zero(monkeypatch):
    # 0 is "GP defaults the account", not a dangling index, so account_index_exists says True for it.
    _stub_create_po_prechecks(monkeypatch, account_index=0, index_exists=True)

    with pytest.raises(Exception) as excinfo:  # noqa: B017
        ops.create_po_op(_FakeConn(), company="TUBC", request=_job_cost_po())

    assert getattr(excinfo.value, "code", None) != "cost_code_account_invalid"


# --- the create_receipt pre-flight (po_line_account_invalid) ---


def test_po_lines_with_dangling_account_reads_invindx_against_gl00105():
    conn = _FakeConn([_PoLine(16384, "ML2010", 1617, "23093")])
    assert po_lines_with_dangling_account(conn, "PO0000070") == [
        {"ord": 16384, "item": "ML2010", "account_index": 1617, "job": "23093"}
    ]
    assert "POP10110" in conn.sql()
    assert "GL00105" in conn.sql()
    assert "l.INVINDX <> 0" in conn.sql()
    assert conn.calls[0][1] == ("PO0000070",)


def _receipt_request(*ords):
    return models.ReceiptRequest(
        company="TUBC",
        po_number="PO0000070",
        lines=[
            models.ReceiptLine(po_line_ord=o, quantity=Decimal("1"), rack_location="A1-1-1") for o in ords
        ],
    )


def _po_line_context(*ords):
    lines = {
        o: {
            "item": "ML2010",
            "itemdesc": "ML2010 LOCK",
            "vendor": "ING100",
            "job": "23093",
            "jobname": "Test job",
            "locn": "VANCOUVER",
            "noninven": 1,
            "uofm": "Each",
            "vnditnum": "ML2010",
            "qtyorder": Decimal("5"),
            "unitcost": Decimal("12.50"),
            "polnesta": 2,
            "prev_received": Decimal("0"),
        }
        for o in ords
    }
    return "ING100", "Ingersoll", lines


def test_create_receipt_refuses_a_line_stamped_with_a_dangling_account(monkeypatch):
    monkeypatch.setattr(econnect, "read_po_receipt_context", lambda conn, po: _po_line_context(16384))
    monkeypatch.setattr(
        econnect,
        "po_lines_with_dangling_account",
        lambda conn, po: [{"ord": 16384, "item": "ML2010", "account_index": 1617, "job": "23093"}],
    )

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_receipt_op(_FakeConn(), company="TUBC", request=_receipt_request(16384))

    error = excinfo.value
    assert error.code == "po_line_account_invalid"
    # The whole point of pre-flighting is that the warehouse user reads this instead of "4612".
    assert "ML2010" in error.message
    assert "1617" in error.message
    assert "23093" in error.message
    assert error.context["lines"][0]["ord"] == 16384


def test_create_receipt_ignores_a_broken_line_nobody_is_receiving(monkeypatch):
    """A PO can hold a broken line that this receipt does not touch. Refusing the whole receipt for it
    would strand hardware that is physically on the dock over an account nobody is about to post to."""
    monkeypatch.setattr(econnect, "read_po_receipt_context", lambda conn, po: _po_line_context(16384, 32768))
    monkeypatch.setattr(
        econnect,
        "po_lines_with_dangling_account",
        lambda conn, po: [{"ord": 32768, "item": "OTHER", "account_index": 1617, "job": "23093"}],
    )
    monkeypatch.setattr(econnect, "get_next_receipt_number", lambda conn: "RCT0001")
    monkeypatch.setattr(econnect, "create_receipt_line", lambda conn, **kw: None)
    monkeypatch.setattr(econnect, "create_receipt_header", lambda conn, **kw: None)

    response = ops.create_receipt_op(_FakeConn(), company="TUBC", request=_receipt_request(16384))

    assert response.receipt_number == "RCT0001"
    assert response.lines_received == 1


def test_create_receipt_runs_the_preflight_before_reserving_a_receipt_number(monkeypatch):
    """Order matters: taGetPurchReceiptNextNumber burns a GP number. Refusing after it would leave a
    gap in the receipt sequence every time somebody tried a job with broken setup."""
    monkeypatch.setattr(econnect, "read_po_receipt_context", lambda conn, po: _po_line_context(16384))
    monkeypatch.setattr(
        econnect,
        "po_lines_with_dangling_account",
        lambda conn, po: [{"ord": 16384, "item": "ML2010", "account_index": 1617, "job": "23093"}],
    )
    reserved = []
    monkeypatch.setattr(econnect, "get_next_receipt_number", lambda conn: reserved.append(1) or "RCT0001")

    with pytest.raises(RelayOpError):
        ops.create_receipt_op(_FakeConn(), company="TUBC", request=_receipt_request(16384))

    assert reserved == []
