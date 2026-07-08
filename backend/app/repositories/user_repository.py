"""Repository for Clerk user management via Clerk Backend API."""

import httpx

from app.config import CLERK_SECRET_KEY
from app.errors import AppError

CLERK_API_BASE = "https://api.clerk.com/v1"

_client = httpx.Client(base_url=CLERK_API_BASE, timeout=30.0)


def _headers() -> dict[str, str]:
    if not CLERK_SECRET_KEY:
        raise AppError("CLERK_SECRET_KEY is not configured")
    return {
        "Authorization": f"Bearer {CLERK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _primary_email(u: dict) -> str:
    """The user's primary email address from a Clerk user payload, or '' if none matches."""
    primary_id = u.get("primary_email_address_id")
    for e in u.get("email_addresses") or []:
        if e.get("id") == primary_id:
            return e.get("email_address", "")
    return ""


def _display_email(u: dict) -> str:
    """The primary email, or - when Clerk marks no primary (which would otherwise leave received_by as
    the raw 'user_2abc...' id, issue #202 #4) - the first email on the account. '' only if there are none."""
    primary = _primary_email(u)
    if primary:
        return primary
    for e in u.get("email_addresses") or []:
        addr = e.get("email_address")
        if addr:
            return addr
    return ""


def list_users() -> list[dict]:
    """List all Clerk users with their roles from publicMetadata."""
    users = []
    offset = 0
    limit = 100

    while True:
        resp = _client.get(
            "/users",
            headers=_headers(),
            params={"limit": limit, "offset": offset, "order_by": "-created_at"},
        )
        resp.raise_for_status()
        data = resp.json()

        for u in data:
            metadata = u.get("public_metadata") or {}
            users.append(
                {
                    "id": u["id"],
                    "first_name": u.get("first_name") or "",
                    "last_name": u.get("last_name") or "",
                    "email": _primary_email(u),
                    "roles": metadata.get("roles", []),
                    "image_url": u.get("image_url") or "",
                }
            )

        if len(data) < limit:
            break
        offset += limit

    return users


def get_user(user_id: str) -> dict:
    """Fetch one Clerk user's name + email (issue #199: server-side received_by resolution, so a
    receive's acting user comes from the Clerk token, not a client-supplied string).

    Issue #202 #4: a Clerk 5xx / timeout used to surface as a raw httpx.HTTPStatusError - an opaque 500
    that coupled receiving to Clerk's availability. Map it to a clean AppError instead so the caller sees
    a retryable, coded error."""
    try:
        resp = _client.get(f"/users/{user_id}", headers=_headers())
        resp.raise_for_status()
        u = resp.json()
    except httpx.HTTPError as e:
        raise AppError(
            "Could not load your user profile from Clerk; please try again.", code="CLERK_UNAVAILABLE"
        ) from e
    return {
        "first_name": u.get("first_name") or "",
        "last_name": u.get("last_name") or "",
        "email": _display_email(u),
    }


def get_user_roles(user_id: str) -> list[str]:
    """Fetch a single Clerk user's roles from publicMetadata. Returns [] if none set."""
    resp = _client.get(f"/users/{user_id}", headers=_headers())
    resp.raise_for_status()
    u = resp.json()
    metadata = u.get("public_metadata") or {}
    return metadata.get("roles") or []


def update_user_roles(user_id: str, roles: list[str]) -> dict:
    """Update a Clerk user's roles in publicMetadata."""
    resp = _client.patch(
        f"/users/{user_id}",
        headers=_headers(),
        json={"public_metadata": {"roles": roles}},
    )
    resp.raise_for_status()
    u = resp.json()
    metadata = u.get("public_metadata") or {}
    return {
        "id": u["id"],
        "first_name": u.get("first_name") or "",
        "last_name": u.get("last_name") or "",
        "email": _primary_email(u),
        "roles": metadata.get("roles", []),
        "image_url": u.get("image_url") or "",
    }
