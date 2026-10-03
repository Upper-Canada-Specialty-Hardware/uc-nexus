"""#1234 request-shape limits: depth, alias and token caps on the schema, checked at validation before any
resolver runs. No database needed: a refused document never reaches a resolver, and the passing cases only
check that no limit fired."""

import asyncio

from graphql import get_introspection_query

from main import MAX_QUERY_ALIASES, MAX_QUERY_DEPTH, MAX_QUERY_TOKENS, schema

LIMIT_MARKERS = ("exceeds maximum", "aliases found", "token")


def _errors(query: str) -> list[str]:
    result = asyncio.run(schema.execute(query, context_value={}))
    return [e.message for e in result.errors or []]


def _limit_errors(query: str) -> list[str]:
    return [m for m in _errors(query) if any(marker in m.lower() for marker in LIMIT_MARKERS)]


def test_too_many_aliases_are_refused():
    aliased = " ".join(f"a{i}: __typename" for i in range(MAX_QUERY_ALIASES + 1))
    errors = _errors(f"{{ {aliased} }}")
    assert errors
    assert any("aliases" in m.lower() for m in errors)


def test_aliases_up_to_the_limit_pass():
    aliased = " ".join(f"a{i}: __typename" for i in range(MAX_QUERY_ALIASES))
    assert _limit_errors(f"{{ {aliased} }}") == []


def test_too_deep_a_query_is_refused():
    # purchaseOrder -> lineItems -> ... nested past the limit; validation refuses on shape alone, so the
    # field names only need to parse, and the depth limiter runs before field validation.
    inner = "id"
    for _ in range(MAX_QUERY_DEPTH + 1):
        inner = f"lineItems {{ {inner} }}"
    errors = _errors(f"query Deep {{ purchaseOrders {{ {inner} }} }}")
    assert any("exceeds maximum operation depth" in m for m in errors)


def test_too_many_tokens_are_refused():
    fields = " ".join("__typename" for _ in range(MAX_QUERY_TOKENS))
    errors = _errors(f"{{ {fields} }}")
    assert any("token" in m.lower() for m in errors)


def test_the_standard_introspection_query_passes_every_limit():
    # Introspection is deliberately open; its nested ofType chain must not trip the depth limit.
    assert _limit_errors(get_introspection_query(descriptions=True)) == []


def test_a_query_at_the_depth_limit_passes_it():
    # The deepest app document measured at #1234 is depth 4 (approveReceiveDraft); the limit leaves room.
    inner = "id"
    for _ in range(MAX_QUERY_DEPTH - 1):
        inner = f"lineItems {{ {inner} }}"
    errors = _errors(f"query AtLimit {{ purchaseOrders {{ {inner} }} }}")
    assert not any("exceeds maximum operation depth" in m for m in errors)
