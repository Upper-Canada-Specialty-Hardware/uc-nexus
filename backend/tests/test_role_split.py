"""UC NEXUS ADMIN and TENANT OWNER are two different things, and the backend keeps them apart (#729).

"Admin/Manager" was one Clerk role that bundled an all-modules bypass with an exemption from the GP
COMPANY NEXUS TENANT line. Splitting it means a TENANT OWNER now holds real authority - user
management, projects, warehouses, every module - while still being a SCOPED caller. That pairing is
new, and it is where the mistakes would be: a field that was safe because only an unscoped role
could reach it, a grant path that was safe because only somebody who already had everything could
use it.

So this file is about the boundary rather than about any one field. Three shapes of assertion:

  - PINNED. `tenant_scope` answers None for the cross-tenant role and for nobody else.
  - REFUSED ACROSS THE LINE. A TENANT OWNER is turned away from the cross-tenant fields, from
    another company's account, and from granting the two roles above their own.
  - THE MODULE MANAGERS HOLD. PO MANAGER, SHIPPING MANAGER and the held-write sets admit the people
    the rulings name and nobody else.

Almost nothing here needs a database: every refusal under test happens before a resolver would open
one, and the admissions stub the first thing the body reaches for so that reaching it is the
assertion (the sentinel pattern from test_resolver_auth_gates.py). The two exceptions take
`db_session`, because what they are about is a WHERE clause - the held-write queue filtering by
company - and a stubbed repository would only be asserting about the stub.
"""

import asyncio
import uuid

import pytest

from app import auth
from app.auth import (
    DB_ADMIN_ROLE,
    NEXUS_ADMIN_ROLE,
    PO_MANAGER_ROLE,
    SHIPPING_MANAGER_ROLE,
    TENANT_OWNER_ROLE,
    ForbiddenError,
    tenant_scope,
)
from app.auth_policy import enforce_root_field
from app.errors import AppError
from app.repositories import gp_outbox_repository, user_repository
from app.schemas import dashboard as dashboard_module
from app.schemas import gp_outbox as gp_outbox_module
from app.schemas import relay as relay_module
from app.services import gp_po_sync
from main import schema

MY_COMPANY = "TUBC"
OTHER_COMPANY = "TFAKE"


class _ResolverRan(Exception):
    """Raised by the first thing a resolver body touches. Seeing it means the caller got through."""


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


class _NoSession:
    """Stands in for `SessionLocal()` so a body under test can run without a database."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _execute(query: str):
    return asyncio.run(schema.execute(query, context_value={"request": _FakeRequest()}))


def _codes(result) -> set:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


def _messages(result) -> set:
    return {e.message for e in (result.errors or [])}


def _caller(monkeypatch, roles, company=MY_COMPANY, *, companies_by_user=None):
    """Sign the request in as `u_caller` holding `roles`, in `company`.

    `companies_by_user` overrides the company lookup per Clerk id, which is what lets a test put the
    caller and the account they are editing in different companies."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: roles if user_id == "u_caller" else [])
    lookup = companies_by_user or {"u_caller": company}
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: lookup.get(user_id))


def _roster_entry(user_id, email, roles, company):
    return {
        "id": user_id,
        "first_name": "",
        "last_name": "",
        "email": email,
        "roles": roles,
        "gp_buyer_id": None,
        "company": company,
        "image_url": "",
    }


def _info(roles, company=None):
    class _Info:
        context = {"request": None, "_auth_roles": roles, "_auth_company": company}

    return _Info()


# --- pinned ------------------------------------------------------------------------------------


def test_a_tenant_owner_is_pinned_to_their_own_company():
    """The whole point of the split. A TENANT OWNER has everything INSIDE one GP company, so they
    are scoped exactly like a warehouse user - only the cross-tenant role answers None."""
    assert tenant_scope(_info([TENANT_OWNER_ROLE], company=MY_COMPANY)) == MY_COMPANY
    assert tenant_scope(_info([NEXUS_ADMIN_ROLE], company=MY_COMPANY)) is None


def test_a_tenant_owner_with_no_company_is_refused_like_any_other_scoped_user():
    """Holding the role does not grant an exemption from needing a company. Scoping them to nothing
    would render an empty application, which reads as "the data is gone" from the user's side."""
    with pytest.raises(ForbiddenError):
        tenant_scope(_info([TENANT_OWNER_ROLE], company=None))


# --- refused across the line ---------------------------------------------------------------------


