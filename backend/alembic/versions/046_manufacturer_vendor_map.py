"""Add manufacturer_vendor_map (issue #232)

Persistent, learned mapping from a hardware line's normalized TITAN manufacturer to the GP vendor a
PO for it was confirmed against, keyed per GP company. Feeds the PO dialog's vendor suggestion and is
upserted from every confirmed PO. Unique on (gp_company, manufacturer_key) so an upsert collapses
variants of the same manufacturer onto one row per company.

Revision ID: 046
Revises: 045
Create Date: 2026-07-13
"""

import sqlalchemy as sa

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manufacturer_vendor_map",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("gp_company", sa.String(length=15), nullable=False),
        sa.Column("manufacturer_key", sa.String(), nullable=False),
        sa.Column("manufacturer_label", sa.String(), nullable=False),
        sa.Column("gp_vendor_id", sa.String(length=15), nullable=False),
        sa.Column("gp_vendor_name", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_manufacturer_vendor_map_company_key",
        "manufacturer_vendor_map",
        ["gp_company", "manufacturer_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_manufacturer_vendor_map_company_key", table_name="manufacturer_vendor_map")
    op.drop_table("manufacturer_vendor_map")
