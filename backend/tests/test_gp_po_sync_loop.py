"""Backfill loop control for the GP PO mirror (gp-owned-po mirror). Pure async - relay + persist are
stubbed, no DB - so these run everywhere.

Covers the anti-hot-spin contract: the cursor advances only over POs that persisted, a stall is a
distinct signal so run_forever waits instead of re-reading the same page, one pass is bounded by
max_pages, and run_once forwards the caller's cap (the admin mutation passes a small one)."""

import asyncio

from app.services import gp_po_sync


def _counts(*, stored_cursor, backfill_done, created=1):
    return {
        "created": created,
        "updated": 0,
        "skipped": 0,
        "stored_cursor": stored_cursor,
        "backfill_done": backfill_done,
    }


def test_backfill_stalls_when_cursor_does_not_advance(monkeypatch):
    calls = {"relay": 0}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: "C1")

    async def fake_relay_call(company, op, params):
        calls["relay"] += 1
        return {"pos": [{"po_number": "PO1"}], "next_cursor": "C1"}

    monkeypatch.setattr(gp_po_sync.relay_gateway, "relay_call", fake_relay_call)
    # Cursor did not move (stored_cursor None) -> the page could not advance.
    monkeypatch.setattr(
        gp_po_sync,
        "_persist_page",
        lambda company, pos, next_cursor, *, is_backfill: _counts(stored_cursor=None, backfill_done=False),
    )

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=50))

    assert result["stalled"] is True
    assert result["backfill_done"] is False
    assert calls["relay"] == 1  # stopped after one page rather than hot-spinning


def test_backfill_drains_until_a_short_page_marks_it_done(monkeypatch):
    pages = [
        {"pos": [{"po_number": "PO1"}], "next_cursor": "C1"},
        {"pos": [{"po_number": "PO2"}], "next_cursor": None},  # short page = history drained
    ]
    state = {"i": 0, "cursor": None}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: state["cursor"])

    async def fake_relay_call(company, op, params):
        return pages[state["i"]]

    monkeypatch.setattr(gp_po_sync.relay_gateway, "relay_call", fake_relay_call)

    def fake_persist(company, pos, next_cursor, *, is_backfill):
        state["i"] += 1
        if next_cursor is None:
            return _counts(stored_cursor=None, backfill_done=True)
        state["cursor"] = next_cursor
        return _counts(stored_cursor=next_cursor, backfill_done=False)

    monkeypatch.setattr(gp_po_sync, "_persist_page", fake_persist)

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=50))

    assert result["backfill_done"] is True
    assert result["stalled"] is False
    assert result["created"] == 2


def test_backfill_is_bounded_by_max_pages(monkeypatch):
    n = {"i": 0}
    monkeypatch.setattr(gp_po_sync, "_load_cursor", lambda c: f"C{n['i']}")

    async def fake_relay_call(company, op, params):
        return {"pos": [{"po_number": "PO"}], "next_cursor": "advance"}

    monkeypatch.setattr(gp_po_sync.relay_gateway, "relay_call", fake_relay_call)

    def fake_persist(company, pos, next_cursor, *, is_backfill):
        n["i"] += 1
        return _counts(stored_cursor=f"C{n['i']}", backfill_done=False)  # always advances, never finishes

    monkeypatch.setattr(gp_po_sync, "_persist_page", fake_persist)

    result = asyncio.run(gp_po_sync._run_backfill("TUBC", max_pages=3))

    assert result["backfill_done"] is False
    assert result["stalled"] is False
    assert n["i"] == 3  # exactly max_pages pages drained, not more


def test_run_once_forwards_the_backfill_cap(monkeypatch):
    monkeypatch.setattr(gp_po_sync.relay_gateway, "_companies", frozenset({"TUBC"}))
    monkeypatch.setattr(gp_po_sync, "_backfill_done", lambda c: False)
    captured = {}

    async def fake_run_backfill(company, *, max_pages):
        captured["max_pages"] = max_pages
        return {"mode": "backfill", "backfill_done": False, "stalled": False}

    monkeypatch.setattr(gp_po_sync, "_run_backfill", fake_run_backfill)

    asyncio.run(gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES))

    assert captured["max_pages"] == gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES
