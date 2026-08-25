"""econnect.sync_pos: the GP PO mirror read (gp-owned-po mirror). A fake pyodbc cursor routes each
SELECT by the table it names, so no test touches GP. Covers backfill assembly + keyset next_cursor,
the short-page terminator, the work-vs-history received-qty rule, and the incremental mode."""

from datetime import datetime

from ucnexus_relay import econnect


class _Row:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _hdr(src, po, status=2, vendor="VEND01", vendname="Acme Supply"):
    return _Row(
        src=src,
        po=po,
        status=status,
        vendor=vendor,
        vendname=vendname,
        docdate=datetime(2026, 1, 2, 0, 0, 0),
        modified=datetime(2026, 1, 3, 8, 30, 0),
    )


def _line(po, ord_, item, qty, cancelled=0, unit_cost=10, status=2):
    return _Row(po=po, ORD=ord_, item=item, itemdesc=f"{item} desc", UNITCOST=unit_cost,
                QTYORDER=qty, QTYCANCE=cancelled, job="JOB1", POLNESTA=status)


def _rcv(po, polnenum, received):
    return _Row(po=po, POLNENUM=polnenum, received=received)


class _Cursor:
    """Routes execute() by SQL text to a rows table, and remembers every query + its bound params."""

    def __init__(self, rows_by_kind):
        self._rows = rows_by_kind
        self._kind = None
        self.last_sql = None
        self.all_sql = []
        self.calls = []  # (sql, params) per execute, for param-binding assertions

    def execute(self, sql, *params):
        self.last_sql = sql
        self.all_sql.append(sql)
        self.calls.append((sql, params))
        if "POP10110" in sql:
            self._kind = "work_lines"
        elif "POP30110" in sql:
            self._kind = "hist_lines"
        elif "POP10500" in sql:
            self._kind = "received"
        else:
            self._kind = "headers"
        return self

    def fetchall(self):
        return list(self._rows.get(self._kind, []))


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_backfill_assembles_lines_received_and_next_cursor():
    rows = {
        "headers": [_hdr("work", "PO000010"), _hdr("history", "PO000005")],
        "work_lines": [_line("PO000010", 16384, "ITEM-A", qty=5)],
        "hist_lines": [_line("PO000005", 16384, "ITEM-B", qty=4, cancelled=1)],
        "received": [_rcv("PO000010", 16384, 3)],
    }
    conn = _Conn(_Cursor(rows))
    out = econnect.sync_pos(conn, cursor=None, page_size=2, modified_since=None)

    assert out["next_cursor"] == "PO000005"  # page filled to page_size -> more may remain
    by_po = {p["po_number"]: p for p in out["pos"]}

    work = by_po["PO000010"]
    assert work["source_table"] == "work"
    assert work["gp_status"] == 2
    assert work["vendor_id"] == "VEND01" and work["vendor_name"] == "Acme Supply"
    assert work["doc_date"] == "2026-01-02"
    # open PO: received comes from the POP10500 sum, not ordered-minus-cancelled.
    assert work["lines"][0]["received"] == 3.0
    assert work["lines"][0]["qty"] == 5.0

    hist = by_po["PO000005"]
    assert hist["source_table"] == "history"
    # history PO: received is derived qty - cancelled (4 - 1).
    assert hist["lines"][0]["received"] == 3.0


def test_backfill_short_page_ends_the_walk():
    rows = {
        "headers": [_hdr("work", "PO000010")],
        "work_lines": [_line("PO000010", 16384, "ITEM-A", qty=2)],
        "received": [],
    }
    conn = _Conn(_Cursor(rows))
    out = econnect.sync_pos(conn, cursor="PO000009", page_size=2, modified_since=None)
    # fewer rows than page_size -> the backfill is drained.
    assert out["next_cursor"] is None
    assert out["pos"][0]["lines"][0]["received"] == 0.0  # no POP10500 rows -> 0 received


def test_incremental_mode_never_paginates():
    rows = {
        "headers": [_hdr("work", "PO000020")],
        "work_lines": [_line("PO000020", 16384, "ITEM-C", qty=7)],
        "received": [_rcv("PO000020", 16384, 7)],
    }
    cursor = _Cursor(rows)
    out = econnect.sync_pos(_Conn(cursor), cursor=None, page_size=300, modified_since="2026-01-01T00:00:00")
    assert out["next_cursor"] is None
    assert out["pos"][0]["lines"][0]["received"] == 7.0
    # incremental filters history on the modified timestamp and does not use TOP.
    header_sql = next(s for s in cursor.all_sql if "UNION ALL" in s)
    assert "DEX_ROW_TS >= ?" in header_sql
    assert "TOP" not in header_sql


