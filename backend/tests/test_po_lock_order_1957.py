"""Lock order where the GP mirror meets Nexus's PO writes (#1957, #1958).

Registering a GP PO's lines decided the PO's status from an unlocked read, so ties could land on a PO
the mirror had just cancelled; and the mirror released ties holding the PO and its lines but never the
project a finalize locks. Both now take the PO row, then the project, then the lines.
"""

import ast
import inspect

from app.repositories import gp_po_sync_repository, po_repository


def _function(module, name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def test_registering_lines_locks_the_po_before_it_reads_its_status():
    fn = _function(po_repository, "nexus_register_po_lines")
    lock = min(
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_lock_po_row"
    )
    status_check = min(
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Attribute) and n.attr == "status" and isinstance(n.value, ast.Name) and n.value.id == "po"
    )
    assert lock < status_check


def test_the_mirror_locks_the_project_before_the_lines():
    source = inspect.getsource(gp_po_sync_repository._lock_po_for_mirror)
    assert source.index("Project.id == row.project_id") < source.index("POLineItem.po_id == po_id")
