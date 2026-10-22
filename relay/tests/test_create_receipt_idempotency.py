"""Recognising a retry of a GP RECEIVE instead of posting the receipt twice (#1389).

The backend stops waiting for a create_receipt after 30 seconds, but the relay and GP do not stop with
it: the receipt lands in its batch. The attempt's key rides into GP on the receipt's record note, and
the relay reads it back before anything else, so the retry comes home with the receipt the first
attempt posted.

No GP: a fake connection records each statement's SQL and params and answers the note lookup out of a
table it is handed, the pattern test_create_po_idempotency.py uses. The header write and the lookup are
left real; the PO context, the job check, the number and the lines are stubbed.
"""

import threading
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import channel, econnect, models, ops
from ucnexus_relay.ops import RelayOpError

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_FoundRow = namedtuple("_FoundRow", "POPRCTNM BACHNUMB")

# Spelled out rather than built from the op's f-string, so a change to what a GP user reads behind the
# receipt's note icon fails a test.
_KEY = "3c9e1f7a-52b4-4d0e-8a61-0f2b7d9c4e18"
_NOTE = "UC Nexus receipt key 3c9e1f7a-52b4-4d0e-8a61-0f2b7d9c4e18"

_RECEIPT_TABLES = ("POP10300", "POP30300")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self._sql = ""

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        self._sql = sql
        return self

    def fetchone(self):
        if "SY03900" in self._sql:
            for table, found in self._conn.posted.items():
                if f"dbo.{table} h" in self._sql:
                    return _FoundRow(*found)
            return None
        return _ExecRow(0, "")


class _FakeConn:
    """`posted` says which GP table holds a receipt whose note carries the key -
    {'POP10300': ('RCT0000111', 'EC-2026/10/08')} is "the first attempt's receipt is still in its
    unposted batch". Empty is a company that has never seen the key."""

    def __init__(self, posted: dict[str, tuple[str, str]] | None = None):
        self.calls: list[tuple[str, tuple]] = []
        self.posted = dict(posted or {})

    def cursor(self):
        return _FakeCursor(self)

    def sql_matching(self, needle: str) -> list[tuple[str, tuple]]:
        return [call for call in self.calls if needle in call[0]]

    def note_lookups(self) -> list[tuple[str, tuple]]:
        return self.sql_matching("SY03900")

    def tables_looked_up(self) -> list[str]:
        return [table for sql, _ in self.note_lookups() for table in _RECEIPT_TABLES if f"dbo.{table} h" in sql]


def _request(**overrides) -> models.ReceiptRequest:
    kwargs = dict(
        company="TUBC",
        po_number="PO0000143",
        lines=[models.ReceiptLine(po_line_ord=16384, quantity=Decimal("2"), rack_location="A1")],
        receipt_date=date(2026, 10, 8),
    )
    kwargs.update(overrides)
    return models.ReceiptRequest(**kwargs)


@pytest.fixture
def stubbed(monkeypatch):
    """Everything create_receipt_op reaches around the header write and the key lookup. Returns what the
    write stubs recorded, so a test can say nothing was written."""
    steps: dict[str, list] = {"context": [], "reserved": [], "lines": [], "whrecline": []}
    lines = {
        16384: {
            "item": "ML2010",
            "itemdesc": "ML2010 LOCK",
            "vendor": "ING100",
            "vnditnum": "ML2010",
            "uofm": "Each",
            "job": "22004",
            "jobname": "TOWER",
            "locn": "VANCOUVER",
            "noninven": 1,
            "polnesta": 2,
            "qtyorder": Decimal("2"),
            "qtycance": Decimal("0"),
            "prev_received": Decimal("0"),
            "unitcost": Decimal("12.50"),
        }
    }

    def _context(conn, po):
        steps["context"].append(po)
        return "ING100", "Ingersoll", lines

    def _next_number(conn):
        steps["reserved"].append("RCT0000112")
        return "RCT0000112"

    monkeypatch.setattr(econnect, "read_po_receipt_context", _context)
    monkeypatch.setattr(econnect, "job_state", lambda conn, job: "active")
    monkeypatch.setattr(econnect, "po_lines_with_dangling_account", lambda conn, po: [])
    monkeypatch.setattr(econnect, "get_next_receipt_number", _next_number)
    monkeypatch.setattr(econnect, "create_receipt_line", lambda conn, **kw: steps["lines"].append(kw))
    monkeypatch.setattr(econnect, "insert_whrecline_row", lambda conn, **kw: steps["whrecline"].append(kw))
    return steps


def _header_calls(conn: _FakeConn) -> list[tuple[str, tuple]]:
    return conn.sql_matching("taPopRcptHdrInsert")


# --- a request that names no attempt is the GP RECEIVE that always was ---


