"""Clerk authentication for GraphQL resolvers.

The backend has no global auth middleware; verification is opt-in per resolver via
``require_admin(info)``. The Strawberry ``get_context`` getter only stashes the request,
so ungated queries pay no JWT/JWKS/Clerk-API cost. Roles live in Clerk publicMetadata
(not in the default session token), so we verify the token for identity (``sub``) and
then look up roles through the Clerk Backend API.
"""

import time
from typing import Any

import httpx
import jwt
from fastapi import Request
from jwt import PyJWKSet

from app.config import CLERK_SECRET_KEY
from app.errors import AppError
from app.repositories import user_repository

ADMIN_ROLE = "Admin/Manager"
SHOP_ASSEMBLY_MANAGER_ROLE = "Shop Assembly Manager"

_CLERK_JWKS_URL = "https://api.clerk.com/v1/jwks"
_JWKS_TTL_SECONDS = 3600.0
_jwks_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}


class AuthError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, "UNAUTHENTICATED")


class ForbiddenError(AppError):
    def __init__(self, message: str = "You do not have permission to perform this action"):
        super().__init__(message, "FORBIDDEN")


def _load_jwks(force: bool = False) -> dict:
    now = time.monotonic()
    cached = _jwks_cache["data"]
    if not force and cached is not None and (now - _jwks_cache["fetched_at"]) < _JWKS_TTL_SECONDS:
        return cached
    if not CLERK_SECRET_KEY:
        raise AuthError("CLERK_SECRET_KEY is not configured")
    resp = httpx.get(
        _CLERK_JWKS_URL,
        headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    _jwks_cache["data"] = data
    _jwks_cache["fetched_at"] = now
    return data


def _signing_key(kid: str):
    for force in (False, True):
        # Refetch once on a kid miss to tolerate key rotation.
        key_set = PyJWKSet.from_dict(_load_jwks(force=force))
        for k in key_set.keys:
            if k.key_id == kid:
                return k.key
    raise AuthError("Token signing key not found")


def verify_clerk_token(token: str) -> dict:
    """Verify a Clerk session JWT (RS256) and return its claims. Raises AuthError on failure."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise AuthError("Malformed authentication token") from e

    kid = header.get("kid")
    if not kid:
        raise AuthError("Authentication token missing key id")

    try:
        return jwt.decode(
            token,
            _signing_key(kid),
            algorithms=["RS256"],
            options={"verify_aud": False},
            leeway=10,
        )
    except jwt.PyJWTError as e:
        raise AuthError("Invalid or expired authentication token") from e


async def get_context(request: Request) -> dict:
    """Strawberry context_getter: stash the request so resolvers can verify on demand.

    The request must be type-annotated; strawberry wraps this as a FastAPI dependency, so an
    unannotated parameter would be treated as a query parameter and break every request.
    """
    return {"request": request}


def _bearer_token(request) -> str | None:
    header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def require_user(info) -> dict:
    """Enforce that the caller is an authenticated UC Nexus user (any role). Returns {user_id}.
    No Clerk Backend API role lookup, so it's cheaper than require_admin."""
    request = info.context["request"]
    token = _bearer_token(request)
    if not token:
        raise AuthError("Authentication required")

    claims = verify_clerk_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise AuthError("Authentication token has no subject")
    return {"user_id": user_id}


def resolve_display_name(user_id: str) -> str:
    """Full name (falling back to email, then the Clerk user id) for the acting user - issue #199's
    server-side received_by, so a receive records the Clerk-authenticated caller, not the relay's
    Windows account. Mirrors the frontend's useIdentity() fullName-or-email convention."""
    profile = user_repository.get_user(user_id)
    full_name = f"{profile['first_name']} {profile['last_name']}".strip()
    return full_name or profile["email"] or user_id


def require_admin(info) -> dict:
    """Enforce that the caller holds the Admin/Manager role. Returns {user_id, roles}."""
    request = info.context["request"]
    token = _bearer_token(request)
    if not token:
        raise AuthError("Authentication required")

    claims = verify_clerk_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise AuthError("Authentication token has no subject")

    roles = user_repository.get_user_roles(user_id)
    if ADMIN_ROLE not in roles:
        raise ForbiddenError("Admin/Manager role required")
    return {"user_id": user_id, "roles": roles}


def require_role(info, role: str) -> dict:
    """Enforce that the caller holds a specific role (looked up via the Clerk Backend API, like
    require_admin). Returns {user_id, roles}. Use for role-gated resolvers other than Admin/Manager,
    e.g. the shop-assembly manager assignment tools (#330)."""
    request = info.context["request"]
    token = _bearer_token(request)
    if not token:
        raise AuthError("Authentication required")

    claims = verify_clerk_token(token)
    user_id = claims.get("sub")
    if not user_id:
        raise AuthError("Authentication token has no subject")

    roles = user_repository.get_user_roles(user_id)
    if role not in roles:
        raise ForbiddenError(f"{role} role required")
    return {"user_id": user_id, "roles": roles}
