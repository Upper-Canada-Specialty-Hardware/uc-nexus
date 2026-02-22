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

app = FastAPI(title="UC Covet - Hardware Management System")

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
