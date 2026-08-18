"""Every GraphQL root field has an authorization policy, and every plain route has a gate (#415, #423).

The property is the same one #415 established: no operation is reachable unauthenticated by accident.
What changed with #423 is where it is decided and therefore what this file has to check.

Under #415 auth was opt-in per resolver - `require_user(info)` as the first line of 161 bodies - so
"ungated" was the silent default and this test's job was to catch a body that forgot. It parsed the
source of every resolver and asserted the line was there. That worked, and it could only ever detect
an omission after somebody wrote it.

Since #423 the default is refusal. `enforce_root_field` (app/auth_policy.py) runs in the schema
extension before any resolver, and a field with no entry in ROOT_FIELD_POLICY and no place on the
OPEN_OPERATIONS allowlist is REFUSED. So a forgotten policy is no longer a hole - it is a broken
field. This test's job is now the other direction: prove the table still describes the whole schema,
so nobody discovers a missing entry from a production 403.

It asks the built Strawberry schema rather than the source, which is the authority on what a root
field is actually called - `open_p_os` is `openPOs` to a caller, and a table keyed on the wrong one
would fail closed on a field that looks covered.

`test_resolver_auth_gates.py` is the complement: this file is coverage, that one is behaviour - that
the extension actually refuses, first, and with the right code.
"""

import ast
from pathlib import Path

import pytest

from app.auth import ADMIN_ROLE, DB_ADMIN_ROLE, SHOP_ASSEMBLY_MANAGER_ROLE, WAREHOUSE_MANAGER_ROLE
from app.auth_policy import OPEN_OPERATIONS, ROOT_FIELD_POLICY, ROSTER_BACKED, SIGNED_IN
from main import schema

# The requirements a policy entry may name. A typo'd role - "Admin/Manger" - would otherwise be a
# field nobody can call, since the check is a membership test against what Clerk returns.
_VALID_REQUIREMENTS = {SIGNED_IN, ADMIN_ROLE, DB_ADMIN_ROLE, SHOP_ASSEMBLY_MANAGER_ROLE, WAREHOUSE_MANAGER_ROLE}
_VALID_ROLES = _VALID_REQUIREMENTS - {SIGNED_IN}

_graphql_schema = schema._schema
_ROOT_FIELDS = set(_graphql_schema.query_type.fields) | set(_graphql_schema.mutation_type.fields)


def test_the_schema_still_has_the_root_fields_this_file_is_policing():
    """Guard the guard. Every assertion below is a set comparison against the schema, so a schema that
    came back empty - a renamed private attribute, a composition that stopped picking up the domain
    query classes - would make all of them pass vacuously."""
    assert len(_ROOT_FIELDS) >= 155, (
        f"only {len(_ROOT_FIELDS)} root fields found on the schema; the introspection below likely "
        f"regressed rather than the schema shrinking by a hundred fields"
    )
    assert _graphql_schema.subscription_type is None, (
        "the schema grew a subscription type. Subscriptions do not go through the resolve hook the "
        "same way; decide how they are gated before adding one, and extend this file to cover them."
    )


def test_every_root_field_has_a_policy_or_is_explicitly_open():
    """The whole point of #423. A field in neither table is refused at runtime, so this failing means
    a real operation is broken, not merely unguarded - but it is the same omission either way."""
    uncovered = sorted(_ROOT_FIELDS - set(ROOT_FIELD_POLICY) - set(OPEN_OPERATIONS))
    assert not uncovered, (
        f"root fields with no authorization policy: {uncovered}. Add each to ROOT_FIELD_POLICY in "
        f"app/auth_policy.py with what it requires, or - if it is genuinely reachable without a Clerk "
        f"session - to OPEN_OPERATIONS with the reason. Until then the extension refuses them."
    )


def test_no_policy_entry_names_a_field_that_does_not_exist():
    """A stale entry is dead weight that reads like coverage. It also hides the reverse mistake: a
    renamed field leaves its old name behind in the table and the new one uncovered, and only the
    check above would notice."""
    stale = sorted((set(ROOT_FIELD_POLICY) | set(OPEN_OPERATIONS)) - _ROOT_FIELDS)
    assert not stale, (
        f"app/auth_policy.py names root fields the schema does not have: {stale}. Either they were "
        f"renamed (update the entry) or removed (delete it)."
    )


def test_no_field_is_both_gated_and_open():
    """OPEN_OPERATIONS is checked first, so an overlap would silently un-gate a field whose policy
    entry says otherwise - the most expensive kind of duplicate."""
    overlap = sorted(set(ROOT_FIELD_POLICY) & set(OPEN_OPERATIONS))
    assert not overlap, (
        f"{overlap} appear in both ROOT_FIELD_POLICY and OPEN_OPERATIONS. OPEN_OPERATIONS wins, so "
        f"the policy entry is doing nothing. Delete whichever one is wrong."
    )


