"""Recognising a retry of a PO REGISTRATION instead of registering it twice.

The backend stops waiting for a create_po after 30 seconds, but the relay and GP do not stop with it:
the PO lands. The attempt's key rides into GP on the PO's record note, and the relay reads it back
before it reserves a number, so the retry comes home with the PO the first attempt made.

No GP: a fake connection records each EXEC's SQL and params (the pattern test_po_header_fields.py
uses) and answers the note lookup out of a table it is handed, while the steps around the two things
under test are stubbed exactly as test_po_number_suffix.py stubs them. The note assertions are about
presence and absence as much as values: a request carrying no key must send GP the same SQL it always
did, because a parameter name that turns out to be wrong can then only ever fail a PO that set one.
"""

import threading
import time
from collections import namedtuple
from contextlib import contextmanager
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import channel, econnect, models, ops

_ExecRow = namedtuple("_ExecRow", "error_state err_string")
_FoundRow = namedtuple("_FoundRow", "PONUMBER")

# One attempt's key and the note it becomes. The note text is spelled out here rather than built from
# the same f-string the op uses, so a change to what a GP user reads on the PO fails a test.
_KEY = "8b1f6c22-0e1f-4d44-9f3a-5d2c1c7e5a10"
_NOTE = "UC Nexus registration key 8b1f6c22-0e1f-4d44-9f3a-5d2c1c7e5a10"

_NOTE_TABLES = ("POP10100", "POP30100")


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
            for table, po_number in self._conn.registered.items():
                if f"dbo.{table} h" in self._sql:
                    return _FoundRow(po_number)
            return None
        return _ExecRow(0, "")


class _FakeConn:
    """Every statement the op sends, in order.

    `registered` says which GP table holds a PO whose note carries the key - {'POP10100': 'PO0012300'}
    is "the first attempt's PO is still an active PO". An empty one is a company that has never seen
    this key, which is what a first attempt meets."""

    def __init__(self, registered: dict[str, str] | None = None):
        self.calls: list[tuple[str, tuple]] = []
        self.registered: dict[str, str] = dict(registered or {})

    def cursor(self):
        return _FakeCursor(self)

    def sql_matching(self, needle: str) -> list[tuple[str, tuple]]:
        return [call for call in self.calls if needle in call[0]]

    def tapohdr_calls(self) -> list[tuple[str, tuple]]:
        return self.sql_matching("taPoHdr")

    def note_lookups(self) -> list[tuple[str, tuple]]:
        return self.sql_matching("SY03900")

    def tables_looked_up(self) -> list[str]:
        """Which PO table each registration-key lookup read, in the order it read them."""
        return [
            table for sql, _ in self.note_lookups() for table in _NOTE_TABLES if f"dbo.{table} h" in sql
        ]


def _request(*, header: dict | None = None, **overrides) -> models.CreatePoRequest:
    fields = dict(vendor_id="ING100", buyer_id="mira", confirm_with="mira", doc_date=date(2026, 9, 16))
    fields.update(header or {})
    kwargs = dict(
        company="TUBC",
        header=models.POHeader(**fields),
        lines=[
            models.POLine(
                item_number="ML2010",
                item_description="ML2010 LOCK",
                quantity=Decimal("2"),
                unit_cost=Decimal("12.50"),
            )
        ],
    )
    kwargs.update(overrides)
    return models.CreatePoRequest(**kwargs)


@pytest.fixture
def stubbed(monkeypatch):
    """Everything create_po_op reaches around the two things under test. The two taPoHdr builders and
    the registration-key lookup are left REAL, so what they send lands in the fake connection's call
    list; the GP masters, the number reservation and the line writes are stubbed, because what those
    send is covered where they are the subject. Returns what the stubs recorded."""
    steps: dict[str, list] = {"reserved": [], "lines": [], "wennsoft": []}
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["mira"])
    monkeypatch.setattr(econnect, "shipping_method_exists", lambda conn, method: True)
    monkeypatch.setattr(econnect, "site_exists", lambda conn, site: True)
    monkeypatch.setattr(econnect, "vendor_address_exists", lambda conn, vendor, code: True)
    monkeypatch.setattr(econnect, "get_vendor_currency", lambda conn, vendor_id: "CAD")
    monkeypatch.setattr(
        econnect, "get_mc_setup", lambda conn: {"functional": "CAD", "purchase_rate_type": "BUY"}
    )
    monkeypatch.setattr(econnect, "po_number_in_use", lambda conn, po_number: None)

    def _next_number(conn):
        steps["reserved"].append("PO0012345")
        return "PO0012345"

    monkeypatch.setattr(econnect, "get_next_po_number", _next_number)
    monkeypatch.setattr(econnect, "create_po_line", lambda conn, **kwargs: steps["lines"].append(kwargs))
    monkeypatch.setattr(
        econnect, "apply_wennsoft_integration", lambda conn, **kwargs: steps["wennsoft"].append(kwargs)
    )
    return steps


