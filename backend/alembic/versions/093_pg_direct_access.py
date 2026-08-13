"""Registry + audit for minted direct-Postgres logins

Revision ID: 093
Revises: 092
Create Date: 2026-08-12

The Database Access page mints per-user Postgres logins over the public proxy (db-admin-postgres-access).
Two tables back it:

- `pg_direct_access` - the registry. One row per grant, tying a deterministic `nexus_rw` role to a
  Clerk user. It is the allowlist every guardrail checks. The two partial uniques enforce "one live
  grant per user" and "one live role name" while leaving a revoked user re-mintable (same role name,
  new row, old row kept for history) - which is why `db_role` is not globally unique.
- `pg_direct_access_audit` - append-only, who did what on the page. `action` is a plain string with a
  CHECK rather than a DB enum, to keep the fixed three-value set out of the two enum-sync files.

The Postgres ROLES themselves are cluster-level and deliberately NOT managed here - they are created
and dropped by the repository at runtime, since a role would collide across the PR-env clones and CI
runs that share a cluster. This migration only owns the two bookkeeping tables.
"""

import sqlalchemy as sa

from alembic import op

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pg_direct_access",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("db_role", sa.String(length=63), nullable=False),
        sa.Column("clerk_user_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    # One live grant per user, one live role name - re-mintable after revoke because a closed row
    # (revoked_at set) drops out of both.
    op.create_index(
        "uq_pg_direct_access_live_user",
        "pg_direct_access",
        ["clerk_user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index(
        "uq_pg_direct_access_live_role",
        "pg_direct_access",
        ["db_role"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "pg_direct_access_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("actor_clerk_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("db_role", sa.String(length=63), nullable=False),
        sa.Column("target_clerk_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action IN ('MINT', 'ROTATE', 'REVOKE')",
            name="ck_pg_direct_access_audit_action",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("pg_direct_access_audit")
    op.drop_index("uq_pg_direct_access_live_role", table_name="pg_direct_access")
    op.drop_index("uq_pg_direct_access_live_user", table_name="pg_direct_access")
    op.drop_table("pg_direct_access")
