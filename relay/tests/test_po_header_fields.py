"""The rest of what GP's Purchase Order Entry takes, now carried by a PO raised in Nexus: the header's
contact and comment on both taPoHdr calls, and the three pre-checks that refuse a shipping method,
site or vendor address code GP does not hold.

No GP: a fake cursor records each EXEC's SQL and params, matching test_create_po_line.py. The
contact/comment assertions are about presence and absence rather than values alone - an omitted
parameter is the whole point of the design, because eConnect only writes a header field it is passed,
so a parameter name that turns out to be wrong can only ever fail a PO that set that field."""

from collections import namedtuple
from datetime import date
from decimal import Decimal

import pytest

from ucnexus_relay import econnect, models, ops
from ucnexus_relay.econnect import create_po_header, update_po_header_subtotal
from ucnexus_relay.ops import RelayOpError

_ExecRow = namedtuple("_ExecRow", "error_state err_string")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, *params):
        self._conn.calls.append((sql, params))
        return self

    def fetchone(self):
        return _ExecRow(0, "")


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def cursor(self):
        return _FakeCursor(self)

    def tapohdr_call(self):
        return next(c for c in self.calls if "taPoHdr" in c[0])


def _header(conn, **overrides):
    kwargs = dict(
        po_number="PO0000001",
        vendor_id="ING100",
        doc_date=date(2026, 1, 1),
        buyer_id="mira",
        confirm_with="mira",
    )
    kwargs.update(overrides)
    create_po_header(conn, **kwargs)


def _subtotal(conn, **overrides):
    kwargs = dict(
        po_number="PO0000001",
        vendor_id="ING100",
        doc_date=date(2026, 1, 1),
        buyer_id="mira",
        confirm_with="mira",
        subtotal=Decimal("25.00"),
    )
    kwargs.update(overrides)
    update_po_header_subtotal(conn, **kwargs)


# --- the contact and the comment on taPoHdr ---

def test_contact_is_bound_when_the_po_sets_one():
    conn = _FakeConn()
    _header(conn, contact="Jane Doe")
    sql, params = conn.tapohdr_call()
    assert "@I_vCONTACT = ?" in sql
    assert "Jane Doe" in params


def test_contact_is_not_sent_at_all_when_absent():
    conn = _FakeConn()
    _header(conn)
    sql, _ = conn.tapohdr_call()
    assert "@I_vCONTACT" not in sql


def test_comment_is_bound_as_gps_id_and_text_pair():
    # GP's header comment is an id naming a master comment plus the text itself. Nexus writes free
    # text, so the id goes blank and the text is what lands on POP10150.
    conn = _FakeConn()
    _header(conn, comment="Deliver to the loading bay")
    sql, params = conn.tapohdr_call()
    assert "@I_vCOMMNTID = ?" in sql
    assert "@I_vCMMTTEXT = ?" in sql
    assert "Deliver to the loading bay" in params
    assert "" in params


def test_comment_is_not_sent_at_all_when_absent():
    conn = _FakeConn()
    _header(conn)
    sql, _ = conn.tapohdr_call()
    assert "@I_vCOMMNTID" not in sql
    assert "@I_vCMMTTEXT" not in sql


def test_the_subtotal_update_sends_the_same_pair():
    # this call upserts the same header, so a field the create wrote and the update omits would be
    # written and then left behind - the two have to send the same set.
    conn = _FakeConn()
    _subtotal(conn, contact="Jane Doe", comment="Deliver to the loading bay")
    sql, params = conn.tapohdr_call()
    assert "@I_vCONTACT = ?" in sql
    assert "@I_vCOMMNTID = ?" in sql
    assert "@I_vCMMTTEXT = ?" in sql
    assert "Jane Doe" in params
    assert "Deliver to the loading bay" in params


def test_the_subtotal_update_omits_them_too():
    conn = _FakeConn()
    _subtotal(conn)
    sql, _ = conn.tapohdr_call()
    assert "@I_vCONTACT" not in sql
    assert "@I_vCOMMNTID" not in sql
    assert "@I_vCMMTTEXT" not in sql


def test_the_subtotal_update_still_sends_its_own_fields():
    # regression guard: adding the pair must not disturb what the second call exists to write.
    conn = _FakeConn()
    _subtotal(conn, contact="Jane Doe")
    sql, params = conn.tapohdr_call()
    assert "@I_vSUBTOTAL = ?" in sql
    assert Decimal("25.00") in params


