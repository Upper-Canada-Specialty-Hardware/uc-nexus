"""Direct-Postgres access queries + mutations (db-admin-postgres-access).

Every field here is gated on the "DB Admin" role in ROOT_FIELD_POLICY (app/auth_policy.py) - the tier
ABOVE Admin/Manager, so unlike the rest of the admin module these do NOT admit a plain admin. The
repository (db_access_repository) carries the real guardrails and refuses every operation when the
feature is disabled (no proxy configured, or a preview environment), so a resolver that slipped past
the gate still cannot mint anything.

`postgresAdmins` and `postgresAccessAudit` are ROSTER_BACKED: they need the Clerk roster both to
authorize the caller's role and to put names/emails on the rows, so the two come from one Clerk call.
"""

from datetime import datetime

import strawberry

from app import config
from app.auth import ADMIN_ROLE, current_user, user_roster
from app.errors import AppError, ValidationError
from app.repositories import db_access_repository, user_repository


@strawberry.type
class PostgresLogin:
    """A live minted login, as the Database Access grid shows it."""

    db_role: str
    clerk_user_id: str
    display_name: str | None
    email: str | None
    # The user is gone from Clerk but the login lives on - the one most in need of a revoke, so it is
    # flagged rather than dropped.
    clerk_missing: bool
    # The role really is present in the cluster and a live nexus_rw member. False means the registry
    # says live but the cluster disagrees (a role dropped out from under the row).
    active: bool
    created_at: datetime
    last_rotated_at: datetime | None


@strawberry.type
class PostgresAccessCredential:
    """The one-time output of a mint or rotate: the connection strings, shown once and stored nowhere."""

    db_role: str
    clerk_user_id: str
    adodb_connection_string: str
    access_connection_string: str


@strawberry.type
class PostgresAccessAuditEntry:
    id: strawberry.ID
    action: str
    db_role: str
    actor_clerk_id: str
    actor_name: str | None
    target_clerk_id: str | None
    target_name: str | None
    created_at: datetime


def _login(d: dict) -> PostgresLogin:
    return PostgresLogin(
        db_role=d["db_role"],
        clerk_user_id=d["clerk_user_id"],
        display_name=d["display_name"],
        email=d["email"],
        clerk_missing=d["clerk_missing"],
        active=d["active"],
        created_at=d["created_at"],
        last_rotated_at=d["last_rotated_at"],
    )


def _credential(d: dict) -> PostgresAccessCredential:
    return PostgresAccessCredential(
        db_role=d["db_role"],
        clerk_user_id=d["clerk_user_id"],
        adodb_connection_string=d["adodb_connection_string"],
        access_connection_string=d["access_connection_string"],
    )


def _audit_entry(d: dict) -> PostgresAccessAuditEntry:
    return PostgresAccessAuditEntry(
        id=strawberry.ID(str(d["id"])),
        action=d["action"],
        db_role=d["db_role"],
        actor_clerk_id=d["actor_clerk_id"],
        actor_name=d["actor_name"],
        target_clerk_id=d["target_clerk_id"],
        target_name=d["target_name"],
        created_at=d["created_at"],
    )


@strawberry.type
class DbAccessQueries:
    @strawberry.field
    def postgres_admins(self, info: strawberry.Info) -> list[PostgresLogin]:
        """The live registry, joined to the Clerk roster the gate already fetched (ROSTER_BACKED)."""
        return [_login(d) for d in db_access_repository.list_admins(user_roster(info.context))]

    @strawberry.field
    def postgres_access_audit(self, info: strawberry.Info) -> list[PostgresAccessAuditEntry]:
        """The mint/rotate/revoke history, newest first, names resolved against the same roster."""
        return [_audit_entry(d) for d in db_access_repository.list_audit(user_roster(info.context))]


@strawberry.type
class DbAccessMutations:
    @strawberry.mutation
    def mint_postgres_admin(self, info: strawberry.Info, clerk_user_id: str) -> PostgresAccessCredential:
        """Mint a login for a Clerk user and return its connection strings once.

        Refuses a target who does not hold Admin/Manager: direct read-write db access only goes to
        people already trusted with the whole app. The env check comes first so a disabled environment
        pays no Clerk round trip."""
        if not config.db_direct_access_enabled():
            raise AppError("Direct database access is not enabled in this environment.", "FEATURE_DISABLED")
        if ADMIN_ROLE not in user_repository.get_user_roles(clerk_user_id):
            raise ValidationError("Direct database access can only be granted to an Admin/Manager holder.")
        actor = current_user(info)["user_id"]
        return _credential(db_access_repository.mint(clerk_user_id, actor_clerk_id=actor))

    @strawberry.mutation
    def rotate_postgres_admin(self, info: strawberry.Info, db_role: str) -> PostgresAccessCredential:
        """A fresh password for an existing login, returned once."""
        actor = current_user(info)["user_id"]
        return _credential(db_access_repository.rotate(db_role, actor_clerk_id=actor))

    @strawberry.mutation
    def revoke_postgres_admin(self, info: strawberry.Info, db_role: str) -> bool:
        """End a login now: terminate its sessions, drop the role, close its registry row."""
        actor = current_user(info)["user_id"]
        db_access_repository.revoke(db_role, actor_clerk_id=actor)
        return True
