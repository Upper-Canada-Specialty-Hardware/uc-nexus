"""Shipping-out request items carry the door leaf (#335)

Revision ID: 058
Revises: 057
Create Date: 2026-07-24

Issue #335: the Shipping Out import can now request an assembled door leaf (an OPENING_ITEM line
pointing at an OpeningItem). Snapshot the leaf on the request line so the pre-accept Shipping
Requests inbox can tell a pair's two lines apart; accept copies it onto pull_request_items.leaf.

Additive, nullable smallint, no backfill. #311's revision 056 added leaf to six tables and skipped
this one; existing rows stay null and accept falls back to reading OpeningItem.leaf.
"""

import sqlalchemy as sa

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipping_out_request_items", sa.Column("leaf", sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("shipping_out_request_items", "leaf")
