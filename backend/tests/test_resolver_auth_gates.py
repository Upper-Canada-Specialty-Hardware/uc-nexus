"""The schema extension refuses an unauthorized caller before the resolver runs (#345, #415, #423).

These were pin tests: one per resolver, each monkeypatching that resolver's gate with something that
raised a sentinel, proving the body asked before it acted. They had to be written one at a time
because the gate was a line inside each body, and a body that dropped its line failed here by name.

#423 moved the decision into `enforce_root_field` (app/auth_policy.py), called from
ResolverGuardExtension before `_next`. Ordering is structural now: there is no body-level line left
to drop, and no resolver-by-resolver list to keep in step with 161 of them. What is worth testing is
the mechanism, once - so these run real operations through the real schema and assert what a caller
gets back.

The sentinel idea survives, inverted. Instead of stubbing the gate and watching it fire, each test
stubs the thing the RESOLVER would touch first (`SessionLocal`, a repository call) so that if the
body ever starts, it says so loudly. A refusal that arrives with the sentinel un-fired is a refusal
that happened first.

`test_resolver_gate_completeness.py` is the complement: this file is behaviour, that one is coverage.
"""

import asyncio
import uuid

import pytest

from app import auth
from app.auth import ADMIN_ROLE, WAREHOUSE_MANAGER_ROLE
from app.auth_policy import OPEN_OPERATIONS, ROOT_FIELD_POLICY, SIGNED_IN, enforce_root_field
from app.errors import AppError
from app.repositories import user_repository
from app.schemas import relay as relay_module
from app.schemas import shipping as shipping_module
from app.schemas import shop_assembly as shop_assembly_module
from app.schemas import warehouse as warehouse_module
from main import schema


class _ResolverRan(Exception):
    """Raised by whatever the resolver body reaches for first. Seeing it means the gate let the call
    through; never seeing it, on a query that was refused, means the gate ran first."""


class _FakeRequest:
    def __init__(self, token: str | None = None):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}


def _execute(query: str, token: str | None = None, context: dict | None = None):
    """Run an operation through the real schema, with a request that carries the given bearer token.

    The context dict is the same one `get_context` builds per request, and the same one the gate
    memoises on - so passing one in lets a test watch what a single request costs."""
    ctx = context if context is not None else {"request": _FakeRequest(token)}
    return asyncio.run(schema.execute(query, context_value=ctx))


def _codes(result) -> set[str | None]:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


def _messages(result) -> set[str]:
    return {e.message for e in (result.errors or [])}


@pytest.fixture
def signed_in(monkeypatch):
    """A verifiable token for user `u_caller`, with no roles unless a test grants some.

    Patches `verify_clerk_token` rather than minting a real JWT: what is under test is the gate's
    decision, not RS256, and the alternative is a JWKS round trip in a unit test."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    return "tok"


def _explodes(monkeypatch, module, attr="SessionLocal"):
    """Make the resolver body's first move raise, so a body that runs cannot do so quietly."""

    def _boom(*args, **kwargs):
        raise _ResolverRan(f"{module.__name__}.{attr}")

    monkeypatch.setattr(module, attr, _boom)


def test_anonymous_caller_is_refused_before_the_resolver_body_runs(monkeypatch):
    """The #415 defect, restated as behaviour: no session, no work. `warehouses` is a plain
    signed-in read, so the only thing standing between an anonymous POST and the database is this."""
    _explodes(monkeypatch, warehouse_module)

    result = _execute("{ warehouses { id } }")

    assert _codes(result) == {"UNAUTHENTICATED"}
    assert not any("SessionLocal" in m for m in _messages(result)), (
        "the resolver body started before the caller was refused - the gate is no longer running first"
    )


def test_the_refusal_carries_the_code_the_frontend_recovers_on():
    """UNAUTHENTICATED is not decoration. The Apollo link re-mints the Clerk token and replays the
    operation once on exactly this code (#429); FORBIDDEN it leaves alone. The extension raises these
    inside the same try/except that maps AppError -> extensions.code, so the two cannot drift."""
    result = _execute("{ warehouses { id } }")

    assert _codes(result) == {"UNAUTHENTICATED"}
    assert _messages(result) == {"Authentication required"}


