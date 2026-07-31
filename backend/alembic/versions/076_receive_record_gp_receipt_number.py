"""A receive carries the GP receipt it posted (#447)

Revision ID: 076
Revises: 075
Create Date: 2026-07-31

Receiving is GP-first: the relay posts the eConnect receipt, GP mints an RCT###### receipt number
and puts it in a batch, and only then does Nexus write its own receive row. The relay has always
returned both numbers in its create_receipt response and the backend has always dropped them, so the
two systems recorded the same physical event with no shared identifier. Anyone reconciling a receive
against GP - or answering "which receipt was this delivery" from the Receiving page - had to match on
PO number and timestamp by hand.

  receipt_number - GP POP receipt number (RCT######), what accounting and the warehouse both call it
  batch_number   - the GP batch it landed in, needed to find it before the batch is posted

Both are NULLABLE and there is no backfill. GP holds every historical receipt, but nothing in either
system maps one back to a specific pre-#447 receive row, so inventing a value would be a guess
presented as a record. Null means "posted before Nexus recorded this", which the UI shows as a dash.

The index is on receipt_number only: a receipt number is the thing someone types in from a GP screen
or a packing slip to find the Nexus receive behind it. Batch numbers are read off a row that has
already been found, never searched by, so an index there would cost writes and answer nothing.

`downgrade()` drops the index and both columns, losing only the GP identifiers - the receive itself,
its line items and the inventory it created are untouched.
"""

import sqlalchemy as sa

from alembic import op

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receive_records", sa.Column("receipt_number", sa.String(length=50), nullable=True))
    op.add_column("receive_records", sa.Column("batch_number", sa.String(length=50), nullable=True))
    op.create_index("ix_receive_records_receipt_number", "receive_records", ["receipt_number"])


def downgrade() -> None:
    op.drop_index("ix_receive_records_receipt_number", table_name="receive_records")
    op.drop_column("receive_records", "batch_number")
    op.drop_column("receive_records", "receipt_number")
