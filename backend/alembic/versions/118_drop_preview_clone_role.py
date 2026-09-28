"""drop the preview_clone login (issue #868)

PR environments were retired as a test surface, and with them the production clone they booted from.
Production used to create a read-only `preview_clone` login (pg_read_all_data, a password from
PREVIEW_CLONE_PASSWORD) at every startup so a preview could pg_dump it over the public proxy. Nothing
creates or uses it any more, and an unused internet-reachable login that can read every table is not
something to leave behind.

Guarded: the role only exists where production minted it, and a refusal (a cluster that will not let
this login drop it) is reported as a NOTICE rather than failing the deploy - the role is inert either
way once nothing hands out its password. No downgrade: the password was never stored anywhere a
migration could read it back from.

Revision ID: 118
Revises: 117
Create Date: 2026-09-28
"""

from alembic import op

revision = "118"
down_revision = "117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'preview_clone') THEN
                BEGIN
                    DROP ROLE preview_clone;
                EXCEPTION WHEN OTHERS THEN
                    RAISE NOTICE 'could not drop the preview_clone role: %', SQLERRM;
                END;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    pass