def test_an_open_operation_is_reachable_without_a_session(monkeypatch):
    """`enrollRelayInstall` is the whole allowlist. The relay calls it during setup, before it holds
    any credential, so there is no Clerk session to gate on - it is authenticated by the single-use
    enrollment token instead. Reaching the body is the assertion."""
    assert set(OPEN_OPERATIONS) == {"enrollRelayInstall"}, (
        "the open-operations allowlist changed; the new entry needs its own reachability test and a "
        "reason that survives review"
    )
    _explodes(monkeypatch, relay_module)

    result = _execute(
        'mutation { enrollRelayInstall(input: {enrollmentToken: "t", hostname: "h", secret: "s"}) { ok } }'
    )

    assert any("SessionLocal" in m for m in _messages(result)), (
        f"enrollRelayInstall did not reach its body: {_messages(result)}. The relay cannot enrol if "
        f"this is gated on a Clerk session it does not have."
    )


def test_an_admin_field_refuses_a_signed_in_non_admin(monkeypatch, signed_in):
    """`relayInstalls` lists relay credentials. A valid session is not enough for it, and the caller
    must not get as far as the query."""
    _explodes(monkeypatch, relay_module)

    result = _execute("{ relayInstalls { id } }", token=signed_in)

    assert _codes(result) == {"FORBIDDEN"}
    assert _messages(result) == {f"{ADMIN_ROLE} role required"}
    assert not any("SessionLocal" in m for m in _messages(result))


def test_an_admin_field_admits_an_admin(monkeypatch, signed_in):
    """The other half of the same check - a gate that refuses everyone is not a gate either."""
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [ADMIN_ROLE])
    _explodes(monkeypatch, relay_module)

    result = _execute("{ relayInstalls { id } }", token=signed_in)

    assert any("SessionLocal" in m for m in _messages(result)), (
        f"an Admin/Manager was refused relayInstalls: {_messages(result)}"
    )


@pytest.mark.parametrize("field", ["rejectReceiveDraft"])
def test_rejecting_a_receive_draft_takes_either_manager_role(field, monkeypatch, signed_in):
    """The any-of requirement, in all three directions.

    Two roles satisfy it, which is the reason ROOT_FIELD_POLICY entries may be a frozenset at all.
    There is no implicit admin bypass in this codebase, so Admin/Manager has to be named in the set
    to hold; a warehouse account that only counts trucks must not hold it either way.

    The shop-assembly manager's board names the other non-Admin role in the table since #646 (see
    test_shop_assembly_batch_schema.py); this is the warehouse half of the same shape.

    `approveReceiveDraft` is not pinned here. Its table entry is SIGNED_IN and the real role check is
    `_authorize_draft_approval` inside the resolver - a plain Admin/Manager gate, exercised in
    test_receive_drafts.py through the approve flow rather than against the policy table.
    """
    assert ROOT_FIELD_POLICY[field] == frozenset({ADMIN_ROLE, WAREHOUSE_MANAGER_ROLE})

    def _roles(roles):
        monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: roles)

    _roles(["Warehouse Staff"])
    with pytest.raises(AppError) as excinfo:
        enforce_root_field(field, {"request": _FakeRequest("tok")})
    assert excinfo.value.code == "FORBIDDEN"
    assert excinfo.value.message == f"{ADMIN_ROLE} or {WAREHOUSE_MANAGER_ROLE} role required"

    for role in (WAREHOUSE_MANAGER_ROLE, ADMIN_ROLE):
        _roles([role])
        enforce_root_field(field, {"request": _FakeRequest("tok")})


def test_a_root_field_with_no_policy_entry_is_refused():
    """Deny by default, which is the entire difference between #415's shape and this one. An operation
    nobody wrote a policy for fails closed - the alternative default is what let `updateUserRoles`
    ship reachable with no session at all."""
    with pytest.raises(AppError) as excinfo:
        enforce_root_field("someFieldNobodyGatedYet", {"request": _FakeRequest("tok")})

    assert excinfo.value.code == "FORBIDDEN"
    assert "someFieldNobodyGatedYet" in str(excinfo.value)


# --- per-field pins ------------------------------------------------------------------------------
#
# The #415 shape had one pin per resolver, each asserting that body called its gate. These are the
# replacement, and they are strictly stronger: they exercise the decision the caller actually gets
# rather than the presence of a line, and they still fail by field name, which is what made the old
# ones useful in review. Driven off ROOT_FIELD_POLICY so a field added to the table is covered the
# moment it is added, and one removed stops being asserted about - neither needs a list here.