def test_incremental_binds_a_datetime_not_a_fractional_string():
    # the backend sends the watermark as datetime.isoformat() -> 6 fractional digits. Bound as a string
    # against DEX_ROW_TS that is a Msg 241 datetime literal (>3 fractional digits rejected), so the
    # reader must parse it to a real datetime before binding.
    rows = {
        "headers": [_hdr("work", "PO000020")],
        "work_lines": [_line("PO000020", 16384, "ITEM-C", qty=7)],
        "received": [_rcv("PO000020", 16384, 7)],
    }
    cursor = _Cursor(rows)
    econnect.sync_pos(_Conn(cursor), cursor=None, page_size=300, modified_since="2026-01-01T00:00:00.123456")
    header_call = next((s, p) for s, p in cursor.calls if "UNION ALL" in s)
    bound = header_call[1][0]
    assert isinstance(bound, datetime) and not isinstance(bound, str)
    assert bound == datetime(2026, 1, 1, 0, 0, 0, 123456)  # microseconds preserved on the datetime


def test_incremental_parses_watermark_without_microseconds():
    # backfill watermarks / round-numbered timestamps arrive with no fractional part; still a datetime.
    rows = {"headers": [_hdr("work", "PO000020")], "work_lines": [], "received": []}
    cursor = _Cursor(rows)
    econnect.sync_pos(_Conn(cursor), cursor=None, page_size=300, modified_since="2026-02-03T09:15:30")
    bound = next(p for s, p in cursor.calls if "UNION ALL" in s)[0]
    assert isinstance(bound, datetime)
    assert bound == datetime(2026, 2, 3, 9, 15, 30)


def test_large_backfill_chunks_the_in_lists():
    # more than one IN-chunk worth of open POs must not go into a single >2100-param statement.
    n = econnect._PO_IN_CHUNK + 5
    po_nums = [f"PO{i:06d}" for i in range(n)]
    rows = {"headers": [_hdr("work", po) for po in po_nums], "work_lines": [], "received": []}
    cursor = _Cursor(rows)
    econnect.sync_pos(_Conn(cursor), cursor=None, page_size=econnect._MAX_PO_PAGE_SIZE, modified_since=None)

    line_calls = [p for s, p in cursor.calls if "POP10110" in s]
    rcv_calls = [p for s, p in cursor.calls if "POP10500" in s]
    assert len(line_calls) == 2 and len(rcv_calls) == 2  # 1005 ids -> chunks of 1000 + 5
    for params in line_calls + rcv_calls:
        assert 0 < len(params) <= econnect._PO_IN_CHUNK  # never exceeds the 2100-param ceiling
    assert sum(len(p) for p in line_calls) == n  # every id queried exactly once, no drops
    assert sum(len(p) for p in rcv_calls) == n


def test_backfill_keyset_uses_raw_ponumber_not_trimmed():
    rows = {"headers": [_hdr("work", "PO000010")], "work_lines": [], "received": []}
    cursor = _Cursor(rows)
    # page_size=1 fills the page, so the returned cursor is the last row's po (not a short-page None).
    out = econnect.sync_pos(_Conn(cursor), cursor="PO000005", page_size=1, modified_since=None)
    header_sql = next(s for s in cursor.all_sql if "UNION ALL" in s)
    # keyset filter + order run on the RAW char column (sargable, seeks the clustered PK), not RTRIM().
    assert "WHERE u.po_raw > ?" in header_sql
    assert "ORDER BY u.po_raw" in header_sql
    assert "PONUMBER AS po_raw" in header_sql
    # the trimmed value is still selected as `po`, which is the cursor handed back and round-tripped.
    assert "RTRIM(PONUMBER) AS po" in header_sql
    assert out["next_cursor"] == "PO000010"  # returned cursor is the trimmed po (round-trips as keyset)
    # the incoming cursor is bound raw against po_raw as the second header param (after TOP page_size).
    header_params = next(p for s, p in cursor.calls if "UNION ALL" in s)
    assert header_params == (1, "PO000005")
