"""Rename po_status ORDERED -> GP_REGISTERED and drop the redundant gp_sync_status column + enum
(a PO only exists once it is in GP, so "ordered" really means "registered in GP"; a PO that fails to
create in GP is never created in UC Nexus, so there is no persisted FAILED and gp_sync_status is
redundant with the status)

Revision ID: 039
Revises: 038
Create Date: 2026-06-29
"""

from alembic import op

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def _rename_enum_value_if_exists(type_name: str, old: str, new: str) -> str:
    """Idempotent enum-value rename (mirrors migration 010) so the integrity round-trip stays clean."""
    return f"""
    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_enum
            WHERE enumlabel = '{old}'
              AND enumtypid = '{type_name}'::regtype
        ) THEN
            ALTER TYPE {type_name} RENAME VALUE '{old}' TO '{new}';
        END IF;
    END $$;
    """


def upgrade() -> None:
    op.execute(_rename_enum_value_if_exists("po_status", "ORDERED", "GP_REGISTERED"))
    op.drop_column("purchase_orders", "gp_sync_status")
    op.execute("DROP TYPE IF EXISTS gp_sync_status")


def downgrade() -> None:
    op.execute("CREATE TYPE gp_sync_status AS ENUM ('NOT_PUSHED', 'SYNCED', 'FAILED')")
    op.execute("ALTER TABLE purchase_orders ADD COLUMN gp_sync_status gp_sync_status NOT NULL DEFAULT 'NOT_PUSHED'")
    op.execute(_rename_enum_value_if_exists("po_status", "GP_REGISTERED", "ORDERED"))
