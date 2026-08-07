"""Per-project pull-request number counters

Revision ID: 087
Revises: 086
Create Date: 2026-08-06

Request numbers on shop-assembly and shipping-out requests were typed by hand (#493). That made a
uniqueness constraint the user's problem to satisfy from memory, and nothing tied a number to the
job it belonged to. The server mints them now, as <project number>-001, -002, ... with one sequence
per project spanning both request types.

The seed reads the highest numeric suffix already in use per project, across shop_assembly_requests,
shipping_out_requests and pull_requests, so an existing project carries on from where its
hand-typed numbers left off rather than colliding with them. Numbers that do not end in a suffix
this scheme would produce are ignored by the seed - they cannot collide with a generated one.
"""

import sqlalchemy as sa

from alembic import op

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


# Highest -NNN suffix per project across every table that carries a live request number. The regex
# anchors on the project's own number so a "23093-004" seeds project 23093 and nothing else.
_SEED = """
INSERT INTO project_request_counters (project_id, next_value)
SELECT p.id, COALESCE(MAX(m.seq), 0) + 1
FROM projects p
LEFT JOIN (
    SELECT r.project_id,
           (regexp_match(r.request_number, '-([0-9]+)$'))[1]::int AS seq
    FROM shop_assembly_requests r
    WHERE r.request_number ~ '-[0-9]+$'
    UNION ALL
    SELECT r.project_id,
           (regexp_match(r.request_number, '-([0-9]+)$'))[1]::int AS seq
    FROM shipping_out_requests r
    WHERE r.request_number ~ '-[0-9]+$'
    UNION ALL
    SELECT r.project_id,
           (regexp_match(r.request_number, '-([0-9]+)$'))[1]::int AS seq
    FROM pull_requests r
    WHERE r.request_number ~ '-[0-9]+$'
) m ON m.project_id = p.id
GROUP BY p.id
"""


def upgrade() -> None:
    op.create_table(
        "project_request_counters",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("next_value", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.execute(_SEED)


def downgrade() -> None:
    op.drop_table("project_request_counters")
