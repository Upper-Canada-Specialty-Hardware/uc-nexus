"""Repository for Clerk user management via Clerk Backend API."""

import httpx

from app.config import CLERK_SECRET_KEY
from app.errors import AppError, ValidationError

CLERK_API_BASE = "https://api.clerk.com/v1"

# Roles that make a user a shop-assembly team member (#330): assignable work in the shop-assembly
# module. A manager can assign to a plain user or to another manager.
SHOP_ASSEMBLY_ROLES = ("Shop Assembly User", "Shop Assembly Manager")

_client = httpx.Client(base_url=CLERK_API_BASE, timeout=30.0)


def _headers() -> dict[str, str]:
    if not CLERK_SECRET_KEY:
        # AppError takes a code, so the bare one-argument raise this used to be was a TypeError
        # rather than the misconfiguration message it meant to be. Reachable from more paths since
        # #423 - the gate now calls list_users() to authorize the roster-backed fields, so a backend
        # deployed without the key answers those with a 500 traceback instead of a named error.
        raise AppError("CLERK_SECRET_KEY is not configured", "CONFIGURATION_ERROR")
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
        # #637: the GP company this account belongs to - its tenant. Same storage pattern as
        # gpBuyerId: one publicMetadata key, null until an admin assigns it.
        "company": metadata.get("company") or None,
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


def shop_assembly_members(users: list[dict]) -> list[dict]:
    """Shop-assembly team members (#330): the subset of a Clerk roster holding a shop-assembly role,
    for the manager assignment picker. Clerk has no server-side filter on publicMetadata, so this is
    a client-side filter over the whole roster either way.

    Takes the roster rather than fetching it so the resolver can pass the request-scoped one the auth
    gate already loaded (#423) - `shopAssemblyMembers` is role-gated, and that check and this answer
    now come out of the same single call to Clerk."""
    members = set(SHOP_ASSEMBLY_ROLES)
    return [u for u in users if members.intersection(u["roles"])]


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
    return _public_metadata(user_id).get("gpBuyerId") or None


def normalize_company(company: str | None) -> str | None:
    """#637: a GP company code as it is stored on a Clerk account - trimmed, uppercased, or None to
    clear. Raises on an over-long code; GP's own company id is char(15)."""
    cleaned = (company or "").strip().upper()
    if not cleaned:
        return None
    if len(cleaned) > 15:
        raise ValidationError("A GP company code is at most 15 characters.", field="company")
    return cleaned


def update_user_company(user_id: str, company: str | None) -> dict:
    """#637: set (or clear, with None) the GP company this UC Nexus account belongs to. This is the
    account's tenant - every non-admin read and write is filtered on it - so it is admin-only, and the
    same merge-not-replace metadata write `updateUserGpBuyerId` uses."""
    return _merge_public_metadata(user_id, {"company": normalize_company(company)})


def get_user_company(user_id: str) -> str | None:
    """#637: the caller's GP company (their tenant) from Clerk publicMetadata, or None if unassigned."""
    return normalize_company(_public_metadata(user_id).get("company"))


def _public_metadata(user_id: str) -> dict:
    """One Clerk user's publicMetadata. The HTTP failure is mapped rather than surfaced raw, for the
    reason `get_user` gives: an opaque 500 couples every caller to Clerk's availability."""
    try:
        resp = _client.get(f"/users/{user_id}", headers=_headers())
        resp.raise_for_status()
        u = resp.json()
    except httpx.HTTPError as e:
        raise AppError(
            "Could not load your user profile from Clerk; please try again.", code="CLERK_UNAVAILABLE"
        ) from e
    return u.get("public_metadata") or {}
