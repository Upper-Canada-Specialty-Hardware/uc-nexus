"""Bearer-token auth. Layer 1 of the relay's two-layer model (Layer 2 is CORS)."""

import secrets

from fastapi import Header, HTTPException

from .config import get_settings
from .errors import error_body

# same opaque message for both the missing-header and wrong-token cases - don't leak which failed
_UNAUTH = error_body("unauthorized", "missing or invalid bearer token")


def verify_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().auth.shared_secret
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=_UNAUTH)
    token = authorization.removeprefix("Bearer ").strip()
    # constant-time compare to avoid leaking the secret via timing
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail=_UNAUTH)
