"""Every GraphQL resolver calls an auth gate, or is on the exemption list below (#415).

Auth here is opt-in per resolver: `get_context` only stashes the request, and there is no middleware
to catch a resolver that never asks. That makes "ungated" the silent default - the resolver works, it
just also works for anonymous callers. `test_resolver_auth_gates.py` pins the gates we knew about;
this test is the one that finds the ones nobody knew about.

That gap was not hypothetical. All four resolvers in `app/schemas/user.py` shipped ungated, including
`updateUserRoles`, which grants `Admin/Manager` - the role gating relay provisioning, relay deletion,
buyer assignments and the GP job/buyer writes. An unauthenticated POST returned the full Clerk roster
with emails, roles and GP buyer ids. It was found by accident while correcting an unrelated comment,
and the sweep that followed turned up 91 more.

This test parses the source rather than the schema, so it needs no database and no Strawberry
introspection: for every function under `app/schemas/` decorated `@strawberry.field` or
`@strawberry.mutation`, assert the body mentions one of the gates. It cannot prove the gate runs
*first* or that the right gate was chosen - that is what the pin tests are for - only that asking was
not forgotten entirely.

To deliberately leave a resolver open, add it to `_EXEMPT` with a reason. That makes an open resolver
a reviewed decision instead of an oversight, which is the whole point.
"""

import ast
from pathlib import Path

import pytest

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas"

_GATES = {"require_user", "require_admin", "require_role", "require_admin_request"}

# (module stem, resolver function name) -> why it is deliberately reachable without a gate.
# Anything added here needs a reason that survives review, not a note that gating was inconvenient.
_EXEMPT: dict[tuple[str, str], str] = {
    # The relay calls this during one-time setup, before it holds any credential, so there is no
    # Clerk session to gate on. It is not unauthenticated: `relay_repository.enroll_install` matches
    # the enrollment token by hash, rejects an expired one, and rejects a reused one via the
    # `enrolled_at` guard. The admin who minted the token is the authorization.
    ("relay", "enroll_relay_install"): "authenticated by the single-use enrollment token, not Clerk",
}


def _resolver_functions(tree: ast.Module):
    """Yield every function decorated @strawberry.field / @strawberry.mutation, at any nesting."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            # Bare `@strawberry.field` is an Attribute; `@strawberry.field(...)` is a Call.
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr in {"field", "mutation"}:
                yield node
                break


def _calls_a_gate(fn) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in _GATES:
                return True
    return False


def _all_resolvers():
    rows = []
    for path in sorted(_SCHEMAS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in _resolver_functions(tree):
            rows.append((path.stem, fn))
    return rows


_RESOLVERS = _all_resolvers()


def test_the_sweep_found_resolvers_at_all():
    """Guard the guard: an AST change that silently matches nothing would make this file pass by
    finding no resolvers to check."""
    assert len(_RESOLVERS) > 100


@pytest.mark.parametrize(
    "module, fn",
    _RESOLVERS,
    ids=[f"{module}.{fn.name}" for module, fn in _RESOLVERS],
)
def test_resolver_calls_an_auth_gate(module, fn):
    if (module, fn.name) in _EXEMPT:
        pytest.skip(f"deliberately ungated: {_EXEMPT[(module, fn.name)]}")

    assert _calls_a_gate(fn), (
        f"{module}.{fn.name} (line {fn.lineno}) is a GraphQL resolver with no "
        f"require_user/require_admin/require_role call. Nothing else enforces auth - add a gate, or "
        f"add it to _EXEMPT in this file with a reason."
    )
