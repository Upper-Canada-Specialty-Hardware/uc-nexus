"""a project's list of product classifications, apart from its hardware schedule (issue #1443)

A product's UCH Shop / UCH Site was stored only on its schedule rows, so a schedule replace that dropped
a product nobody had ordered took its rows, and its classification, with it. The product owner ruled that
classifications belong to the project: a newer schedule appends to the list and never changes what is on
it, and a product a newer schedule dropped stays listed.

The backfill lists every product whose classified schedule rows all agree. A product whose rows disagree
(Mixed) is left off until somebody sets it on the Hardware Classifications page, and so is a product the
project has as By Others, which stays a project_excluded_items row and is not this list's business.

Revision ID: 155
Revises: 154
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "155"
down_revision = "154"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_product_classifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column(
            "classification",
            # The type hardware_items.classification already uses; not created again.
            postgresql.ENUM("SITE_HARDWARE", "SHOP_HARDWARE", name="classification", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "hardware_category", "product_code", name="uq_project_product_classifications"
        ),
    )
    op.execute(
        """
        INSERT INTO project_product_classifications
            (id, project_id, hardware_category, product_code, classification, created_at, updated_at)
        SELECT gen_random_uuid(), hi.project_id, hi.hardware_category, hi.product_code,
               MIN(hi.classification::text)::classification, now() AT TIME ZONE 'utc', now() AT TIME ZONE 'utc'
        FROM hardware_items hi
        WHERE hi.classification IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM project_excluded_items pei
              WHERE pei.project_id = hi.project_id
                AND pei.hardware_category = hi.hardware_category
                AND pei.product_code = hi.product_code
          )
        GROUP BY hi.project_id, hi.hardware_category, hi.product_code
        HAVING COUNT(DISTINCT hi.classification) = 1
        """
    )


def downgrade() -> None:
    op.drop_table("project_product_classifications")