def test_a_receipt_with_no_key_sends_no_note_and_reads_no_note(stubbed):
    # even against a company that DOES hold a receipt under some key: no key sent, no lookup run.
    conn = _FakeConn(posted={"POP10300": ("RCT0000111", "EC-2026/10/08")})

    response = ops.create_receipt_op(conn, company="TUBC", request=_request())

    ((sql, params),) = _header_calls(conn)
    assert "@I_vNOTETEXT" not in sql
    assert len(params) == 6
    assert conn.note_lookups() == []
    assert response.receipt_number == "RCT0000112"
    assert response.existing is False


# --- a key GP has not seen: the receipt is posted, carrying the key ---


def test_a_new_key_is_looked_up_in_both_tables_then_stamped_on_the_header(stubbed):
    conn = _FakeConn()

    response = ops.create_receipt_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert conn.tables_looked_up() == ["POP10300", "POP30300"]
    ((sql, params),) = _header_calls(conn)
    assert "@I_vNOTETEXT   = ?" in sql
    assert params[-1] == _NOTE
    assert stubbed["reserved"] == ["RCT0000112"]
    assert response.existing is False


def test_the_lookup_is_pinned_to_the_po_and_reads_every_note_slot(stubbed):
    # VNDDOCNM is what keeps the join to one PO's receipts; the eight slots are because the encrypted
    # proc does not show which one its NOTETEXT fills; NOTEINDX 0 is an empty slot, never a match.
    conn = _FakeConn()

    ops.create_receipt_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    sql, params = conn.note_lookups()[0]
    assert "h.VNDDOCNM = ?" in sql
    assert "n.NOTEINDX <> 0" in sql
    for slot in range(1, 9):
        assert f"h.RCPTNOTE_{slot}" in sql
    assert params == ("PO0000143", f"%{_KEY}%")


# --- a key GP has seen: the receipt the first attempt posted comes back, and nothing is written ---


def test_a_key_found_in_the_unposted_batch_returns_that_receipt_and_writes_nothing(stubbed):
    conn = _FakeConn(posted={"POP10300": ("RCT0000111", "EC-2026/10/08")})

    response = ops.create_receipt_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert response.receipt_number == "RCT0000111"
    assert response.batch_number == "EC-2026/10/08"
    assert response.existing is True
    assert conn.tables_looked_up() == ["POP10300"]
    assert _header_calls(conn) == []
    assert stubbed["reserved"] == [] and stubbed["lines"] == [] and stubbed["whrecline"] == []


def test_a_key_found_only_in_history_is_still_a_retry(stubbed):
    # somebody posted the batch in GP before the retry arrived.
    conn = _FakeConn(posted={"POP30300": ("RCT0000111", "EC-2026/10/08")})

    response = ops.create_receipt_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert response.receipt_number == "RCT0000111"
    assert response.existing is True
    assert conn.tables_looked_up() == ["POP10300", "POP30300"]
    assert stubbed["reserved"] == []


def test_the_lookup_runs_before_the_remaining_quantity_check(stubbed, monkeypatch):
    # GP counts an unposted receipt toward the line's received quantity, so after the first attempt the
    # line reads fully received. A retry must be recognised, not refused as qty_exceeds_remaining.
    full = {
        16384: {
            "polnesta": 2,
            "qtyorder": Decimal("2"),
            "qtycance": Decimal("0"),
            "prev_received": Decimal("2"),
            "job": "22004",
        }
    }
    monkeypatch.setattr(econnect, "read_po_receipt_context", lambda conn, po: ("ING100", "Ingersoll", full))
    conn = _FakeConn(posted={"POP10300": ("RCT0000111", "EC-2026/10/08")})

    response = ops.create_receipt_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))
    assert response.existing is True

    # the same request with a key GP has never seen is refused, as before.
    with pytest.raises(RelayOpError) as excinfo:
        ops.create_receipt_op(_FakeConn(), company="TUBC", request=_request(idempotency_key=_KEY))
    assert excinfo.value.code == "qty_exceeds_remaining"


def _line_with(*, ordered: str, cancelled: str, received: str) -> dict:
    return {
        16384: {
            "item": "ML2010",
            "itemdesc": "ML2010 LOCK",
            "vendor": "ING100",
            "vnditnum": "ML2010",
            "uofm": "Each",
            "job": "",
            "jobname": None,
            "locn": "VANCOUVER",
            "noninven": 1,
            "polnesta": 2,
            "qtyorder": Decimal(ordered),
            "qtycance": Decimal(cancelled),
            "prev_received": Decimal(received),
            "unitcost": Decimal("12.50"),
        }
    }


