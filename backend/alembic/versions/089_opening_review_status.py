"""Per-opening review state on shop-assembly openings

Revision ID: 089
Revises: 088
Create Date: 2026-08-06

Shop-assembly review was request-level: accept or reject the whole thing (#495). One contentious
leaf held up every other leaf on the same request, and the reviewer works a pooled queue across
projects rather than one request at a time.

Review moves to the opening. The request's own status becomes a derived display value - PENDING
while any of its openings is PENDING, APPROVED once none are - so `shop_assembly_requests.status`
stays where it is and simply stops being the thing that decides.

The backfill reads the parent request: an APPROVED request's openings become ACCEPTED, a REJECTED
request's become REJECTED, and everything else stays PENDING. An opening whose request is null (a
legacy #222-era row hanging off a PullRequest alone) also lands PENDING, which is honest - nobody
reviewed it under this scheme.

DEFERRED has no backfill because nothing could have been deferred before this existed.
"""

import sqlalchemy as sa

from alembic import op

revision = "089"
down_revision = "088"
branch_labels = None
depends_on = None

_ENUM = sa.Enum("PENDING", "ACCEPTED", "REJECTED", "DEFERRED", name="opening_review_status")


def upgrade() -> None:
    _ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "shop_assembly_openings",
        sa.Column("review_status", _ENUM, nullable=False, server_default="PENDING"),
    )
    op.add_column("shop_assembly_openings", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("reviewed_by", sa.String(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("review_reason", sa.String(), nullable=True))

    # Inherit the decision already made at request level, so a queue built on this column does not
    # re-present work somebody has already accepted or turned down.
    op.execute(
        """
        UPDATE shop_assembly_openings o
        SET review_status = 'ACCEPTED'
        FROM shop_assembly_requests r
        WHERE r.id = o.shop_assembly_request_id AND r.status = 'APPROVED'
        """
    )
    op.execute(
        """
        UPDATE shop_assembly_openings o
        SET review_status = 'REJECTED'
        FROM shop_assembly_requests r
        WHERE r.id = o.shop_assembly_request_id AND r.status = 'REJECTED'
        """
    )

    op.create_index(
        "ix_shop_assembly_openings_review_status",
        "shop_assembly_openings",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_shop_assembly_openings_review_status", table_name="shop_assembly_openings")
    op.drop_column("shop_assembly_openings", "review_reason")
    op.drop_column("shop_assembly_openings", "reviewed_by")
    op.drop_column("shop_assembly_openings", "reviewed_at")
    op.drop_column("shop_assembly_openings", "review_status")
    _ENUM.drop(op.get_bind(), checkfirst=True)