@pytest.mark.parametrize("field", ["updateUserCompany", "relayInstalls", "gpSyncState"])
def test_the_cross_tenant_fields_refuse_a_tenant_owner(field, monkeypatch):
    """Which account is in which company, the relay credentials, and what the sync loops are doing
    across every company at once. None of the three is answerable inside one tenant, so none of them
    opens to the role that lives inside one."""
    _caller(monkeypatch, [TENANT_OWNER_ROLE])

    with pytest.raises(AppError) as excinfo:
        enforce_root_field(field, {"request": _FakeRequest()})

    assert excinfo.value.code == "FORBIDDEN"
    assert excinfo.value.message == f"{NEXUS_ADMIN_ROLE} role required"


def test_editing_an_account_in_another_company_reads_as_absent(monkeypatch):
    """NOT FOUND, not FORBIDDEN. A forbidden answer confirms the account exists, which would turn
    the mutation into an oracle over the whole Clerk roster - the same reasoning every by-id check
    in app/repositories/tenancy.py follows."""
    _caller(
        monkeypatch,
        [TENANT_OWNER_ROLE],
        companies_by_user={"u_caller": MY_COMPANY, "u_target": OTHER_COMPANY},
    )
    monkeypatch.setattr(
        user_repository,
        "update_user_name",
        lambda *a, **k: pytest.fail("the write reached Clerk despite the refusal"),
    )

    result = _execute('mutation { updateUserName(userId: "u_target", firstName: "A", lastName: "B") { id } }')

    assert _codes(result) == {"NOT_FOUND"}


@pytest.mark.parametrize("granted", [NEXUS_ADMIN_ROLE, DB_ADMIN_ROLE])
def test_a_tenant_owner_cannot_grant_a_role_above_their_own(granted, monkeypatch):
    """Without this the company boundary holds only until somebody notices it: one save granting
    themselves the cross-tenant role and the scope they are confined to stops applying."""
    _caller(
        monkeypatch,
        [TENANT_OWNER_ROLE],
        companies_by_user={"u_caller": MY_COMPANY, "u_target": MY_COMPANY},
    )
    monkeypatch.setattr(
        user_repository,
        "update_user_roles",
        lambda *a, **k: pytest.fail("the write reached Clerk despite the refusal"),
    )

    result = _execute(f'mutation {{ updateUserRoles(userId: "u_target", roles: ["{granted}"]) {{ id }} }}')

    assert _codes(result) == {"FORBIDDEN"}
    assert _messages(result) == {f"Only a {NEXUS_ADMIN_ROLE} may grant or remove {granted}"}


def test_a_tenant_owner_may_still_set_the_roles_below_their_own(monkeypatch):
    """The limit is the two roles above them, not the whole mutation - a TENANT OWNER runs their own
    company's people, including handing a peer the same authority."""
    _caller(
        monkeypatch,
        [TENANT_OWNER_ROLE],
        companies_by_user={"u_caller": MY_COMPANY, "u_target": MY_COMPANY},
    )
    written: dict = {}
    monkeypatch.setattr(
        user_repository,
        "update_user_roles",
        lambda user_id, roles: written.update(roles=roles) or _roster_entry(user_id, "", roles, MY_COMPANY),
    )

    result = _execute(
        f'mutation {{ updateUserRoles(userId: "u_target", roles: ["{TENANT_OWNER_ROLE}", "PO User"]) {{ id }} }}'
    )

    assert result.errors is None, f"a peer promotion was refused: {_messages(result)}"
    assert written["roles"] == [TENANT_OWNER_ROLE, "PO User"]


def test_the_roster_a_tenant_owner_reads_is_their_own_company(monkeypatch):
    """`users` is how the Edit User page is populated, so an unfiltered one would show a TENANT
    OWNER every account in the business - and name the companies they cannot otherwise see."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda: [
            _roster_entry("u_caller", "owner@ucsh.com", [TENANT_OWNER_ROLE], MY_COMPANY),
            _roster_entry("u_peer", "peer@ucsh.com", ["PO User"], MY_COMPANY),
            _roster_entry("u_elsewhere", "elsewhere@ucsh.com", ["PO User"], OTHER_COMPANY),
        ],
    )
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: pytest.fail("the roster should answer this"))

    result = _execute("{ users { id } }")

    assert result.errors is None, f"users failed: {_messages(result)}"
    assert result.data == {"users": [{"id": "u_caller"}, {"id": "u_peer"}]}


def test_the_tenant_owner_landing_counts_one_company(monkeypatch):
    """`adminStats` is the Tenant Owner landing's three figures. The user count is filtered in the
    resolver because the accounts live in Clerk, and both database counts are handed the company so
    the repository can filter them there."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda: [
            _roster_entry("u_caller", "owner@ucsh.com", [TENANT_OWNER_ROLE], MY_COMPANY),
            _roster_entry("u_peer", "peer@ucsh.com", ["PO User"], MY_COMPANY),
            _roster_entry("u_elsewhere", "elsewhere@ucsh.com", ["PO User"], OTHER_COMPANY),
        ],
    )
    monkeypatch.setattr(dashboard_module, "SessionLocal", _NoSession)
    seen: dict = {}

    def _stats(session, user_count, *, company=None):
        seen.update(user_count=user_count, company=company)
        return {"user_count": user_count, "hardware_item_count": 0, "opening_count": 0}

    monkeypatch.setattr(dashboard_module.dashboard_repository, "get_admin_stats", _stats)

    result = _execute("{ adminStats { userCount } }")

    assert result.errors is None, f"adminStats failed: {_messages(result)}"
    assert seen == {"user_count": 2, "company": MY_COMPANY}
    assert result.data == {"adminStats": {"userCount": 2}}


