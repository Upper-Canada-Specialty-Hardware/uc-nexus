"""A first demo build that fails says so, and why (#1937).

`ensure_built` recorded the error and re-raised it as it came, so anything but an AppError reached the
person switching demo mode on as the masked server error. Nothing here touches a database or SharePoint:
the build's reads and its record are stubbed.
"""

import asyncio
from contextlib import nullcontext

import pytest

from app.errors import AppError, ConflictError
from app.services import demo_build


@pytest.fixture
def first_build(monkeypatch):
    """A first switch-on with no demo yet, whose legacy-list read raises `error`. Answers the records."""
    records: list[dict] = []

    def _make(error: Exception):
        async def _read_fails():
            raise error

        monkeypatch.setattr(demo_build.demo_reset, "has_demo_data", lambda: False)
        monkeypatch.setattr(demo_build, "building", lambda: False)
        monkeypatch.setattr(demo_build, "_record", lambda key, changes, replace=False: records.append(changes))
        monkeypatch.setattr(demo_build, "SessionLocal", nullcontext)
        monkeypatch.setattr(demo_build.state, "get", lambda session, key: None)
        monkeypatch.setattr(demo_build.demo_mirror, "refresh_legacy_list", _read_fails)
        return records

    return _make


def test_a_failed_first_build_is_named_with_its_reason(first_build):
    records = first_build(RuntimeError("Graph answered 503"))
    with pytest.raises(AppError) as e:
        asyncio.run(demo_build.ensure_built("Mira Lane"))
    assert e.value.code == "DEMO_BUILD_FAILED"
    assert e.value.message == "The demo couldn't be built: Graph answered 503"
    assert records[-1]["error"] == "Graph answered 503"
    assert records[-1]["running"] is False


def test_an_app_error_from_the_build_passes_through_as_it_is(first_build):
    first_build(ConflictError("The demo is being built already. Wait for it to finish."))
    with pytest.raises(ConflictError) as e:
        asyncio.run(demo_build.ensure_built("Mira Lane"))
    assert e.value.code == "CONFLICT"
