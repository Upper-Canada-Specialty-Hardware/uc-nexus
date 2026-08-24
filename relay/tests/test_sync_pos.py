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
    """Routes execute() by SQL text to a rows table, and remembers the last query for assertions."""

    def __init__(self, rows_by_kind):
        self._rows = rows_by_kind
        self._kind = None
        self.last_sql = None
        self.all_sql = []

    def execute(self, sql, *params):
        self.last_sql = sql
        self.all_sql.append(sql)
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
