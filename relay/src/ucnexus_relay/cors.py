"""CORS — Layer 2 of auth. Only configured UC Nexus origins may call the relay."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings


def configure_cors(app: FastAPI) -> None:
    origins = get_settings().cors.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