# --- the three create_po pre-checks ---

class _NoSqlConn:
    def cursor(self):
        raise AssertionError("the pre-checks under test are stubbed; nothing here should reach SQL")


_REFUSALS = ("shipping_method_not_registered", "site_not_registered", "vendor_address_not_registered")


def _po(*, lines=None, **header):
    fields = dict(vendor_id="ING100", buyer_id="mira", confirm_with="mira", doc_date=date(2026, 1, 1))
    fields.update(header)
    return models.CreatePoRequest(
        company="TUBC",
        header=models.POHeader(**fields),
        lines=lines or [
            models.POLine(
                item_number="ML2010",
                item_description="ML2010 LOCK",
                quantity=Decimal("2"),
                unit_cost=Decimal("12.50"),
            )
        ],
    )


def _stub(monkeypatch, *, shipping=True, site=True, address=True, sites_seen=None):
    """Everything create_po_op does up to and including the checks under test. Anything AFTER them is
    left unstubbed on purpose: if a check fails to refuse, the op walks into a real cursor and the
    test breaks loudly rather than passing quietly."""
    monkeypatch.setattr(econnect, "list_buyers", lambda conn: ["mira"])
    monkeypatch.setattr(econnect, "shipping_method_exists", lambda conn, method: shipping)

    def _site_exists(conn, value):
        if sites_seen is not None:
            sites_seen.append(value)
        return site

    monkeypatch.setattr(econnect, "site_exists", _site_exists)
    monkeypatch.setattr(econnect, "vendor_address_exists", lambda conn, vendor, code: address)


def test_an_unregistered_shipping_method_is_refused_by_name(monkeypatch):
    _stub(monkeypatch, shipping=False)

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po(shipping_method="BY DRONE"))

    assert excinfo.value.code == "shipping_method_not_registered"
    assert "BY DRONE" in excinfo.value.message
    assert "TUBC" in excinfo.value.message


def test_a_site_gp_does_not_hold_is_refused_by_name(monkeypatch):
    _stub(monkeypatch, site=False)

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po(site="NARNIA"))

    assert excinfo.value.code == "site_not_registered"
    assert "NARNIA" in excinfo.value.message
    assert "TUBC" in excinfo.value.message


def test_a_vendor_address_code_the_vendor_lacks_is_refused_by_name(monkeypatch):
    _stub(monkeypatch, address=False)

    with pytest.raises(RelayOpError) as excinfo:
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po(vendor_address_code="REMIT"))

    assert excinfo.value.code == "vendor_address_not_registered"
    assert "REMIT" in excinfo.value.message
    assert "ING100" in excinfo.value.message
    assert "TUBC" in excinfo.value.message


def test_values_gp_holds_are_accepted(monkeypatch):
    """Passing must not be provable by the op never reaching the checks, so this asserts the op got
    PAST them: it fails on the next unstubbed step, not on one of the three refusals."""
    _stub(monkeypatch)

    with pytest.raises(Exception) as excinfo:  # noqa: B017 - anything but the three under test
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po())

    assert getattr(excinfo.value, "code", None) not in _REFUSALS


def test_the_site_checked_is_the_one_each_line_resolves_to(monkeypatch):
    # the header's site is only the fallback for a line that names none, so what is checked is what
    # the lines actually land on - a line with its own site, and the header's for one without.
    seen: list[str] = []
    _stub(monkeypatch, sites_seen=seen)
    lines = [
        models.POLine(item_number="A", item_description="a", quantity=Decimal(1), unit_cost=Decimal(1)),
        models.POLine(
            item_number="B", item_description="b", quantity=Decimal(1), unit_cost=Decimal(1),
            location_code="SHOWROOM",
        ),
    ]

    with pytest.raises(Exception):  # noqa: B017 - the op runs on past the checks
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po(site="VANCOUVER", lines=lines))

    assert seen == ["VANCOUVER", "SHOWROOM"]


def test_a_site_repeated_across_lines_is_checked_once(monkeypatch):
    seen: list[str] = []
    _stub(monkeypatch, sites_seen=seen)
    lines = [
        models.POLine(item_number=str(i), item_description="x", quantity=Decimal(1), unit_cost=Decimal(1))
        for i in range(3)
    ]

    with pytest.raises(Exception):  # noqa: B017
        ops.create_po_op(_NoSqlConn(), company="TUBC", request=_po(lines=lines))

    assert seen == ["VANCOUVER"]
