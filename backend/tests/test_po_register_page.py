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
