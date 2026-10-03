"""#1107 api hardening: masked server errors (#1114), the CORS origin list (#1115) and capped list limits
(#1134). The by-id tenancy reads (#1113) are covered in test_shop_assembly_batch_schema.py, beside the
fixtures they need."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from graphql import GraphQLError
from sqlalchemy.exc import IntegrityError

from app import config
from app.errors import ValidationError
from app.schemas import warehouse as warehouse_module
from app.schemas.limits import MAX_LIST_LIMIT, cap_limit, cap_offset
from main import ResolverGuardExtension, app

# --- masked errors (#1114) ---------------------------------------------------------------------


def _nested_info(field_name="someField"):
    """A non-root field, so the root-field policy gate stays out of the way."""
    return SimpleNamespace(field_name=field_name, path=SimpleNamespace(prev=object()), context={})


def _resolve(raising: BaseException):
    def _next(*_args, **_kwargs):
        raise raising

    return ResolverGuardExtension.resolve(ResolverGuardExtension(), _next, None, _nested_info())


def test_an_unexpected_error_is_masked_but_kept_for_the_log():
    leak = IntegrityError("INSERT INTO purchase_orders (secret) VALUES (%(s)s)", {"s": "x"}, Exception("dup"))

    with pytest.raises(GraphQLError) as exc:
        _resolve(leak)

    assert exc.value.extensions == {"code": "INTERNAL"}
    assert "INSERT" not in exc.value.message
    assert "purchase_orders" not in exc.value.message
    # The original rides along server-side only: Strawberry logs it with exc_info=original_error,
    # and graphql-core's formatted (wire) error carries no original_error.
    assert exc.value.original_error is leak
    assert set(exc.value.formatted) == {"message", "extensions"}


def test_a_malformed_id_is_a_validation_error_not_an_internal_one():
    with pytest.raises(GraphQLError) as exc:
        _resolve(ValueError("badly formed hexadecimal UUID string"))

    assert exc.value.extensions == {"code": "VALIDATION_ERROR"}
    assert "hexadecimal" not in exc.value.message
    assert exc.value.message == "someField: that id is not valid."


def test_other_value_errors_are_still_masked():
    with pytest.raises(GraphQLError) as exc:
        _resolve(ValueError("invalid literal for int() with base 10: 'abc'"))

    assert exc.value.extensions == {"code": "INTERNAL"}
    assert "literal" not in exc.value.message


def test_an_app_error_keeps_its_own_message_and_code():
    with pytest.raises(GraphQLError) as exc:
        _resolve(ValidationError("Quantity must be at least 1", field="quantity"))

    assert exc.value.message == "Quantity must be at least 1"
    assert exc.value.extensions == {"code": "VALIDATION_ERROR", "field": "quantity"}


def test_a_graphql_error_raised_on_purpose_passes_through():
    raised = GraphQLError("custom", extensions={"code": "CUSTOM"})

    with pytest.raises(GraphQLError) as exc:
        _resolve(raised)

    assert exc.value is raised


def test_an_async_resolver_is_masked_too():
    async def _boom():
        raise RuntimeError("connection to server at 10.0.0.1 failed")

    result = ResolverGuardExtension.resolve(ResolverGuardExtension(), lambda *a, **k: _boom(), None, _nested_info())

    with pytest.raises(GraphQLError) as exc:
        asyncio.run(result)

    assert exc.value.extensions == {"code": "INTERNAL"}
    assert "10.0.0.1" not in exc.value.message


# --- CORS (#1115) ------------------------------------------------------------------------------


def _preflight(origin: str):
    client = TestClient(app)
    return client.options(
        "/graphql",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,x-nexus-company",
        },
    )


def test_the_production_frontend_may_call_the_backend():
    origin = "https://frontend-production-34fc.up.railway.app"
    response = _preflight(origin)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_any_other_origin_is_refused():
    response = _preflight("https://evil.example.com")

    assert response.headers.get("access-control-allow-origin") is None


def test_the_origin_list_can_be_replaced_by_environment(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " https://nexus.example.com/ , http://localhost:5173 ")

    assert config.cors_allow_origins() == ["https://nexus.example.com", "http://localhost:5173"]


def test_an_empty_override_falls_back_to_the_defaults(monkeypatch):
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", " , ")

    assert config.cors_allow_origins() == list(config.DEFAULT_CORS_ALLOW_ORIGINS)


# --- list limits (#1134) -----------------------------------------------------------------------


def test_cap_limit_bounds_both_ends():
    assert cap_limit(10) == 10
    assert cap_limit(100_000) == MAX_LIST_LIMIT
    assert cap_limit(0) == 1
    assert cap_limit(-5) == 1
    assert cap_offset(-1) == 0
    assert cap_offset(30) == 30


def test_recent_receive_records_never_asks_for_more_than_the_cap(monkeypatch):
    seen = {}

    def _fake(session, limit, *, company=None):
        seen["limit"] = limit
        return []

    class _Session:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(warehouse_module.warehouse_repository, "get_recent_receive_records", _fake)
    monkeypatch.setattr(warehouse_module, "SessionLocal", _Session)
    monkeypatch.setattr(warehouse_module, "tenant_scope", lambda info: "TUBC")

    resolver = warehouse_module.WarehouseQueries.recent_receive_records
    assert resolver(None, SimpleNamespace(), limit=100_000) == []
    assert seen["limit"] == MAX_LIST_LIMIT
