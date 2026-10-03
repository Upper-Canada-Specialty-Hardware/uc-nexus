"""The returned-to-pending note dates a cancel by the Toronto calendar, not the stored UTC date (#1272).
Pure: both formatters take the cancel's fields directly, so no database is needed."""

from datetime import datetime

from app.repositories import request_return_notes, shop_assembly_repository

# 8:30pm EDT on Oct 3, stored as naive UTC.
EVENING_CANCEL = datetime(2026, 10, 4, 0, 30)


def test_shipping_note_dates_an_evening_cancel_on_the_day_it_happened():
    note = request_return_notes._format_note("SR-0001", "Jay", EVENING_CANCEL, None)
    assert "on 2026-10-03" in note


def test_shop_note_dates_an_evening_cancel_on_the_day_it_happened():
    note = shop_assembly_repository._format_return_note("SA-0001-B1", "Jay", EVENING_CANCEL, "door cut")
    assert "on 2026-10-03: door cut" in note


def test_a_daytime_cancel_keeps_its_date():
    note = request_return_notes._format_note("SR-0001", None, datetime(2026, 10, 3, 15, 0), None)
    assert note == "Returned to Pending: pull SR-0001 was cancelled by someone on 2026-10-03."
