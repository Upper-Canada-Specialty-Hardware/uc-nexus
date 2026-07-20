"""Re-parent shop_assembly_openings from SAR to the shop-assembly PullRequest

Adds shop_assembly_openings.pull_request_id (FK -> pull_requests) and relaxes
shop_assembly_request_id to nullable, so openings created directly from Start a Task
hang off a PullRequest instead of a SAR (#222).

Revision ID: 042
Revises: 041
Create Date: 2026-07-09
"""

import sqlalchemy as sa

from alembic import op

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy SAR parent is now optional — PR-parented openings have no SAR.
    op.alter_column(
        "shop_assembly_openings",
        "shop_assembly_request_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    # New parent: the shop-assembly PullRequest the opening was created under.
    op.add_column(
        "shop_assembly_openings",
        sa.Column(
            "pull_request_id",
            sa.Uuid(),
            sa.ForeignKey("pull_requests.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_shop_assembly_openings_pull_request",
        "shop_assembly_openings",
        ["pull_request_id"],
    )


def downgrade() -> None:
    # PR-parented openings (Start a Task, #222) have shop_assembly_request_id NULL, so
    # re-tightening it to NOT NULL would abort. Refuse rather than silently drop or orphan
    # them - the operator must remove them before downgrading past 042.
    bind = op.get_bind()
    orphans = bind.execute(
        sa.text("SELECT count(*) FROM shop_assembly_openings WHERE shop_assembly_request_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"Cannot downgrade past migration 042: {orphans} shop_assembly_openings row(s) are "
            "PR-parented (shop_assembly_request_id IS NULL). Delete them before downgrading."
        )

    op.drop_index("ix_shop_assembly_openings_pull_request", table_name="shop_assembly_openings")
    op.drop_column("shop_assembly_openings", "pull_request_id")
    op.alter_column(
        "shop_assembly_openings",
        "shop_assembly_request_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
