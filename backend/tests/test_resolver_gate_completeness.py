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

# `require_admin_request` is deliberately absent: it takes a FastAPI Request, not a Strawberry Info,
# so it is the gate for the plain HTTP routes in main.py and can never be a valid resolver gate.
# Accepting it here would green-light `require_admin_request(info)`, which type-checks to nothing and
# blows up at runtime on `info.headers`.
_GATES = {"require_user", "require_admin", "require_role"}

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


def _calls_a_gate(fn, gates=frozenset(_GATES)) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
            if name in gates:
                return True
    return False


def _leading_call_name(stmt) -> str | None:
    """The function called by a bare-expression or plain-assignment statement, if it is one.

    Assignment counts because several resolvers legitimately keep the result:
    ``auth = require_user(info)`` then read ``auth["user_id"]``.
    """
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        call = stmt.value
    elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
        call = stmt.value
    else:
        return None
    f = call.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def _gates_before_acting(fn) -> bool:
    """The gate must be the first thing the body does, after any docstring."""
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return bool(body) and _leading_call_name(body[0]) in _GATES


def _all_resolvers():
    # rglob, not glob: a resolver moved into a sub-package (app/schemas/gp/queries.py) must not fall
    # out of the sweep just by moving.
    rows = []
    for path in sorted(_SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in _resolver_functions(tree):
            rows.append((path.stem, fn))
    return rows


_RESOLVERS = _all_resolvers()

# Every file that *looks* like it defines resolvers, decided by plain text rather than by the AST
# walk this file is trying to police - so the two can disagree and be caught at it.
_MODULES_WITH_DECORATORS = {
    path.stem
    for path in _SCHEMAS_DIR.rglob("*.py")
    if "@strawberry.field" in (text := path.read_text(encoding="utf-8")) or "@strawberry.mutation" in text
}


def test_every_module_that_declares_resolvers_was_collected():
    """Guard the guard. A bare count threshold is too weak: if the decorator predicate regressed and
    warehouse.py's 46 resolvers stopped being collected, a `> 100` assertion would still pass with 115.
    Comparing against a text scan catches a whole module dropping out, which is the realistic failure.
    """
    collected = {module for module, _ in _RESOLVERS}
    missing = _MODULES_WITH_DECORATORS - collected
    assert not missing, f"modules declare resolver decorators but none were collected from them: {sorted(missing)}"
    assert len(_RESOLVERS) >= 155, f"only {len(_RESOLVERS)} resolvers collected; the AST walk likely regressed"


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


@pytest.mark.parametrize(
    "module, fn",
    _RESOLVERS,
    ids=[f"{module}.{fn.name}" for module, fn in _RESOLVERS],
)
def test_resolver_gates_before_it_acts(module, fn):
    """A gate that runs after the work has already happened is not a gate.

    The pin tests in `test_resolver_auth_gates.py` prove ordering by monkeypatching a sentinel, but
    only for the resolvers somebody listed. This covers every one of them, so a refactor that drops
    `require_user(info)` below the `with SessionLocal()` block - letting an anonymous caller's write
    land and only then rejecting them - fails here by name.
    """
    if (module, fn.name) in _EXEMPT:
        pytest.skip(f"deliberately ungated: {_EXEMPT[(module, fn.name)]}")

    assert _gates_before_acting(fn), (
        f"{module}.{fn.name} (line {fn.lineno}) calls a gate, but not as its first statement. "
        f"Move the gate above everything else in the body - work done before it runs is work done "
        f"for an unauthenticated caller."
    )


# --- plain FastAPI routes in main.py (#422) -------------------------------------------------------
#
# The sweep above walks app/schemas/ only, so /testing/clerk-sign-in - a plain @app.get route that
# mints a real Clerk session for any staff email - sat outside it with no auth at all. Routes get the
# same treatment as resolvers: call a gate or appear below with a reason. There is no ordering check
# here, and that is deliberate - the gated routes check TESTING_ENABLED before auth so a production
# deployment refuses outright rather than leaking whether the credential would have been good enough.

_MAIN_PY = Path(__file__).resolve().parent.parent / "main.py"

# The only gate that fits a bare FastAPI Request. require_user/require_admin/require_role unwrap a
# Strawberry Info and can never appear in a route, mirroring the exclusion note on _GATES above.
_ROUTE_GATES = frozenset({"require_admin_request"})

# route function name -> why it is deliberately reachable without require_admin_request.
_ROUTE_EXEMPT: dict[str, str] = {
    "health": "public liveness probe returning a constant; deploy healthchecks call it anonymously",
    "relay_link": "authenticated by the enrolled relay's Bearer secret on the websocket handshake, not Clerk",
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


_ROUTES = list(_route_functions(ast.parse(_MAIN_PY.read_text(encoding="utf-8"))))


def test_every_main_py_route_was_collected():
    """Guard the guard, same shape as the module-collection test above: if the decorator predicate
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
        f"enforces auth on a plain FastAPI route - add the gate (or an equivalent explicit credential "
        f"check alongside it), or add it to _ROUTE_EXEMPT in this file with a reason."
    )
