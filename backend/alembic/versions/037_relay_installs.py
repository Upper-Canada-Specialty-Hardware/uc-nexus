"""relay_installs: per-install relay Bearer secret (encrypted) + one-time enrollment token
(uc nexus <-> relay full spec, backend-issued per-install secret)

Revision ID: 037
Revises: 036
Create Date: 2026-06-25
"""

import sqlalchemy as sa

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relay_installs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("hostname", sa.String(), nullable=True),
        sa.Column("secret_encrypted", sa.Text(), nullable=True),
        sa.Column("enrollment_token_hash", sa.String(), nullable=True),
        sa.Column("enrollment_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_relay_installs_enrollment_token_hash", "relay_installs", ["enrollment_token_hash"])


def downgrade() -> None:
    op.drop_index("ix_relay_installs_enrollment_token_hash", table_name="relay_installs")
    op.drop_table("relay_installs")