def test_the_remaining_quantity_nets_what_gp_cancelled(stubbed, monkeypatch):
    # #1861: 5 ordered, 2 cancelled in GP, 1 received - 2 are left to receive, not 4.
    line = _line_with(ordered="5", cancelled="2", received="1")
    monkeypatch.setattr(econnect, "read_po_receipt_context", lambda conn, po: ("ING100", "Ingersoll", line))
    over = [models.ReceiptLine(po_line_ord=16384, quantity=Decimal("3"), rack_location="A1")]

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_receipt_op(_FakeConn(), company="TUBC", request=_request(lines=over))

    assert excinfo.value.code == "qty_exceeds_remaining"
    assert "remaining 2" in excinfo.value.message and "cancelled 2" in excinfo.value.message
    assert stubbed["reserved"] == []

    response = ops.create_receipt_op(_FakeConn(), company="TUBC", request=_request())
    assert response.lines_received == 1


def test_the_receipt_context_reads_the_cancelled_quantity():
    class _Cursor:
        def __init__(self):
            self.sql: list[str] = []

        def execute(self, sql, *params):
            self.sql.append(sql)
            return self

        def fetchone(self):
            return namedtuple("_Hdr", "vendor vendname")("ING100", "Ingersoll")

        def fetchall(self):
            fields = (
                "ORD item itemdesc vendor job jobname locn NONINVEN uofm vnditnum QTYORDER QTYCANCE UNITCOST "
                "POLNESTA prev_received"
            )
            row = namedtuple("_Line", fields)(
                16384, "ML2010", "LOCK", "ING100", "", None, "VAN", 1, "Each", "", 5, 2, 12.5, 2, 1
            )
            return [row]

    cursor = _Cursor()
    conn = type("_Conn", (), {"cursor": lambda self: cursor})()

    _, _, lines = econnect.read_po_receipt_context(conn, "PO0000143")

    assert "l.QTYCANCE" in cursor.sql[1]
    assert lines[16384]["qtycance"] == 2


def test_an_overlong_key_is_refused_by_the_model():
    with pytest.raises(ValueError):
        _request(idempotency_key="k" * 65)


@pytest.mark.parametrize("bad", ["%", "_", "[a-z]", "ab%cd", "key with space", "key'quote", "k\\1"])
def test_a_key_carrying_like_syntax_is_refused_by_the_model(bad):
    # #1860: the key is matched inside GP's note text with LIKE, where these characters are pattern syntax.
    with pytest.raises(ValueError):
        _request(idempotency_key=bad)


@pytest.mark.parametrize("good", [_KEY, "demo-seed-approve-3c9e1f7a-52b4-4d0e-8a61-0f2b7d9c4e18", "k-1", ""])
def test_the_keys_the_backend_mints_are_accepted(good):
    assert _request(idempotency_key=good).idempotency_key == good


def test_the_receipt_lookup_escapes_its_pattern():
    conn = _FakeConn()

    econnect.find_receipt_by_note(conn, key="a%b_c[d", po_number="PO0000143")

    sql, params = conn.note_lookups()[0]
    assert "LIKE ? ESCAPE '\\'" in sql
    assert params == ("PO0000143", "%a\\%b\\_c\\[d%")


# --- what the relay says about it, and how it serialises ---


def test_the_hello_advertises_the_receipt_idempotency_feature():
    assert channel.CREATE_RECEIPT_IDEMPOTENCY_FEATURE == "create_receipt_idempotency"
    assert channel.CREATE_RECEIPT_IDEMPOTENCY_FEATURE in channel._hello_frame()["features"]


def test_two_receipts_for_one_company_run_one_at_a_time(monkeypatch):
    # a retry finds the first attempt by its committed receipt, so the two must not overlap.
    active = {"now": 0, "max": 0, "committed": 0}
    guard = threading.Lock()

    class _Conn:
        def commit(self):
            with guard:
                active["committed"] += 1

        def rollback(self):
            pass

    @contextmanager
    def _connection(company):
        yield _Conn()

    def _op(conn, *, company, request):
        with guard:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
        time.sleep(0.05)
        with guard:
            active["now"] -= 1
        return models.ReceiptResponse(
            receipt_number="RCT1",
            batch_number="EC-2026/10/08",
            po_number=request.po_number,
            company=company,
            lines_received=1,
            custom_db_written=False,
        )

    monkeypatch.setattr(channel.ops, "check_company_served", lambda company: None)
    monkeypatch.setattr(channel.db, "get_connection", _connection)
    monkeypatch.setattr(channel.ops, "create_receipt_op", _op)
    payload = _request(idempotency_key=_KEY).model_dump(mode="json", exclude={"company"})

    threads = [threading.Thread(target=channel._run_create_receipt, args=("TUBC", payload)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert active["max"] == 1
    assert active["committed"] == 3
    assert channel._create_receipt_lock("TUBC").locked() is False


def test_the_receipt_lock_is_not_the_po_lock():
    assert channel._create_receipt_lock("TUBC") is not channel._create_po_lock("TUBC")
    assert channel._create_receipt_lock("TUBC") is channel._create_receipt_lock("TUBC")