_ROLE_GATED = sorted(f for f, requirement in ROOT_FIELD_POLICY.items() if requirement != SIGNED_IN)


def _acceptable_roles(field: str) -> list[str]:
    """Every role that satisfies a field, so the any-of entries are proved once per role rather than
    once per field. A bare string is a one-element list of itself."""
    requirement = ROOT_FIELD_POLICY[field]
    return sorted(requirement) if isinstance(requirement, frozenset) else [requirement]


def _expected_refusal(field: str) -> str:
    requirement = ROOT_FIELD_POLICY[field]
    if isinstance(requirement, frozenset):
        return f"{' or '.join(sorted(requirement))} role required"
    return f"{requirement} role required"


# One case per (field, acceptable role): an any-of requirement is only proved by showing EACH of its
# roles gets in. A frozenset where one name is a typo would otherwise pass on the other one.
_ROLE_GATED_CASES = [(field, role) for field in _ROLE_GATED for role in _acceptable_roles(field)]


@pytest.mark.parametrize("field", sorted(ROOT_FIELD_POLICY), ids=sorted(ROOT_FIELD_POLICY))
def test_every_gated_field_refuses_an_anonymous_caller(field):
    """No session, no field. This is the property #415 established and #423 had to preserve while
    moving where it is decided - a refactor that dropped a policy entry, or made SIGNED_IN mean
    "anyone", fails here on the field it broke."""
    with pytest.raises(AppError) as excinfo:
        enforce_root_field(field, {"request": _FakeRequest()})

    assert excinfo.value.code == "UNAUTHENTICATED", f"{field} let an anonymous caller through with {excinfo.value.code}"


@pytest.mark.parametrize("field", _ROLE_GATED, ids=_ROLE_GATED)
def test_every_role_gated_field_refuses_a_caller_without_the_role(field, monkeypatch):
    """A signed-in session is not a role. Everything in this list guards something a plain warehouse
    or assembly account has no business reaching - relay credentials, the Clerk roster, warehouse
    and vendor writes, the GP job and buyer writes, and `updateUserRoles`, which grants the role the
    rest of them are gated on."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: ["Warehouse Staff"])
    monkeypatch.setattr(user_repository, "list_users", lambda: [{"id": "u_caller", "roles": ["Warehouse Staff"]}])

    with pytest.raises(AppError) as excinfo:
        enforce_root_field(field, {"request": _FakeRequest("tok")})

    assert excinfo.value.code == "FORBIDDEN", f"{field} admitted a caller holding only Warehouse Staff"
    assert excinfo.value.message == _expected_refusal(field)


@pytest.mark.parametrize("field,role", _ROLE_GATED_CASES, ids=[f"{f}-{r}" for f, r in _ROLE_GATED_CASES])
def test_every_role_gated_field_admits_a_caller_holding_the_role(field, role, monkeypatch):
    """The other direction, per field and - for an any-of requirement - per role in it. A gate nobody
    can pass is the failure mode a deny-by-default refactor invites: a typo in a role name, or a
    policy entry pointing at a role Clerk never grants, locks the field for everyone and looks like
    working security until someone reports it."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [role])
    monkeypatch.setattr(user_repository, "list_users", lambda: [{"id": "u_caller", "roles": [role]}])

    enforce_root_field(field, {"request": _FakeRequest("tok")})


@pytest.mark.parametrize("field", sorted(OPEN_OPERATIONS), ids=sorted(OPEN_OPERATIONS))
def test_every_open_operation_is_reachable_without_a_session(field):
    """The allowlist has to actually allow. `enrollRelayInstall` is the relay's only way in during
    setup, before it holds any credential - gating it strands every new install."""
    enforce_root_field(field, {"request": _FakeRequest()})


def test_receiving_history_is_a_plain_signed_in_read(monkeypatch, signed_in):
    """#447's new root field, in both directions through the real schema.

    The parametrized pins above already prove it refuses an anonymous caller, because it is in
    ROOT_FIELD_POLICY - but they call `enforce_root_field` directly, so nothing there would notice a
    SIGNED_IN field that was gated so hard no warehouse account could reach it. The Receiving page is
    warehouse-facing and cross-project, so the requirement is identity and nothing more: every
    frontend caller is not in one role's module, which is the rule for choosing SIGNED_IN over a role
    name."""
    assert ROOT_FIELD_POLICY["receivingHistoryPos"] == SIGNED_IN
    _explodes(monkeypatch, warehouse_module)

    refused = _execute("{ receivingHistoryPos { id } }")
    admitted = _execute("{ receivingHistoryPos { id } }", token=signed_in)

    assert _codes(refused) == {"UNAUTHENTICATED"}
    assert not any("SessionLocal" in m for m in _messages(refused))
    assert any("SessionLocal" in m for m in _messages(admitted)), (
        f"a signed-in caller was refused receivingHistoryPos: {_messages(admitted)}"
    )


