"""Server-driven register paging/search (gp-owned-po mirror). DB-backed (db_session).

The escaping assertions are the ones that matter: a user typing % or _ into the register search must
search for the literal character, not fire a SQL LIKE wildcard that matches everything.
"""

import uuid
from decimal import Decimal

from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository


def _make_po(session, *, po_number, vendor="Acme"):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=po_number,
        request_number=None,
        status=POStatus.GP_REGISTERED,
        gp_company="TUBC",
        vendor_name_snapshot=vendor,
    )
    session.add(po)
    session.flush()
    return po


def _search_numbers(session, term):
    rows, _counts, _total = po_repository.get_purchase_orders_page(session, search=term)
    return {r.po_number for r in rows}


def test_percent_in_search_is_a_literal_not_a_wildcard(db_session):
    literal = _make_po(db_session, po_number="PO50%OFF")
    _make_po(db_session, po_number="PO5099")
    db_session.flush()

    # Unescaped, "%50%%" would match anything containing "50"; escaped, it matches only the literal "50%".
    assert _search_numbers(db_session, "50%") == {literal.po_number}


def test_underscore_in_search_is_a_literal_not_a_single_char_wildcard(db_session):
    literal = _make_po(db_session, po_number="PO_A")
    _make_po(db_session, po_number="POXA")
    db_session.flush()

    # Unescaped, "_A" would match POXA too (underscore = any one char); escaped, only the literal "_A".
    assert _search_numbers(db_session, "_A") == {literal.po_number}


def test_plain_search_still_matches_substrings(db_session):
    a = _make_po(db_session, po_number="PO-ALPHA-1", vendor="Widgets Inc")
    _make_po(db_session, po_number="PO-BETA-2", vendor="Other Co")
    db_session.flush()

    assert _search_numbers(db_session, "ALPHA") == {a.po_number}
    assert _search_numbers(db_session, "widgets") == {a.po_number}  # ILIKE is case-insensitive


def test_backslash_in_search_does_not_break(db_session):
    _make_po(db_session, po_number="PO-PLAIN")
    db_session.flush()
    # A stray backslash must be escaped, not left to consume the next char as a LIKE escape.
    assert _search_numbers(db_session, "\\") == set()


def test_page_row_carries_line_item_count_scalar_not_collection(db_session):
    po = _make_po(db_session, po_number="PO-COUNT-1")
    for ord_ in (1, 2):
        from app.models.purchase_order import POLineItem

        db_session.add(
            POLineItem(
                id=uuid.uuid4(),
                po_id=po.id,
                hardware_category="HINGE",
                product_code="HG-100",
                ordered_quantity=3,
                received_quantity=0,
                unit_cost=Decimal("1.00"),
                gp_line_ord=ord_ * 16384,
            )
        )
    db_session.flush()

    rows, counts, total = po_repository.get_purchase_orders_page(db_session, search="PO-COUNT-1")
    assert total == 1
    assert counts[rows[0].id] == 2


# --- #632: Created By on a register row ------------------------------------------------------------
# Resolved server-side over the page's DISTINCT author ids rather than one Clerk lookup per row - a
# per-row lookup is the N+1 that turns a 50-row page into 50 network calls. No database: the point is
# the resolution and the two fallbacks, so the repository read and Clerk are both stubbed.


class _StubRow:
    """The columns po_list_row_to_type and the Created By resolution read off a register row."""

    def __init__(self, *, po_number, created_by_user_id=None, buyer_id=None):
        from datetime import datetime

        from app.models.enums import POOrigin, POStatus

        self.id = uuid.uuid4()
        self.po_number = po_number
        self.request_number = None
        self.project_id = None
        self.status = POStatus.GP_REGISTERED
        self.origin = POOrigin.GP
        self.gp_company = "TUBC"
        self.vendor_name_snapshot = "Acme"
        self.ordered_at = None
        self.expected_delivery_date = None
        self.created_at = datetime(2026, 1, 1)
        self.gp_synced_at = None
        self.created_by_user_id = created_by_user_id
        self.buyer_id = buyer_id


class _NullSession:
    """The resolver opens its own session and hands it to a stubbed repository, so it never gets used."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _page(monkeypatch, rows, *, names=None, raises_for=()):
    from app.schemas import po as po_module

    monkeypatch.setattr(po_module, "SessionLocal", lambda: _NullSession())
    monkeypatch.setattr(
        po_module.po_repository,
        "get_purchase_orders_page",
        lambda session, **kwargs: (rows, {}, len(rows)),
    )
    lookups: list[str] = []

    def _resolve(user_id):
        lookups.append(user_id)
        if user_id in raises_for:
            raise RuntimeError("Clerk says no")
        return (names or {})[user_id]

    monkeypatch.setattr(po_module, "resolve_display_name", _resolve)
    return po_module.POQueries().purchase_orders_page(None), lookups


def test_a_nexus_request_shows_its_authors_display_name(monkeypatch):
    rows = [_StubRow(po_number="PO-1", created_by_user_id="u_1")]

    page, _ = _page(monkeypatch, rows, names={"u_1": "Bev Buyer"})

    assert page.rows[0].created_by == "Bev Buyer"
    assert page.total_count == 1


def test_a_mirrored_gp_row_falls_back_to_its_gp_buyer(monkeypatch):
    """A PO that came in off the GP mirror has no Nexus author, and the GP buyer id is the only
    answer the row actually holds."""
    rows = [_StubRow(po_number="PO-1", created_by_user_id=None, buyer_id="BUYER1")]

    page, lookups = _page(monkeypatch, rows)

    assert page.rows[0].created_by == "BUYER1"
    assert lookups == [], "a row with no Nexus author must not cost a Clerk lookup"


def test_a_row_with_neither_author_nor_buyer_reads_null(monkeypatch):
    rows = [_StubRow(po_number="PO-1", created_by_user_id=None, buyer_id="")]

    page, _ = _page(monkeypatch, rows)

    assert page.rows[0].created_by is None


def test_an_unresolvable_clerk_id_degrades_to_the_raw_id(monkeypatch):
    """A deleted Clerk account must not take the whole register page down with it."""
    rows = [_StubRow(po_number="PO-1", created_by_user_id="u_gone")]

    page, _ = _page(monkeypatch, rows, raises_for={"u_gone"})

    assert page.rows[0].created_by == "u_gone"


def test_authors_are_resolved_once_per_page_not_once_per_row(monkeypatch):
    """The N+1 this batching exists to avoid: three rows by one author is one Clerk lookup."""
    rows = [_StubRow(po_number=f"PO-{i}", created_by_user_id="u_1") for i in range(3)]
    rows.append(_StubRow(po_number="PO-4", created_by_user_id="u_2"))

    page, lookups = _page(monkeypatch, rows, names={"u_1": "Bev Buyer", "u_2": "Pat Purchasing"})

    assert sorted(lookups) == ["u_1", "u_2"]
    assert [r.created_by for r in page.rows] == ["Bev Buyer"] * 3 + ["Pat Purchasing"]
