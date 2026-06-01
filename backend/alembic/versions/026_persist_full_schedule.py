"""Persist full hardware schedule: add AVAILABLE state, snapshot opening on SAR, drop opening FKs

Revision ID: 026
Revises: 025
Create Date: 2026-06-01
"""

import sqlalchemy as sa

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add AVAILABLE to hardware_item_state enum (idempotent; ordered before IN_PO to
    #    match the Python enum declaration order so alembic check sees no drift)
    op.execute("ALTER TYPE hardware_item_state ADD VALUE IF NOT EXISTS 'AVAILABLE' BEFORE 'IN_PO'")

    # 2. Add snapshot columns to shop_assembly_openings (nullable for backfill)
    op.add_column("shop_assembly_openings", sa.Column("opening_number", sa.String(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("building", sa.String(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("floor", sa.String(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("location", sa.String(), nullable=True))

    # 3. Backfill snapshot columns from openings table
    op.execute(
        """
        UPDATE shop_assembly_openings sao
        SET opening_number = o.opening_number,
            building       = o.building,
            floor          = o.floor,
            location       = o.location
        FROM openings o
        WHERE sao.opening_id = o.id
        """
    )

    # 4. Make opening_number NOT NULL now that it's backfilled
    op.alter_column("shop_assembly_openings", "opening_number", nullable=False)

    # 5. Drop FK from shop_assembly_openings.opening_id -> openings.id
    #    (column stays NOT NULL as historical UUID; just no longer enforced referentially)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'shop_assembly_openings_opening_id_fkey'
            ) THEN
                ALTER TABLE shop_assembly_openings
                DROP CONSTRAINT shop_assembly_openings_opening_id_fkey;
            END IF;
        END $$;
        """
    )

    # 6. Drop FK from opening_items.opening_id -> openings.id
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'opening_items_opening_id_fkey'
            ) THEN
                ALTER TABLE opening_items
                DROP CONSTRAINT opening_items_opening_id_fkey;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Reverse FK drops (re-create with original implicit names)
    op.create_foreign_key(
        "opening_items_opening_id_fkey",
        "opening_items",
        "openings",
        ["opening_id"],
        ["id"],
    )

    op.create_foreign_key(
        "shop_assembly_openings_opening_id_fkey",
        "shop_assembly_openings",
        "openings",
        ["opening_id"],
        ["id"],
    )

    # Drop snapshot columns
    op.drop_column("shop_assembly_openings", "location")
    op.drop_column("shop_assembly_openings", "floor")
    op.drop_column("shop_assembly_openings", "building")
    op.drop_column("shop_assembly_openings", "opening_number")

    # AVAILABLE enum value is intentionally left in place; Postgres cannot drop enum
    # values cleanly, and adding it back later is idempotent via IF NOT EXISTS.