_SLIP_ID = uuid.uuid4()
_DELIVERY_REQUEST_MUTATIONS = {
    "updateShipmentDetails": f'updateShipmentDetails(input: {{id: "{_SLIP_ID}"}}) {{ id }}',
    "markShipmentPickedUp": f'markShipmentPickedUp(id: "{_SLIP_ID}") {{ id }}',
    "markShipmentDelivered": f'markShipmentDelivered(id: "{_SLIP_ID}") {{ id }}',
}


@pytest.mark.parametrize("field", sorted(_DELIVERY_REQUEST_MUTATIONS), ids=sorted(_DELIVERY_REQUEST_MUTATIONS))
def test_the_delivery_request_mutations_are_plain_signed_in_writes(field, monkeypatch, signed_in):
    """#447's three new mutations, in both directions through the real schema.

    The parametrized pins prove they refuse an anonymous caller because they are in
    ROOT_FIELD_POLICY - but they call `enforce_root_field` directly, so nothing there would catch a
    SIGNED_IN field gated so hard that no shipping account could reach it. The Shipments page is
    worked by the shipping department, the warehouse and the office alike, so no one role's module
    owns the callers and the requirement is identity only. The edit is refused on *state*, not on
    role: a shipment that has been picked up is closed to everybody."""
    assert ROOT_FIELD_POLICY[field] == SIGNED_IN
    # `current_user` is the first thing the picked-up/delivered bodies touch, and SessionLocal the
    # first thing the edit touches, so patch both - either one firing means the body started.
    _explodes(monkeypatch, shipping_module, "current_user")
    _explodes(monkeypatch, shipping_module, "SessionLocal")
    operation = f"mutation {{ {_DELIVERY_REQUEST_MUTATIONS[field]} }}"

    refused = _execute(operation)
    admitted = _execute(operation, token=signed_in)

    assert _codes(refused) == {"UNAUTHENTICATED"}
    assert not any("shipping" in m for m in _messages(refused))
    assert any("shipping" in m for m in _messages(admitted)), (
        f"a signed-in caller was refused {field}: {_messages(admitted)}"
    )


def test_nested_fields_are_not_re_checked(monkeypatch, signed_in):
    """Only root fields are gated (`info.path.prev is None`). A nested field is reachable only through
    a root field that already passed, and checking each one would put a Clerk decision on every node
    of every response - the reason the per-resolver shape was expensive in the first place."""
    verifications = []
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: (verifications.append(token), {"sub": "u_caller"})[1])
    _explodes(monkeypatch, warehouse_module)

    # `warehouses` selects several sub-fields; only the root one may be gated.
    _execute("{ warehouses { id name code isActive } }", token=signed_in)

    assert len(verifications) == 1


def test_the_jwt_is_verified_once_for_a_query_hitting_several_root_fields(monkeypatch, signed_in):
    """#415 verified per gate, so a page firing one query over five root fields paid five times. The
    identity is a property of the request, so it is resolved once and memoised on the request's own
    context."""
    verifications = []
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: (verifications.append(token), {"sub": "u_caller"})[1])
    _explodes(monkeypatch, warehouse_module)
    _explodes(monkeypatch, shop_assembly_module, "SessionLocal")

    # Three schema modules, and `stockItems` is deliberately NOT exploded: the memoisation this test
    # is named for is cross-module, so at least one field has to reach a real resolver. (It was
    # `vendors` until #509 removed it; a fourth warehouse field would have collapsed the test to two
    # modules, all of them patched.)
    _execute(
        "{ warehouses { id } pullRequests { id } stockItems { id } shopAssemblyRequests { id } }",
        token=signed_in,
    )

    assert len(verifications) == 1, f"the token was verified {len(verifications)} times for one request"


