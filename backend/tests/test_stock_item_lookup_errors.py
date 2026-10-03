"""stockItem reads null only when the row is not there for the caller (#1281).

A missing row, one outside the caller's company (the scope check raises NotFoundError for that, so the
row's existence is not revealed) and a malformed id read as null. Every other failure used to be
swallowed into null too; it now propagates, so a database error is not mistaken for an empty result.
No database is needed: the session, scope check and read are replaced.
"""

import uuid
from contextlib import nullcontext

import pytest

from app.errors import NotFoundError
from app.schemas import stock as stock_schema


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(stock_schema, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(stock_schema, "tenant_scope", lambda info: "TUBC")
    return lambda id: stock_schema.StockQueries().stock_item(info=None, id=id)


def test_an_out_of_scope_or_missing_row_reads_null(monkeypatch, resolver):
    def out_of_scope(session, stock_item_id, scope):
        raise NotFoundError(f"Stock item {stock_item_id} not found")

    monkeypatch.setattr(stock_schema.tenancy, "require_stock_item_in_scope", out_of_scope)

    assert resolver(str(uuid.uuid4())) is None


def test_a_malformed_id_reads_null(resolver):
    assert resolver("not-a-uuid") is None


def test_any_other_failure_propagates(monkeypatch, resolver):
    def broken(session, stock_item_id, scope):
        raise RuntimeError("database went away")

    monkeypatch.setattr(stock_schema.tenancy, "require_stock_item_in_scope", broken)

    with pytest.raises(RuntimeError):
        resolver(str(uuid.uuid4()))
