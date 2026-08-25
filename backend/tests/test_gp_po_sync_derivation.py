"""Pure status-derivation rules for the GP PO mirror (gp-owned-po mirror). No DB - derive_po_stage is
a pure function of source table + line quantities, so these run everywhere."""

from app.models.enums import POStatus
from app.repositories.gp_po_sync_repository import derive_po_stage


def _line(qty, received=0, cancelled=0):
    return {"qty": qty, "received": received, "qty_cancelled": cancelled}


def test_open_no_receipts_is_registered_baseline():
    assert derive_po_stage("work", [_line(5)]) == POStatus.GP_REGISTERED


def test_open_partial_receipt_is_partially_received():
    assert derive_po_stage("work", [_line(5, received=2)]) == POStatus.PARTIALLY_RECEIVED


def test_open_fully_received_is_closed():
    assert derive_po_stage("work", [_line(5, received=5)]) == POStatus.CLOSED


def test_open_over_received_is_closed():
    assert derive_po_stage("work", [_line(5, received=7)]) == POStatus.CLOSED


def test_open_fully_cancelled_no_receipts_is_cancelled():
    assert derive_po_stage("work", [_line(5, cancelled=5)]) == POStatus.CANCELLED


def test_open_partial_cancel_counts_net():
    # 5 ordered, 2 cancelled -> 3 receivable; 3 received -> fully received -> CLOSED.
    assert derive_po_stage("work", [_line(5, received=3, cancelled=2)]) == POStatus.CLOSED
    # 1 received against 3 receivable -> partial.
    assert derive_po_stage("work", [_line(5, received=1, cancelled=2)]) == POStatus.PARTIALLY_RECEIVED


def test_posted_history_is_closed():
    assert derive_po_stage("history", [_line(5, received=5)]) == POStatus.CLOSED


def test_posted_history_fully_cancelled_is_cancelled():
    assert derive_po_stage("history", [_line(5, cancelled=5)]) == POStatus.CANCELLED


def test_posted_history_cancelled_but_partly_received_is_closed():
    # Something landed before the PO was closed out, so it is not a pure cancellation.
    assert derive_po_stage("history", [_line(5, received=2, cancelled=3)]) == POStatus.CLOSED


def test_multiline_aggregate():
    lines = [_line(4, received=4), _line(6, received=1)]
    # 10 receivable, 5 received -> partial across the PO.
    assert derive_po_stage("work", lines) == POStatus.PARTIALLY_RECEIVED


def test_empty_lines_is_registered_not_cancelled():
    # A header with no lines yet must not read as a cancellation.
    assert derive_po_stage("work", []) == POStatus.GP_REGISTERED
