"""#1924: no GraphiQL and no FastAPI docs on production; a test environment keeps both. Introspection stays
open everywhere. No database: nothing here reaches a resolver that reads one."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from strawberry.fastapi import GraphQLRouter

import app.config
import main

_HTML = {"accept": "text/html"}


def _app_as_built_for(monkeypatch, environment: str) -> TestClient:
    """The app as main.py builds it when RAILWAY_ENVIRONMENT_NAME is `environment`. Built fresh rather
    than by reimporting main, which would rebuild the relay gateway singleton under the rest of the suite."""
    monkeypatch.setattr(app.config, "RAILWAY_ENVIRONMENT_NAME", environment)
    built = FastAPI(**main._api_docs_urls())
    built.include_router(
        GraphQLRouter(main.schema, context_getter=main.get_context, graphql_ide=main._graphql_ide()), prefix="/graphql"
    )
    return TestClient(built)


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_serves_no_api_docs(monkeypatch, path):
    client = _app_as_built_for(monkeypatch, "production")

    assert client.get(path).status_code == 404


def test_production_serves_no_graphql_ide(monkeypatch):
    resp = _app_as_built_for(monkeypatch, "production").get("/graphql", headers=_HTML)

    assert "graphiql" not in resp.text.lower()


def test_production_still_answers_introspection(monkeypatch):
    resp = _app_as_built_for(monkeypatch, "production").post(
        "/graphql", json={"query": "{ __schema { queryType { name } } }"}
    )

    assert resp.status_code == 200
    assert resp.json()["data"]["__schema"]["queryType"]["name"] == "Query"


@pytest.mark.parametrize("environment", ["", "staging"])
def test_a_test_environment_keeps_the_ide_and_the_docs(monkeypatch, environment):
    client = _app_as_built_for(monkeypatch, environment)

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200
    assert "graphiql" in client.get("/graphql", headers=_HTML).text.lower()


def test_the_running_app_is_built_from_the_same_switches():
    """main.app itself, imported off Railway: the defaults, so the IDE and the docs are there."""
    client = TestClient(main.app)

    assert client.get("/docs").status_code == 200
    assert "graphiql" in client.get("/graphql", headers=_HTML).text.lower()
