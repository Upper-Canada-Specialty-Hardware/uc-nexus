"""Clerk authentication primitives: verify a token, resolve who the caller is, cache both per request.

Roles live in Clerk publicMetadata rather than in the session token, so identity (the JWT's ``sub``)
and authorization (roles) are two different lookups - the second one a Clerk Backend API call.

**This module no longer decides who may call what.** Until #423 every GraphQL resolver opened with
its own ``require_user(info)`` / ``require_admin(info)`` line, which made "ungated" the silent
default: a resolver that forgot the line still worked, it just also worked for anonymous callers.
That is how all four resolvers in ``app/schemas/user.py``, ``updateUserRoles`` included, shipped
reachable with no session at all (#415). The decision now lives in one table,
``app/auth_policy.py``, and is enforced from the schema extension in main.py before any resolver
runs - so an operation nobody wrote a policy for is REFUSED rather than public.

What is left here is the machinery that table drives, plus the two things a resolver body still
legitimately does for itself:

  - ``current_user(info)`` - read the identity the extension already verified. A body needs it to
    stamp the acting user on an audit row (#427) or to scope a read to the caller (#428). It is a
    dict lookup, not a second verification.
  - ``require_role(info, role)`` - a CONDITIONAL role check inside a body, for the one requirement
    that is not a property of the field: ``assignOpenings`` lets anyone self-assign but only a Shop
    Assembly Manager assign to somebody else (#330).

``require_admin_request`` is separate again: the plain FastAPI routes in main.py have no Strawberry
info to unwrap and no extension running for them, so they carry their own gate.

Everything is memoised on the Strawberry context dict, which ``get_context`` builds fresh per
request. A query hitting eight root fields verifies its JWT once and looks up roles at most once,
where #415's shape paid for both per field.
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
# The role that may approve or reject a drafted receive - the second pair of eyes between a counted
# truck and a posted GP receipt. Admin/Manager satisfies the same fields, which is why those entries
# in ROOT_FIELD_POLICY are a frozenset of both rather than this name alone.
WAREHOUSE_MANAGER_ROLE = "Warehouse Manager"

_CLERK_JWKS_URL = "https://api.clerk.com/v1/jwks"
_JWKS_TTL_SECONDS = 3600.0
_jwks_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}

# Display names are looked up per audit-writing mutation since #427, which put a Clerk round-trip on
# hot write paths that never had one - savePickDraft fires on every keystroke batch of a pick sheet.
# A name only changes through `updateUserName` (an admin action, which invalidates this), so a short
# TTL costs nothing in accuracy and keeps the picker's save at one Postgres transaction.
_DISPLAY_NAME_TTL_SECONDS = 300.0
_display_name_cache: dict[str, tuple[float, str]] = {}


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
    """Strawberry context_getter: stash the request, and give this request somewhere to memoise.

    The dict returned here is the whole per-request store the caches below use. Strawberry wraps this
    as a FastAPI dependency, so it runs once per HTTP request and returns a NEW dict every time -
    which is the reason one caller's verified identity or roles can never be served to another. A
    module-level cache keyed by anything would not have that property.

    The request must be type-annotated; an unannotated parameter would be treated by FastAPI as a
    query parameter and break every request.
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


# Keys under which the per-request memos live on the context dict from get_context. Underscored so
# they read as internal beside the "request" key resolvers do touch.
_IDENTITY_KEY = "_auth_user_id"
_ROLES_KEY = "_auth_roles"
_ROSTER_KEY = "_auth_user_roster"


def authenticated_user_id(context) -> str:
    """The caller's Clerk user id, verifying the request's JWT the first time and reusing it after.

    Both outcomes are memoised, the refusal as well as the identity. A query naming eight root fields
    resolves eight times through the extension, and an expired token should cost one JWKS/verify
    round of work for the whole request rather than eight - the failure is a property of the request,
    not of the field that happened to ask.
    """
    cached = context.get(_IDENTITY_KEY)
    if isinstance(cached, AppError):
        raise cached
    if cached is not None:
        return cached

    try:
        token = _bearer_token(context["request"])
        if not token:
            raise AuthError("Authentication required")
        claims = verify_clerk_token(token)
        user_id = claims.get("sub")
        if not user_id:
            raise AuthError("Authentication token has no subject")
    except AppError as e:
        context[_IDENTITY_KEY] = e
        raise

    context[_IDENTITY_KEY] = user_id
    return user_id


def caller_roles(context) -> list[str]:
    """The caller's Clerk roles, looked up once per request.

    Roles are in publicMetadata, not in the session token, so this is a Clerk Backend API call. Under
    #415 every `require_admin(info)` made its own, meaning the admin landing page paid one per admin
    query it fired; now the whole request shares this one.
    """
    roles = context.get(_ROLES_KEY)
    if roles is None:
        roles = context[_ROLES_KEY] = user_repository.get_user_roles(authenticated_user_id(context))
    return roles