# --- the module managers hold ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "refused_role", "admitted_role"),
    [
        ("createShipmentMethod", "Shipping Out", SHIPPING_MANAGER_ROLE),
        ("updatePoDocumentSettings", "PO User", PO_MANAGER_ROLE),
    ],
)
def test_a_module_manager_field_admits_its_manager_and_nobody_below(field, refused_role, admitted_role, monkeypatch):
    """Doing the work and deciding how the module works are two different things: the shipment
    methods list is the shape every load is recorded against, and the document settings are what
    every PO the company sends out looks like."""
    _caller(monkeypatch, [refused_role])
    with pytest.raises(AppError) as excinfo:
        enforce_root_field(field, {"request": _FakeRequest()})
    assert excinfo.value.code == "FORBIDDEN"

    for role in (admitted_role, TENANT_OWNER_ROLE, NEXUS_ADMIN_ROLE):
        _caller(monkeypatch, [role])
        enforce_root_field(field, {"request": _FakeRequest()})


@pytest.mark.parametrize(
    ("roles", "expected_company", "expected_all"),
    [(["PO User"], MY_COMPANY, False), ([NEXUS_ADMIN_ROLE], None, True)],
)
def test_sync_from_gp_covers_the_callers_own_company(roles, expected_company, expected_all, monkeypatch):
    """Sync from GP opens to everyone who works the PO table (#744), so it can no longer set every
    company's mirror going: a scoped caller pulls their own and only the unscoped role pulls them
    all."""
    _caller(monkeypatch, roles)
    monkeypatch.setattr(
        type(relay_module.relay_gateway), "companies", property(lambda self: [MY_COMPANY, OTHER_COMPANY])
    )
    seen: dict = {}

    async def _run_once(*, backfill_max_pages=None, all_companies=False, only_company=None, **kwargs):
        seen.update(all_companies=all_companies, only_company=only_company)
        return {"mode": "queued", "created": 0, "updated": 0, "backfill_done": True}

    monkeypatch.setattr(gp_po_sync, "run_once", _run_once)

    result = _execute("mutation { syncGpPos { mode } }")

    assert result.errors is None, f"syncGpPos failed: {_messages(result)}"
    assert seen == {"all_companies": expected_all, "only_company": expected_company}


def _outbox_entry(relay_op, company=MY_COMPANY):
    class _Entry:
        pass

    entry = _Entry()
    entry.relay_op = relay_op
    entry.company = company
    return entry


def _stub_outbox(monkeypatch, relay_op, company=MY_COMPANY):
    """Serve one held write of the given kind, and make the retry itself announce that it ran."""
    monkeypatch.setattr(gp_outbox_module, "SessionLocal", _NoSession)
    monkeypatch.setattr(gp_outbox_repository, "get_entry", lambda session, entry_id: _outbox_entry(relay_op, company))

    def _retry(*a, **k):
        raise _ResolverRan("retry_entry")

    monkeypatch.setattr(gp_outbox_repository, "retry_entry", _retry)


_RETRY = 'mutation { retryGpOutboxEntry(id: "00000000-0000-0000-0000-000000000000") { id } }'


def test_a_po_user_may_retry_a_held_po_registration(monkeypatch):
    """A held PO REGISTRATION belongs to whoever raises POs, which is what the field-level admin
    gate used to stop: the person whose PO it is had to find an admin to press the button."""
    _caller(monkeypatch, ["PO User"])
    _stub_outbox(monkeypatch, "create_po")

    result = _execute(_RETRY)

    assert any("retry_entry" in m for m in _messages(result)), (
        f"a PO User was refused a held PO REGISTRATION: {_messages(result)}"
    )


def test_a_po_user_may_not_retry_a_held_receive(monkeypatch):
    """The other half of the same ruling. Writing a receipt into GP is the warehouse's decision, and
    retrying an ambiguous one can post it twice."""
    _caller(monkeypatch, ["PO User"])
    _stub_outbox(monkeypatch, "create_receipt")

    result = _execute(_RETRY)

    assert _codes(result) == {"FORBIDDEN"}
    assert not any("retry_entry" in m for m in _messages(result)), "the retry ran despite the refusal"


