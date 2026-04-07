from collections.abc import Callable
from typing import Any

import strawberry
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from graphql import GraphQLError, GraphQLResolveInfo
from strawberry.extensions import SchemaExtension
from strawberry.fastapi import GraphQLRouter

from app.errors import AppError
from app.schemas.mutations import Mutation
from app.schemas.queries import Query


class ErrorHandlerExtension(SchemaExtension):
    def resolve(self, _next: Callable, root: Any, info: GraphQLResolveInfo, *args, **kwargs):
        try:
            result = _next(root, info, *args, **kwargs)
            return result
        except AppError as e:
            extensions = {"code": e.code}
            if e.field:
                extensions["field"] = e.field
            raise GraphQLError(message=e.message, extensions=extensions) from e
        except NotImplementedError as e:
            raise GraphQLError(
                message=str(e),
                extensions={"code": "NOT_IMPLEMENTED"},
            ) from e


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    extensions=[ErrorHandlerExtension],
)

graphql_app = GraphQLRouter(schema)

app = FastAPI(title="UC Nexus - Hardware Management System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/reset-data")
def reset_data():
    """Drop and rebuild the entire public schema via alembic. Dev use only."""
    from alembic.config import Config
    from sqlalchemy import text

    from alembic import command
    from app.database import engine

    # Drop and recreate schema
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()

    # Rebuild via alembic
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")

    return {"status": "ok", "message": "Schema dropped and rebuilt"}


@app.get("/testing/clerk-sign-in")
def get_clerk_sign_in_token(email: str = "jayp@ucsh.com"):
    """Create a Clerk sign-in token for E2E testing. Only available when TESTING_ENABLED=true."""
    import httpx
    from fastapi.responses import JSONResponse

    from app.config import CLERK_SECRET_KEY, TESTING_ENABLED

    if not TESTING_ENABLED:
        return JSONResponse(status_code=403, content={"error": "Testing is not enabled"})

    headers = {"Authorization": f"Bearer {CLERK_SECRET_KEY}"}

    # Find user by email
    users_resp = httpx.get(
        "https://api.clerk.com/v1/users",
        headers=headers,
        params={"email_address": email},
    )
    users_resp.raise_for_status()
    users = users_resp.json()
    if not users:
        return JSONResponse(status_code=404, content={"error": f"No user found with email {email}"})

    user_id = users[0]["id"]

    # Create sign-in token
    token_resp = httpx.post(
        "https://api.clerk.com/v1/sign_in_tokens",
        headers=headers,
        json={"user_id": user_id},
    )
    token_resp.raise_for_status()
    data = token_resp.json()
    return {"token": data["token"], "url": data.get("url", ""), "user_id": user_id}
