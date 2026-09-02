"""Server-driven register paging/search (gp-owned-po mirror). DB-backed (db_session).

The escaping assertions are the ones that matter: a user typing % or _ into the register search must
search for the literal character, not fire a SQL LIKE wildcard that matches everything.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest

from app import auth
from app.auth import ADMIN_ROLE
from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import PurchaseOrder
from app.repositories import po_repository, user_repository
from main import schema


def _make_po(session, *, po_number, vendor="Acme"):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=po_number,
        request_number=None,
        status=POStatus.GP_REGISTERED,
        gp_company="TUBC",
        vendor_name_snapshot=vendor,
        company="TUBC",
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

    def __init__(self, *, po_number, created_by_user_id=None, buyer_id=None, company="TUBC", gp_company="TUBC"):
        from datetime import datetime

        from app.models.enums import POOrigin, POStatus

        self.id = uuid.uuid4()
        self.po_number = po_number
        self.request_number = None
        self.project_id = None
        self.status = POStatus.GP_REGISTERED
        self.origin = POOrigin.GP
        self.company = company
        self.gp_company = gp_company
        self.vendor_name_snapshot = "Acme"
        self.ordered_at = None
        self.expected_delivery_date = None
        self.created_at = datetime(2026, 1, 1)
        self.gp_synced_at = None
        self.created_by_user_id = created_by_user_id
        self.buyer_id = buyer_id


class _AdminInfo:
    """An ADMIN caller, seeded into the per-request role memo so `tenant_scope` (#637) answers None
    (unscoped) instead of trying to verify a JWT off a request that is not there."""

    context = {"request": None, "_auth_roles": [ADMIN_ROLE]}


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
    return po_module.POQueries().purchase_orders_page(_AdminInfo()), lookups


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


# --- #637: the tenant a PO belongs to ---------------------------------------------------------------
# `company` is stamped when the PO is raised; `gp_company` only when it is registered into GP. A DRAFT
# therefore has the first and not the second, which is the row the register used to print as "-": the
# column read gp_company, the one field a draft never has. Both reads have to publish `company`, so
# both are exercised through the built schema rather than through the converter.


def test_a_draft_register_row_carries_its_tenant_with_no_gp_company(monkeypatch):
    rows = [_StubRow(po_number=None, company="TUBC", gp_company=None)]

    page, _ = _page(monkeypatch, rows)

    assert page.rows[0].company == "TUBC"
    assert page.rows[0].gp_company is None


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context():
    """A signed-in, company-scoped caller with the auth memos already filled, so neither the gate nor
    `tenant_scope` (#637) reaches Clerk for a token this test never minted."""
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": "TUBC",
    }


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context()))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    """A signed-in caller whose PO resolvers run against the test's own session."""
    from app.schemas import po as po_module

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: "TUBC")

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    return db_session


def _make_draft(session, *, company="TUBC"):
    """A project and the DRAFT PO raised against it, both in the same company."""
    project = Project(
        id=uuid.uuid4(),
        company=company,
        project_id=f"PO-{uuid.uuid4().hex[:8]}",
        description=f"{company} job",
    )
    session.add(project)
    session.flush()
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=company,
        po_number=None,
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=POStatus.DRAFT,
        gp_company=None,
        vendor_name_snapshot="Acme",
    )
    session.add(po)
    session.flush()
    return project, po


def test_the_register_publishes_a_drafts_company(signed_in, db_session):
    project, po = _make_draft(db_session)

    result = _execute(
        """query($search: String!){
             purchaseOrdersPage(search: $search){ rows{ id company gpCompany } }
           }""",
        {"search": po.request_number},
    )

    assert result.errors is None, result.errors
    assert result.data["purchaseOrdersPage"]["rows"] == [
        {"id": str(po.id), "company": project.company, "gpCompany": None}
    ]


def test_the_detail_read_publishes_a_drafts_company(signed_in, db_session):
    project, po = _make_draft(db_session)

    result = _execute(
        "query($id: ID!){ purchaseOrder(id: $id){ company gpCompany } }",
        {"id": str(po.id)},
    )

    assert result.errors is None, result.errors
    assert result.data["purchaseOrder"] == {"company": project.company, "gpCompany": None}