# --- a request that names no attempt is the PO REGISTRATION that always was ---

def test_a_po_with_no_key_sends_no_note_on_either_header_call(stubbed):
    conn = _FakeConn()

    response = ops.create_po_op(conn, company="TUBC", request=_request())

    calls = conn.tapohdr_calls()
    assert len(calls) == 2
    for sql, _ in calls:
        assert "@I_vNOTETEXT" not in sql
    assert response.existing is False


def test_a_po_with_no_key_still_sends_everything_it_always_did(stubbed):
    # regression guard: the note must not have disturbed what the two header calls exist to write.
    conn = _FakeConn()

    ops.create_po_op(conn, company="TUBC", request=_request())

    create_sql, _ = conn.tapohdr_calls()[0]
    subtotal_sql, subtotal_params = conn.tapohdr_calls()[1]
    assert "@I_vPONUMBER = ?" in create_sql
    assert "@I_vSUBTOTAL = ?" in subtotal_sql
    assert Decimal("25.00") in subtotal_params


def test_a_po_with_no_key_never_reads_the_note_table(stubbed):
    # even against a company that DOES hold a PO under the key: no key sent, no lookup run.
    conn = _FakeConn(registered={"POP10100": "PO0012300"})

    ops.create_po_op(conn, company="TUBC", request=_request())

    assert conn.note_lookups() == []
    assert stubbed["reserved"] == ["PO0012345"]


# --- a key GP has not seen: the PO is registered, carrying the key ---

def test_the_key_is_stamped_on_both_header_calls(stubbed):
    # both, because the second call upserts the same header - one that omitted the note would leave
    # the retry nothing to find.
    conn = _FakeConn()

    response = ops.create_po_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    calls = conn.tapohdr_calls()
    assert len(calls) == 2
    for sql, params in calls:
        assert "@I_vNOTETEXT = ?" in sql
        assert _NOTE in params
    assert response.existing is False


def test_a_key_gp_has_not_seen_registers_the_po_as_usual(stubbed):
    conn = _FakeConn()

    response = ops.create_po_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert conn.tables_looked_up() == ["POP10100", "POP30100"]
    assert stubbed["reserved"] == ["PO0012345"]
    assert len(stubbed["lines"]) == 1
    assert response.po_number == "PO0012345"
    assert response.existing is False


def test_the_lookup_is_pinned_to_the_buyer_and_the_week_before_the_po(stubbed):
    # what keeps a LIKE over GP's note master cheap: one buyer, and only POs dated near this one.
    conn = _FakeConn()

    ops.create_po_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    sql, params = conn.note_lookups()[0]
    assert "h.BUYERID = ?" in sql and "h.DOCDATE >= ?" in sql
    assert params == ("mira", date(2026, 9, 9), f"%{_KEY}%")


# --- a key GP already holds: the PO the earlier attempt made, and no second one ---

def test_a_key_already_in_gp_returns_that_po_and_writes_nothing(stubbed):
    conn = _FakeConn(registered={"POP10100": "PO0012300        "})  # char(17), padded as GP holds it

    response = ops.create_po_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert response.po_number == "PO0012300"
    assert response.existing is True
    assert stubbed["reserved"] == []
    assert stubbed["lines"] == []
    assert stubbed["wennsoft"] == []
    assert conn.tapohdr_calls() == []
    # the active table answered, so history was never read
    assert conn.tables_looked_up() == ["POP10100"]


def test_a_key_found_only_in_history_is_still_a_retry(stubbed):
    # a PO the first attempt made can have been received and moved on before the retry arrives.
    conn = _FakeConn(registered={"POP30100": "PO0012300"})

    response = ops.create_po_op(conn, company="TUBC", request=_request(idempotency_key=_KEY))

    assert response.po_number == "PO0012300"
    assert response.existing is True
    assert conn.tables_looked_up() == ["POP10100", "POP30100"]
    assert stubbed["reserved"] == []
    assert conn.tapohdr_calls() == []


