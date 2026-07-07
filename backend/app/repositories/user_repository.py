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
            email_objs = u.get("email_addresses") or []
            primary_email = ""
            for e in email_objs:
                if e.get("id") == u.get("primary_email_address_id"):
                    primary_email = e.get("email_address", "")
                    break

            users.append(
                {
                    "id": u["id"],
                    "first_name": u.get("first_name") or "",
                    "last_name": u.get("last_name") or "",
                    "email": primary_email,
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
    receive's acting user comes from the Clerk token, not a client-supplied string)."""
    resp = _client.get(f"/users/{user_id}", headers=_headers())
    resp.raise_for_status()
    u = resp.json()
    email_objs = u.get("email_addresses") or []
    primary_email = ""
    for e in email_objs:
        if e.get("id") == u.get("primary_email_address_id"):
            primary_email = e.get("email_address", "")
            break
    return {
        "first_name": u.get("first_name") or "",
        "last_name": u.get("last_name") or "",
        "email": primary_email,
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
    email_objs = u.get("email_addresses") or []
    primary_email = ""
    for e in email_objs:
        if e.get("id") == u.get("primary_email_address_id"):
            primary_email = e.get("email_address", "")
            break

    return {
        "id": u["id"],
        "first_name": u.get("first_name") or "",
        "last_name": u.get("last_name") or "",
        "email": primary_email,
        "roles": metadata.get("roles", []),
        "image_url": u.get("image_url") or "",
    }