@pytest.mark.parametrize("field", sorted(ROOT_FIELD_POLICY), ids=sorted(ROOT_FIELD_POLICY))
def test_policy_requirement_is_one_the_gate_understands(field):
    requirement = ROOT_FIELD_POLICY[field]
    if isinstance(requirement, frozenset):
        # An any-of requirement. Empty would refuse everyone, and SIGNED_IN inside a set is
        # meaningless - the gate reads it as a role name and nobody holds a role called "@signed-in".
        assert requirement, f"{field} requires an empty frozenset, which no caller can ever satisfy."
        unknown = sorted(requirement - _VALID_ROLES)
        assert not unknown, (
            f"{field} may be satisfied by {unknown}, which are not roles this codebase grants "
            f"({sorted(_VALID_ROLES)}). The gate tests membership against what Clerk returns, so a "
            f"requirement nobody can hold locks the field for everyone."
        )
        return

    assert requirement in _VALID_REQUIREMENTS, (
        f"{field} requires {requirement!r}, which is neither SIGNED_IN nor a role this codebase "
        f"grants ({sorted(_VALID_ROLES)}). The gate tests membership against "
        f"what Clerk returns, so a requirement nobody can hold locks the field for everyone."
    )


def test_every_open_operation_carries_its_reason():
    """OPEN_OPERATIONS maps a field to why it is safe without a Clerk session. An empty reason makes
    it an entry nobody has to defend, which is how the list stops meaning anything."""
    unexplained = sorted(f for f, reason in OPEN_OPERATIONS.items() if not (reason or "").strip())
    assert not unexplained, f"open operations with no stated reason: {unexplained}"


def test_roster_backed_fields_are_role_gated():
    """ROSTER_BACKED only picks which Clerk call answers a role requirement. A field that requires
    nothing but SIGNED_IN has no role to look up, so listing it there buys a roster fetch for
    nothing - and would suggest it is gated harder than it is."""
    wrong = sorted(f for f in ROSTER_BACKED if ROOT_FIELD_POLICY.get(f, SIGNED_IN) == SIGNED_IN)
    assert not wrong, (
        f"{wrong} are in ROSTER_BACKED but require no role. Remove them: the roster is fetched to "
        f"answer a role check, and these have none."
    )


# --- plain FastAPI routes in main.py (#422) -------------------------------------------------------
#
# Untouched by #423, and deliberately so. The schema extension only runs for GraphQL; a plain
# @app.get route like /testing/clerk-sign-in - which mints a real Clerk session for any staff email -
# has nothing in front of it, which is exactly how it sat with no auth at all until #422. Routes get
# the same treatment as root fields did: call a gate or appear below with a reason. There is no
# ordering check here, and that is deliberate - the gated routes check TESTING_ENABLED before auth so
# a production deployment refuses outright rather than leaking whether the credential would have been
# good enough.

_MAIN_PY = Path(__file__).resolve().parent.parent / "main.py"

# The only gate that fits a bare FastAPI Request. The GraphQL path's helpers unwrap a Strawberry Info
# or a Strawberry context and can never appear in a route.
_ROUTE_GATES = frozenset({"require_admin_request"})

# route function name -> why it is deliberately reachable without require_admin_request.
_ROUTE_EXEMPT: dict[str, str] = {
    "health": "public liveness probe returning a constant; deploy healthchecks call it anonymously",
    "relay_link": "authenticated by the enrolled relay's Bearer secret on the websocket handshake, not Clerk",
    "relay_channels": "same enrolled relay Bearer secret as relay_link, checked inline; a workstation has no session",
    "get_testing_session": (
        "gated inline on TESTING_ENABLED + is_preview_environment + a constant-time per-env key-hash "
        "compare; require_admin_request is the wrong gate for it by design (the whole point is a "
        "no-session preview sign-in), and the account it mints is refused on production"
    ),
}


def _route_functions(tree: ast.Module):
    """Yield every function decorated @app.<method>(...) - get/post/put/patch/delete/websocket."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "app"
                and target.attr in {"get", "post", "put", "patch", "delete", "websocket"}
            ):
                yield node
                break


def _calls_a_gate(fn, gates) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in gates:
                return True
    return False


_ROUTES = list(_route_functions(ast.parse(_MAIN_PY.read_text(encoding="utf-8"))))


def test_every_main_py_route_was_collected():
    """Guard the guard, same shape as the root-field count above: if the decorator predicate
    regressed, the parametrized test below would silently shrink instead of failing."""
    collected = {fn.name for fn in _ROUTES}
    expected = {"health", "relay_link", "reset_data", "get_clerk_sign_in_token"}
    missing = expected - collected
    assert not missing, f"known main.py routes were not collected; the AST walk likely regressed: {sorted(missing)}"


@pytest.mark.parametrize("fn", _ROUTES, ids=[fn.name for fn in _ROUTES])
def test_route_calls_an_auth_gate(fn):
    if fn.name in _ROUTE_EXEMPT:
        pytest.skip(f"deliberately ungated: {_ROUTE_EXEMPT[fn.name]}")

    assert _calls_a_gate(fn, _ROUTE_GATES), (
        f"main.py route {fn.name} (line {fn.lineno}) has no require_admin_request call. Nothing else "
        f"enforces auth on a plain FastAPI route - the GraphQL policy table does not cover them - so "
        f"add the gate (or an equivalent explicit credential check alongside it), or add it to "
        f"_ROUTE_EXEMPT in this file with a reason."
    )