def user_roster(context) -> list[dict]:
    """Every Clerk user, once per request - the roster `users`, `adminStats` and `shopAssemblyMembers`
    each need in full.

    Loading it also fills the roles memo, because the roster carries roles per user and the caller is
    one of them. That is what removes `adminStats`' second Clerk round trip: the gate's role lookup
    and the resolver's own `list_users()` collapse into this single call (see ROSTER_BACKED in
    app/auth_policy.py).
    """
    roster = context.get(_ROSTER_KEY)
    if roster is None:
        roster = context[_ROSTER_KEY] = user_repository.list_users()
    return roster


def current_user(info) -> dict:
    """The authenticated caller, as {user_id}, for a resolver body that needs to know who asked.

    This does NOT gate anything - by the time a body runs, `enforce_root_field` has already refused
    everyone it was going to (app/auth_policy.py). It is the read of that verified identity, so the
    bodies that stamp an actor on an audit row (#427) or scope a query to the caller's own buyer
    assignment (#428) keep working without re-verifying the token.

    It still raises rather than returning None when there is no identity, so calling it from an
    operation on the OPEN_OPERATIONS allowlist - where no gate ran - fails loudly instead of
    attributing the action to nobody.
    """
    return {"user_id": authenticated_user_id(info.context)}


def resolve_display_name(user_id: str) -> str:
    """Full name (falling back to email, then the Clerk user id) for the acting user - issue #199's
    server-side received_by, so a receive records the Clerk-authenticated caller, not the relay's
    Windows account. Mirrors the frontend's useIdentity() fullName-or-email convention.

    Issue #427 made this the source of EVERY actor stamped on an audit or history row, not just a
    receive's. Before that each mutation took the name from its own arguments, so a signed-in user
    could attribute their action to anyone: `completePullRequest(id, completedBy: "Someone Else")`
    put that name on every opening the pull staged. The client no longer gets a say - the name comes
    from the same Clerk token the gate already verified."""
    cached = _display_name_cache.get(user_id)
    now = time.monotonic()
    if cached is not None and (now - cached[0]) < _DISPLAY_NAME_TTL_SECONDS:
        return cached[1]
    profile = user_repository.get_user(user_id)
    full_name = f"{profile['first_name']} {profile['last_name']}".strip()
    name = full_name or profile["email"] or user_id
    _display_name_cache[user_id] = (now, name)
    return name


def invalidate_display_name(user_id: str) -> None:
    """Drop a cached display name so a rename shows up on the next audit row instead of up to
    `_DISPLAY_NAME_TTL_SECONDS` later. Called by `updateUserName`, the only thing that changes one."""
    _display_name_cache.pop(user_id, None)


def require_admin_request(request) -> dict:
    """Enforce Admin/Manager on a bare FastAPI Request, for the plain HTTP routes in main.py that have
    no Strawberry `info` to unwrap and no schema extension running for them. Same two lookups the
    GraphQL path makes - identity from the Clerk JWT, roles from the Clerk Backend API - so a route
    and a root field cannot drift apart on what "admin" means. Returns {user_id, roles}.

    Deliberately un-memoised: a plain route handles one request and makes one check, so there is no
    second call to save, and taking the per-request store would mean inventing one for a Request that
    never goes through `get_context`. `/testing/clerk-sign-in` and `/admin/reset-data` depend on this
    path staying exactly as it was (#422)."""
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
    """Enforce a role from INSIDE a resolver body. Returns {user_id, roles}.

    Field-level role requirements belong in ROOT_FIELD_POLICY, not here - the extension applies them
    before the body runs. This is for the requirement that is not a property of the field:
    `assignOpenings` lets any signed-in user claim work for themselves and only a Shop Assembly
    Manager hand it to somebody else (#330), so the check depends on the arguments and can only be
    made once the body has them.

    Reads the per-request role memo, so a body-level check on a field whose policy already resolved
    roles adds no Clerk call.
    """
    roles = caller_roles(info.context)
    if role not in roles:
        raise ForbiddenError(f"{role} role required")
    return {"user_id": authenticated_user_id(info.context), "roles": roles}


def require_any_role(info, roles: frozenset[str]) -> dict:
    """`require_role` for a requirement satisfied by any one of several roles. Returns {user_id, roles}.

    Same rule about where requirements belong: if the field ALWAYS needs one of these, put the
    frozenset in ROOT_FIELD_POLICY and let the extension apply it. This is for the conditional case -
    `updateReceiveDraft` lets the draft's own author edit it and otherwise needs a Warehouse Manager
    or an admin, which is only decidable once the body knows whose draft it is.
    """
    caller = caller_roles(info.context)
    if not roles & set(caller):
        raise ForbiddenError(f"{' or '.join(sorted(roles))} role required")
    return {"user_id": authenticated_user_id(info.context), "roles": caller}
