"""A cancelled pull's restock locks in a pick's order (#1904).

A pick and the availability gate lock every row of every combo in play, in id order, before the rows
they name. The cancel took the picked rows first and the combos after, the opposite order, so a cancel
and a pick on one combo could deadlock.
"""

import ast
import inspect

from app.repositories.warehouse import pull_requests


def _first_call_line(fn: ast.FunctionDef, name: str) -> int:
    lines = [
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]
    assert lines, f"{name} is not called"
    return min(lines)


def test_the_combos_are_locked_before_the_picked_rows():
    tree = ast.parse(inspect.getsource(pull_requests))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_restock_cancelled_pull")

    assert _first_call_line(fn, "_lock_combos") < _first_call_line(fn, "lock_rows")
