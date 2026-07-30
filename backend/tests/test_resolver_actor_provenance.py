"""The actor on an audit or history row comes from the authenticated caller, never from input (#427).

Sibling of `test_resolver_gate_completeness.py`, and the same shape: an AST sweep over every
`@strawberry.field` / `@strawberry.mutation` under `app/schemas/`, no database, no Strawberry
introspection. That file asks whether a resolver checked *who* the caller is. This one asks whether
it then *believed* them about it.

The bug it pins: every mutation that stamps a name on a row took that name from its own arguments.
`completePullRequest(id, completedBy: "Someone Else")` wrote that string onto every opening the pull
staged, and the staging panel showed it. The same shape covered `performedBy` on inventory
corrections, `pickedBy` on the pick, `shippedBy` on a packing slip, `acceptedBy` on an approval - the
whole audit trail was a field the client filled in. `resolve_display_name` had existed since #199 for
exactly this, but only `createReceive` used it.

The check is deliberately mechanical rather than clever, so a reviewer can predict it:

  A. No resolver body may read an actor-named attribute off `input`, or read back an actor-named
     argument of its own. Those are the two ways a client value reaches a repository call.
  B. No actor-named keyword argument may be a string literal. That is the other historical wrong
     answer - `performed_by="Admin/Manager"` hardcoded on inventory adjustments and location moves,
     which made every one of those rows claim an admin did it.

What is left once both hold is a name derived from the Clerk token (`resolve_display_name`, or the
gate's own `user_id`) or read back off a row the server already wrote - which is the point.

Known limits, stated so nobody mistakes this for more than it is:

  - It reads syntax, not data flow. `actor = request.headers["X-Who"]` followed by
    `performed_by=actor` passes. It catches the shape the codebase actually had, not every
    conceivable one.
  - An actor passed POSITIONALLY (`repository.confirm_pick(session, pr_id, lines, actor)`) is invisible
    to rule B, because there is no argument name to match. Rule A still covers it: the dangerous value
    has to come from `input.x` or a parameter to get there, and both are refused.
  - It says nothing about resolvers that should stamp an actor and do not.

`assignedTo` / `assignedToUserId` on `assignOpenings` are deliberately absent from ACTOR_NAMES. They
name the person work is being given TO, not the person doing the giving, and a manager assigning to
someone else is the whole feature - that value MUST come from the client. The gate for it is
`require_role`, not this test.
"""

import ast
from pathlib import Path

import pytest

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas"

# Field names that mean "the person who did this", across the audit log, the pull/request lifecycle
# stamps and the shipping documents. Kept as a flat vocabulary rather than per-module lists so a new
# mutation inherits the rule by naming its column the way every other one does.
ACTOR_NAMES = {
    "accepted_by",
    "approved_by",
    "armed_by",
    "cancelled_by",
    "completed_by",
    "created_by",
    "entered_by",
    "fetched_by",
    "performed_by",
    "picked_by",
    "received_by",
    "rejected_by",
    "requested_by",
    "returned_by",
    "reviewed_by",
    "shipped_by",
    "staged_by",
    "started_by",
}

# The Strawberry convention in this codebase: the client's payload arrives as a parameter called
# `input`. Reading an actor off it is the exact defect #427 fixed.
_CLIENT_INPUT = "input"


def _resolver_functions(tree: ast.Module):
    """Yield every function decorated @strawberry.field / @strawberry.mutation, at any nesting.

    Same predicate as test_resolver_gate_completeness, deliberately duplicated rather than shared:
    two independent copies of the walk cannot both silently stop collecting a module.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr in {"field", "mutation"}:
                yield node
                break


def _all_resolvers():
    rows = []
    for path in sorted(_SCHEMAS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in _resolver_functions(tree):
            rows.append((path.stem, fn))
    return rows


_RESOLVERS = _all_resolvers()


def _parameter_names(fn) -> set[str]:
    a = fn.args
    names = {arg.arg for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


def _client_supplied_actor_reads(fn) -> list[str]:
    """Every place the body takes an actor from something the caller controls.

    Two forms, which is all there are: off the input object (`input.performed_by`) or off the
    resolver's own argument list (`completed_by`). A local assigned from `resolve_display_name` is
    neither, which is why the fix reads as a two-line preamble in every resolver.
    """
    params = _parameter_names(fn)
    hits = []
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.ctx, ast.Load)
            and node.attr in ACTOR_NAMES
            and isinstance(node.value, ast.Name)
            and node.value.id == _CLIENT_INPUT
        ):
            hits.append(f"{_CLIENT_INPUT}.{node.attr} (line {node.lineno})")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in ACTOR_NAMES:
            if node.id in params:
                hits.append(f"argument {node.id} (line {node.lineno})")
    return hits


def _hardcoded_actor_keywords(fn) -> list[str]:
    """Actor keyword arguments whose value is a bare string, e.g. performed_by="Admin/Manager"."""
    hits = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg in ACTOR_NAMES and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                hits.append(f"{kw.arg}={kw.value.value!r} (line {kw.value.lineno})")
    return hits


def test_the_actor_vocabulary_is_actually_present_in_the_schemas():
    """Guard the guard. If the field names were renamed wholesale, both checks below would pass
    vacuously on a codebase full of client-supplied actors under new names. Assert the vocabulary
    still matches reality by requiring a decent share of it to appear somewhere in app/schemas/."""
    text = "\n".join(p.read_text(encoding="utf-8") for p in _SCHEMAS_DIR.rglob("*.py"))
    present = {name for name in ACTOR_NAMES if name in text}
    assert len(present) >= 10, (
        f"only {sorted(present)} of the actor vocabulary appears in app/schemas/ - either the fields "
        f"were renamed (update ACTOR_NAMES) or this test is no longer checking anything."
    )


@pytest.mark.parametrize(
    "module, fn",
    _RESOLVERS,
    ids=[f"{module}.{fn.name}" for module, fn in _RESOLVERS],
)
def test_resolver_does_not_take_its_actor_from_the_client(module, fn):
    hits = _client_supplied_actor_reads(fn)
    assert not hits, (
        f"{module}.{fn.name} (line {fn.lineno}) reads the acting user from client input: "
        f"{', '.join(hits)}. Whoever is signed in could then file the action under someone else's "
        f"name. Take it from the gate instead:\n"
        f"    auth = require_user(info)\n"
        f"    actor = resolve_display_name(auth['user_id'])\n"
        f"Do not add the argument back to the GraphQL schema either. #427 left the old ones in as "
        f"ignored @deprecated no-ops purely so a tab from the previous deploy still validated, and "
        f"#438 removed them once that window closed - a new one has no such window to earn."
    )


@pytest.mark.parametrize(
    "module, fn",
    _RESOLVERS,
    ids=[f"{module}.{fn.name}" for module, fn in _RESOLVERS],
)
def test_resolver_does_not_hardcode_its_actor(module, fn):
    hits = _hardcoded_actor_keywords(fn)
    assert not hits, (
        f"{module}.{fn.name} (line {fn.lineno}) writes a constant as the acting user: "
        f"{', '.join(hits)}. A row that says 'Admin/Manager' for every caller records nothing - it "
        f"is the same defect as trusting the client, with the wrong answer baked in instead. Resolve "
        f"the caller with resolve_display_name(auth['user_id'])."
    )