def test_the_role_lookup_is_not_repeated_across_root_fields(monkeypatch, signed_in):
    """Same argument, and the expensive half: roles live in Clerk publicMetadata rather than the
    session token, so each `require_admin` was its own Clerk Backend API round trip. The admin
    dashboard fires several admin queries; they now share one."""
    role_lookups = []
    monkeypatch.setattr(
        user_repository, "get_user_roles", lambda user_id: (role_lookups.append(user_id), [ADMIN_ROLE])[1]
    )
    _explodes(monkeypatch, relay_module)

    _execute("{ relayInstalls { id } relayAdoptWindow { label } }", token=signed_in)

    assert len(role_lookups) == 1, f"roles were fetched {len(role_lookups)} times for one request"


def test_two_requests_do_not_share_an_identity(monkeypatch):
    """The memo lives on the context dict `get_context` builds per request, so it cannot outlive one.
    A process-global cache would be the same optimisation and a much worse bug: one user's roles
    served to another."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": f"u_{token}"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [ADMIN_ROLE] if user_id == "u_a" else [])
    _explodes(monkeypatch, relay_module)

    admitted = _execute("{ relayInstalls { id } }", token="a")
    refused = _execute("{ relayInstalls { id } }", token="b")

    assert any("SessionLocal" in m for m in _messages(admitted))
    assert _codes(refused) == {"FORBIDDEN"}


def test_admin_stats_authorizes_and_answers_with_one_clerk_call(monkeypatch, signed_in):
    """The double round trip #423 called out. `adminStats` counts Clerk users, so it calls
    `list_users` - which returns roles per user, the caller's included - and then paid for a separate
    `get_user_roles` to authorize the very same caller. The gate now takes the roles out of that one
    roster call (ROSTER_BACKED in app/auth_policy.py)."""
    rosters = []
    role_lookups = []
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda: (rosters.append(1), [{"id": "u_caller", "roles": [ADMIN_ROLE]}])[1],
    )
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: (role_lookups.append(user_id), [])[1])
    from app.schemas import dashboard as dashboard_module

    _explodes(monkeypatch, dashboard_module)

    result = _execute("{ adminStats { userCount } }", token=signed_in)

    assert any("SessionLocal" in m for m in _messages(result)), (
        f"adminStats was refused for an Admin/Manager: {_messages(result)}"
    )
    assert len(rosters) == 1, f"the Clerk roster was fetched {len(rosters)} times"
    assert role_lookups == [], "adminStats still pays a separate per-user role lookup on top of the roster"


def test_the_roster_is_not_fetched_for_a_field_that_does_not_need_it(monkeypatch, signed_in):
    """The roster is the cheaper answer only where the body wanted it anyway. Every other admin field
    stays on the single-user lookup rather than pulling every Clerk account to authorize one."""
    rosters = []
    monkeypatch.setattr(user_repository, "list_users", lambda: (rosters.append(1), [])[1])
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [ADMIN_ROLE])
    _explodes(monkeypatch, relay_module)

    _execute("{ relayInstalls { id } }", token=signed_in)

    assert rosters == []


def test_a_signed_in_field_costs_no_role_lookup(monkeypatch, signed_in):
    """SIGNED_IN means identity only. Reading roles for it would put a Clerk round trip on every
    warehouse and assembly screen in the app to learn something the gate does not use."""
    assert ROOT_FIELD_POLICY["warehouses"] == SIGNED_IN
    role_lookups = []
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: (role_lookups.append(user_id), [])[1])
    _explodes(monkeypatch, warehouse_module)

    _execute("{ warehouses { id } }", token=signed_in)

    assert role_lookups == []


def test_the_user_management_page_reads_the_roster_it_was_authorized_from(monkeypatch, signed_in):
    """`users` is the other roster-backed field: an admin-only read whose answer IS the roster the
    gate checked the caller against."""
    caller = {
        "id": "u_caller",
        "first_name": "A",
        "last_name": "B",
        "email": "a@b.c",
        "roles": [ADMIN_ROLE],
        "gp_buyer_id": None,
        "image_url": "",
    }
    rosters = []
    monkeypatch.setattr(user_repository, "list_users", lambda: (rosters.append(1), [caller])[1])
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: pytest.fail("roster should answer this"))

    result = _execute("{ users { id email } }", token=signed_in)

    assert result.errors is None, f"users failed: {_messages(result)}"
    assert result.data == {"users": [{"id": "u_caller", "email": "a@b.c"}]}
    assert len(rosters) == 1
