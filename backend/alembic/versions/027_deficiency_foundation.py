"""Phase 1: deficiency foundation — deficient_quantity on inventory_locations + audit enum values

Revision ID: 027
Revises: 026
Create Date: 2026-06-04
"""

import sqlalchemy as sa

from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add deficient_quantity column to inventory_locations
    op.add_column(
        "inventory_locations",
        sa.Column("deficient_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    # Drop server_default so model default takes over for new rows
    op.alter_column("inventory_locations", "deficient_quantity", server_default=None)

    # 2. Add CHECK constraints for the new column
    op.create_check_constraint(
        "ck_inventory_locations_deficient_quantity_nonneg",
        "inventory_locations",
        "deficient_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_inventory_locations_deficient_within_quantity",
        "inventory_locations",
        "deficient_quantity <= quantity",
    )

    # 3. Extend audit_action enum with new values used by the stock + deficiency flows
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'DESTOCK'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'ALLOCATE_FROM_STOCK'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'RECLASSIFY'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'REPORT_DEFICIENT'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'RESOLVE_DEFICIENT'")

    # 4. Extend audit_entity_type enum so stock items can be referenced as audit subjects
    op.execute("ALTER TYPE audit_entity_type ADD VALUE IF NOT EXISTS 'STOCK_ITEM'")


def downgrade() -> None:
    op.drop_constraint(
        "ck_inventory_locations_deficient_within_quantity",
        "inventory_locations",
        type_="check",
    )
    op.drop_constraint(
        "ck_inventory_locations_deficient_quantity_nonneg",
        "inventory_locations",
        type_="check",
    )
    op.drop_column("inventory_locations", "deficient_quantity")

    # Rebuild audit_action enum without the new values (Postgres has no DROP VALUE)
    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")
    new_action = sa.Enum(
        "ADJUSTMENT",
        "MOVE",
        "UNLOCATE",
        "RECEIVE",
        "PULL_DEDUCTION",
        "SPOT_CHECK",
        "PUT_AWAY",
        name="audit_action",
    )
    new_action.create(op.get_bind(), checkfirst=False)
    op.execute("ALTER TABLE inventory_audit_log ALTER COLUMN action TYPE audit_action USING action::text::audit_action")
    op.execute("DROP TYPE audit_action_old")

    # Rebuild audit_entity_type enum without STOCK_ITEM
    op.execute("ALTER TYPE audit_entity_type RENAME TO audit_entity_type_old")
    new_entity = sa.Enum(
        "INVENTORY_LOCATION",
        "OPENING_ITEM",
        name="audit_entity_type",
    )
    new_entity.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE inventory_audit_log "
        "ALTER COLUMN entity_type TYPE audit_entity_type "
        "USING entity_type::text::audit_entity_type"
    )
    op.execute("DROP TYPE audit_entity_type_old")
