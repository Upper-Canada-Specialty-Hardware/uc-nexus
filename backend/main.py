import uuid
from typing import Any, Callable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.database import SessionLocal
from app.models.shipping import PackingSlip
from app.services import file_storage_service
import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.extensions import SchemaExtension
from graphql import GraphQLError, GraphQLResolveInfo

from app.schemas.queries import Query
from app.schemas.mutations import Mutation
from app.errors import AppError


class ErrorHandlerExtension(SchemaExtension):
    def resolve(
        self, _next: Callable, root: Any, info: GraphQLResolveInfo, *args, **kwargs
    ):
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


@app.get("/packing-slips/{packing_slip_id}/pdf")
def download_packing_slip_pdf(packing_slip_id: str):
    """Generate a signed S3 URL for a packing slip PDF and redirect to it."""
    with SessionLocal() as session:
        ps = session.get(PackingSlip, uuid.UUID(packing_slip_id))
        if ps is None or not ps.pdf_file_path:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Packing slip not found")
        signed_url = file_storage_service.generate_signed_url(ps.pdf_file_path)
        return RedirectResponse(url=signed_url)
