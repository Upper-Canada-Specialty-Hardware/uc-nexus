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


def _user_summary(u: dict) -> dict:
    """The shape the users query / user mutations return, from a raw Clerk user payload."""
    metadata = u.get("public_metadata") or {}
    return {
        "id": u["id"],
        "first_name": u.get("first_name") or "",
        "last_name": u.get("last_name") or "",
        "email": _primary_email(u),
        "roles": metadata.get("roles", []),
        "gp_buyer_id": metadata.get("gpBuyerId") or None,
        "image_url": u.get("image_url") or "",
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
            users.append(_user_summary(u))

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


def _merge_public_metadata(user_id: str, patch: dict) -> dict:
    """Merge keys into a Clerk user's publicMetadata via the /metadata endpoint (deep merge), so
    writing one key (roles) never wipes another (gpBuyerId) - PATCH /users/{id} would replace the
    whole object. Returns the updated user summary."""
    resp = _client.patch(
        f"/users/{user_id}/metadata",
        headers=_headers(),
        json={"public_metadata": patch},
    )
    resp.raise_for_status()
    return _user_summary(resp.json())


def update_user_roles(user_id: str, roles: list[str]) -> dict:
    """Update a Clerk user's roles in publicMetadata."""
    return _merge_public_metadata(user_id, {"roles": roles})


def update_user_name(user_id: str, first_name: str, last_name: str) -> dict:
    """Issue #240: admin-driven display-name change. first_name/last_name are top-level Clerk user
    fields (not metadata), so this never touches roles/gpBuyerId. Everything that shows a display
    name (useIdentity fullName, resolve_display_name for received_by) derives from these."""
    resp = _client.patch(
        f"/users/{user_id}",
        headers=_headers(),
        json={"first_name": (first_name or "").strip(), "last_name": (last_name or "").strip()},
    )
    resp.raise_for_status()
    return _user_summary(resp.json())


def update_user_gp_buyer_id(user_id: str, gp_buyer_id: str | None) -> dict:
    """Issue #216: set (or clear, with None) the GP BUYERID this UC Nexus account acts as. The PO
    dialog auto-uses it and the create/register mutations enforce it server-side."""
    cleaned = (gp_buyer_id or "").strip() or None
    return _merge_public_metadata(user_id, {"gpBuyerId": cleaned})


def get_user_gp_buyer_id(user_id: str) -> str | None:
    """Issue #216: the caller's GP buyer identity from Clerk publicMetadata, or None if unset."""
    try:
        resp = _client.get(f"/users/{user_id}", headers=_headers())
        resp.raise_for_status()
        u = resp.json()
    except httpx.HTTPError as e:
        raise AppError(
            "Could not load your user profile from Clerk; please try again.", code="CLERK_UNAVAILABLE"
        ) from e
    metadata = u.get("public_metadata") or {}
    return metadata.get("gpBuyerId") or None
