"""Relay connection events: a durable history of the relay's single connection slot (#654)

Revision ID: 103
Revises: 102
Create Date: 2026-09-01

Issue #384 made every slot transition loggable, which answers "what is happening right now" for as
long as Railway retains the log. The questions that actually get asked are later ones - how often does
it drop, was it up when that PO failed, has anything been dialling with a secret we do not recognise -
and a refused connection is the one transition that leaves no other trace at all.

`kind` is a String + CHECK rather than a PG enum, the precedent gp_write_outbox.status set in 065/068:
a CHECK is trivially reversible and this list will grow.

`install_id` is ON DELETE SET NULL with an `install_label` snapshot beside it, because retiring a
workstation (#366's delete) must not erase its history, and history that can only say "an install that
no longer exists" is worth nothing.
"""

import sqlalchemy as sa

from alembic import op

revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None

KINDS = ("CONNECTED", "DISCONNECTED", "REFUSED_SLOT", "REFUSED_SECRET", "ADOPTED")


def upgrade() -> None:
    op.create_table(
        "relay_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("install_id", sa.Uuid(), nullable=True),
        sa.Column("install_label", sa.String(), nullable=True),
        sa.Column("build", sa.String(), nullable=True),
        sa.Column("companies", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["install_id"], ["relay_installs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN (" + ", ".join(f"'{k}'" for k in KINDS) + ")", name="ck_relay_events_kind"),
    )
    # Every read of this table is "the newest N", and the 30-day prune rides the same column.
    op.create_index("ix_relay_events_at", "relay_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_relay_events_at", table_name="relay_events")
    op.drop_table("relay_events")