def test_a_held_write_of_another_company_reads_as_absent(monkeypatch):
    """The entry carries the company it is for, so the tenant line applies to the queue as well -
    and it answers NOT FOUND, with the same message an id that is not in the table gets. A
    forbidden answer would confirm the entry exists, which is all an enumerator needs."""
    _caller(monkeypatch, ["PO User"])
    _stub_outbox(monkeypatch, "create_po", company=OTHER_COMPANY)

    result = _execute(_RETRY)

    assert _codes(result) == {"NOT_FOUND"}
    assert _messages(result) == {"No retryable GP write queue entry with that id"}
    assert not any("retry_entry" in m for m in _messages(result)), "the retry ran despite the refusal"


def test_a_warehouse_manager_may_retry_a_held_receive(monkeypatch):
    _caller(monkeypatch, ["Warehouse Manager"])
    _stub_outbox(monkeypatch, "create_receipt")

    result = _execute(_RETRY)

    assert any("retry_entry" in m for m in _messages(result)), (
        f"a Warehouse Manager was refused a held GP RECEIVE ENTRY: {_messages(result)}"
    )


# --- the write queue is one company's ------------------------------------------------------------
#
# The two reads stay SIGNED_IN, because the PO and receiving lists join held writes onto their rows
# for everybody. What changed is WHICH rows they get: the queue row carries the GP company its
# write is for, so a scoped caller sees their own and an unscoped UC NEXUS ADMIN sees them all.


@pytest.mark.parametrize(
    ("roles", "expected_company"),
    [([TENANT_OWNER_ROLE], MY_COMPANY), (["PO User"], MY_COMPANY), ([NEXUS_ADMIN_ROLE], None)],
)
def test_the_queue_reads_are_handed_the_callers_company(roles, expected_company, monkeypatch):
    """The resolver's half: whichever way the field is called, the company it filters on is the
    caller's scope, and None - every company - only for the unscoped role."""
    monkeypatch.setattr(gp_outbox_module, "SessionLocal", _NoSession)
    seen: dict = {}

    def _list(session, **kwargs):
        seen["list"] = kwargs.get("company")
        return []

    def _summary(session, company=None):
        seen["summary"] = company
        return {"pending": 0, "in_flight": 0, "failed": 0, "oldest_pending_at": None, "last_drained_at": None}

    monkeypatch.setattr(gp_outbox_repository, "list_entries", _list)
    monkeypatch.setattr(gp_outbox_repository, "summary", _summary)

    info = _info(roles, company=MY_COMPANY)
    gp_outbox_module.GpOutboxQueries().gp_outbox(info)
    gp_outbox_module.GpOutboxQueries().gp_outbox_summary(info)

    assert seen == {"list": expected_company, "summary": expected_company}


def _queue_row(session, company, relay_op="create_po"):
    return gp_outbox_repository.enqueue(
        session,
        idempotency_key=f"{company}:{relay_op}:{uuid.uuid4()}",
        op="register_po_in_gp" if relay_op == "create_po" else "create_receive",
        relay_op=relay_op,
        company=company,
        payload={},
        persist_context={},
        entity_key=f"po:{uuid.uuid4()}",
        label="Held write",
    )


def test_the_queue_itself_filters_by_company(db_session):
    """The repository's half, against real rows in both companies: the list carries one company's
    held writes and not the other's, checked by identity so an empty result still fails."""
    mine = _queue_row(db_session, MY_COMPANY)
    theirs = _queue_row(db_session, OTHER_COMPANY)
    db_session.flush()

    scoped = {r.id for r in gp_outbox_repository.list_entries(db_session, company=MY_COMPANY)}
    unscoped = {r.id for r in gp_outbox_repository.list_entries(db_session)}

    assert mine.id in scoped
    assert theirs.id not in scoped
    assert {mine.id, theirs.id} <= unscoped


def test_the_queue_chip_counts_one_company(db_session):
    """The summary is what every open browser polls, so it has to answer the same question the list
    does - a chip counting another tenant's held writes sends somebody looking for work they cannot
    see.

    Counted as a delta rather than against an absolute, because the count is over whatever else the
    database happens to be holding and the point is what these three rows do to it."""

    def _pending(company=None):
        return gp_outbox_repository.summary(db_session, company=company)["pending"]

    before = (_pending(MY_COMPANY), _pending(OTHER_COMPANY), _pending())

    _queue_row(db_session, MY_COMPANY)
    _queue_row(db_session, OTHER_COMPANY)
    _queue_row(db_session, OTHER_COMPANY)
    db_session.flush()

    after = (_pending(MY_COMPANY), _pending(OTHER_COMPANY), _pending())

    assert [a - b for a, b in zip(after, before, strict=True)] == [1, 2, 3]