def test_a_found_po_answers_with_the_figures_the_create_would_have(stubbed, monkeypatch):
    """The backend snapshots the subtotal, the currency and the tax off this response, so a retry has
    to answer with what the create it stands in for would have answered - and still write nothing."""
    monkeypatch.setattr(econnect, "get_tax_detail_percent", lambda conn, tax_detail_id: Decimal("5"))
    header = {"tax_detail_id": "BC HST P"}

    created = ops.create_po_op(
        _FakeConn(), company="TUBC", request=_request(header=header, idempotency_key=_KEY)
    )
    found_conn = _FakeConn(registered={"POP10100": "PO0012300"})
    found = ops.create_po_op(
        found_conn, company="TUBC", request=_request(header=header, idempotency_key=_KEY)
    )

    assert found.subtotal == created.subtotal == Decimal("25.00")
    assert found.currency == created.currency == "CAD"
    assert found.tax_amount == created.tax_amount == Decimal("1.25")
    assert found.lines_created == created.lines_created == 1
    assert (found.existing, created.existing) == (True, False)
    # the tax detail is a WRITE; the retry made none.
    assert found_conn.sql_matching("taPopIvcTaxInsert") == []


# --- what the relay says about it ---

def test_the_hello_advertises_the_idempotency_feature():
    # How the backend knows it may send a key at all: an older relay advertises no such string, and a
    # retry against one would reserve a second number.
    assert channel.CREATE_PO_IDEMPOTENCY_FEATURE in channel._hello_frame()["features"]


def test_the_traffic_line_says_when_a_po_was_recognised_rather_than_made():
    reused = {"ok": True, "result": {"po_number": "PO0012300", "existing": True}}
    fresh = {"ok": True, "result": {"po_number": "PO0012345"}}

    assert channel._summarise("create_po", {}, reused) == "PO PO0012300 (existing)"
    assert channel._summarise("create_po", {}, fresh) == "PO PO0012345"


# --- two creates at once ---

class _CommitOnlyConn:
    def cursor(self):
        raise AssertionError("the op is stubbed in these tests; nothing should reach a cursor")

    def commit(self):
        pass

    def rollback(self):
        pass


@contextmanager
def _fake_connection(company):
    yield _CommitOnlyConn()


_PAYLOAD = {
    "header": {
        "vendor_id": "ING100",
        "buyer_id": "mira",
        "confirm_with": "mira",
        "doc_date": "2026-09-16",
    },
    "lines": [
        {"item_number": "ML2010", "item_description": "ML2010 LOCK", "quantity": "2", "unit_cost": "12.50"}
    ],
}


def _response(company: str) -> models.CreatePoResponse:
    return models.CreatePoResponse(
        po_number="PO0012345",
        company=company,
        lines_created=1,
        subtotal=Decimal("25.00"),
        doc_date=date(2026, 9, 16),
        vendor_id="ING100",
    )


def _run_together(companies_: list[str]) -> list[BaseException]:
    """Fire one _run_create_po per company from its own thread, all released at the same moment, and
    hand back whatever any of them raised."""
    start = threading.Barrier(len(companies_))
    errors: list[BaseException] = []

    def _go(company):
        try:
            start.wait(timeout=5)
            channel._run_create_po(company, _PAYLOAD)
        except BaseException as exc:  # noqa: BLE001 - the assertion is that nothing was raised
            errors.append(exc)

    threads = [threading.Thread(target=_go, args=(company,)) for company in companies_]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return errors


def test_two_creates_for_one_company_run_one_after_the_other(monkeypatch, serving):
    """A retry that arrives while the first attempt is still inside GP has to wait for it: only a
    committed PO can be found by its key, so two running together would both miss and both reserve."""
    serving(["TUBC"])
    monkeypatch.setattr(channel.db, "get_connection", _fake_connection)
    inside: list[str] = []
    seen: list[tuple[str, ...]] = []
    probe = threading.Lock()

    def _slow_create(conn, *, company, request):
        with probe:
            inside.append(company)
            seen.append(tuple(inside))
        time.sleep(0.05)
        with probe:
            inside.remove(company)
        return _response(company)

    monkeypatch.setattr(channel.ops, "create_po_op", _slow_create)

    errors = _run_together(["TUBC", "TUBC"])

    assert errors == []
    assert len(seen) == 2
    assert max(len(moment) for moment in seen) == 1


def test_two_companies_are_not_held_up_by_each_other(monkeypatch, serving):
    """The lock is per company, not one queue for the whole relay: a TUBC registration must not wait
    behind a UCSH one."""
    serving(["TUBC", "UCSH"])
    monkeypatch.setattr(channel.db, "get_connection", _fake_connection)
    # Passing this barrier is only possible if the other company's create is inside at the same time;
    # one queue behind the other and it breaks on the timeout instead.
    both_inside = threading.Barrier(2)

    def _create(conn, *, company, request):
        both_inside.wait(timeout=5)
        return _response(company)

    monkeypatch.setattr(channel.ops, "create_po_op", _create)

    assert _run_together(["TUBC", "UCSH"]) == []
