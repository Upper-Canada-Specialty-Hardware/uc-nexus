"""#1921: a /graphql request body past the cap is refused with a 413 before Strawberry reads it.

No database: a refused body never reaches a resolver, and the passing case asks only `__typename`, which
the root-field gate leaves open."""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main
from app.repositories.po_repository import MAX_PO_DOCUMENT_BYTES
from app.repositories.shipment_photos import MAX_PHOTO_BYTES


@pytest.fixture
def small_cap(monkeypatch):
    monkeypatch.setattr(main, "MAX_GRAPHQL_BODY_BYTES", 1024)
    return TestClient(main.app)


def test_the_cap_holds_one_maximum_upload():
    # One maximum PO document as base64, plus room for the rest of the mutation's JSON.
    assert (MAX_PO_DOCUMENT_BYTES * 4) // 3 + 4 + 64 * 1024 < main.MAX_GRAPHQL_BODY_BYTES
    assert MAX_PHOTO_BYTES <= MAX_PO_DOCUMENT_BYTES


def test_a_body_within_the_cap_is_answered(small_cap):
    resp = small_cap.post("/graphql", json={"query": "{ __typename }"})

    assert resp.status_code == 200
    assert resp.json()["data"] == {"__typename": "Query"}


def test_a_declared_length_past_the_cap_is_refused(small_cap):
    resp = small_cap.post(
        "/graphql",
        content=b'{"query": "{ __typename }", "x": "' + b"a" * 2048 + b'"}',
        headers={"content-type": "application/json"},
    )

    assert resp.status_code == 413
    assert resp.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_a_streamed_body_past_the_cap_stops_being_read(monkeypatch):
    """No Content-Length: the body is counted as it arrives and refused once it passes the cap, without
    reading the rest and without the app ever seeing it."""
    monkeypatch.setattr(main, "MAX_GRAPHQL_BODY_BYTES", 1024)

    chunks = [{"type": "http.request", "body": b"a" * 600, "more_body": True} for _ in range(10)]
    read = []

    async def receive():
        read.append(1)
        return chunks[len(read) - 1]

    sent = []

    async def send(message):
        sent.append(message)

    async def app(_scope, _receive, _send):
        raise AssertionError("the app must not see a body past the cap")

    scope = {"type": "http", "method": "POST", "path": "/graphql", "headers": []}
    asyncio.run(main.GraphQLBodyCapMiddleware(app)(scope, receive, send))

    assert len(read) == 2
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_other_paths_are_not_capped(monkeypatch):
    """The cap is the GraphQL endpoint's; every other route keeps its own rules."""
    monkeypatch.setattr(main, "MAX_GRAPHQL_BODY_BYTES", 1)
    seen = []

    async def app(scope, _receive, _send):
        seen.append(scope["path"])

    scope = {"type": "http", "method": "POST", "path": "/webhooks/clerk/email", "headers": [(b"content-length", b"99")]}
    asyncio.run(main.GraphQLBodyCapMiddleware(app)(scope, None, None))

    assert seen == ["/webhooks/clerk/email"]
