"""GP-owned PO mirror: origin/gp_synced_at, nullable request_number, sync-state table

Revision ID: 098
Revises: 097
Create Date: 2026-08-24

A PO is only real once it is in GP. This lands the schema for mirroring GP's own purchase orders into
local rows keyed by (gp_company, po_number), so a PO created directly in GP - or stranded after a
schema reset - is visible and receivable instead of invisible.

purchase_orders gains:
- origin (po_origin enum, default NEXUS) - NEXUS for a PO drafted here, GP for one the mirror sync
  discovered. Existing rows are all NEXUS.
- gp_synced_at - when the sync last wrote GP-derived fields onto the row.
- request_number becomes nullable - a mirrored PO was never raised through Nexus, so it has none and
  the register falls back to po_number. The unique index stays (many NULLs never collide).
- a partial unique index on (gp_company, po_number) where po_number is not null - the upsert key the
  sync converges on. A nexus-registered PO stamps both together, so it collapses onto its mirror row.

gp_po_sync_state is the per-company cursor: backfill vs incremental, keyset cursor, modified watermark.

Downgrade reverses all of it. request_number is restored NOT NULL, which is safe only if no mirrored
(null-request-number) rows remain - fine in dev, and any GP-origin rows would be dropped first.
"""

import sqlalchemy as sa

from alembic import op

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None

_ORIGIN_ENUM = sa.Enum("NEXUS", "GP", name="po_origin")
_GP_KEY_INDEX = "ix_purchase_orders_gp_company_po_number"


def upgrade() -> None:
    _ORIGIN_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "purchase_orders",
        sa.Column("origin", _ORIGIN_ENUM, nullable=False, server_default="NEXUS"),
    )
    op.add_column("purchase_orders", sa.Column("gp_synced_at", sa.DateTime(), nullable=True))
    op.alter_column("purchase_orders", "request_number", existing_type=sa.String(50), nullable=True)
    op.create_index(
        _GP_KEY_INDEX,
        "purchase_orders",
        ["gp_company", "po_number"],
        unique=True,
        postgresql_where=sa.text("po_number IS NOT NULL"),
    )

    op.create_table(
        "gp_po_sync_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company", sa.String(15), nullable=False),
        sa.Column("watermark", sa.DateTime(), nullable=True),
        sa.Column("backfill_cursor", sa.String(17), nullable=True),
        sa.Column("backfill_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company", name="uq_gp_po_sync_state_company"),
    )


def downgrade() -> None:
    op.drop_table("gp_po_sync_state")
    op.drop_index(_GP_KEY_INDEX, table_name="purchase_orders")

    # A mirrored PO has a null request_number and must be gone before the column can go NOT NULL again.
    # None of the child tables (po_line_items / po_documents / po_document_data / receive_records +
    # receive_line_items / receive_drafts) has ON DELETE CASCADE, and a GP-origin PO can have received
    # into inventory, so the whole descendant graph is torn down FK-first, children before parents,
    # before deleting the POs themselves. (The migration-integrity job runs this on an empty DB, so
    # order does not matter there; a populated dev DB is why it does.)
    op.execute(
        """
        -- inventory received under a GP PO: clear the RESTRICT referrers, then drop the rows (they sit
        -- above both po_line_items and receive_line_items, so they must go first).
        UPDATE deficiency_reviews SET inventory_location_id = NULL
        WHERE inventory_location_id IN (
          SELECT il.id FROM inventory_locations il
          WHERE il.po_line_item_id IN (
                  SELECT li.id FROM po_line_items li
                  WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
             OR il.receive_line_item_id IN (
                  SELECT rli.id FROM receive_line_items rli
                  WHERE rli.receive_record_id IN (
                          SELECT rr.id FROM receive_records rr
                          WHERE rr.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
                     OR rli.po_line_item_id IN (
                          SELECT li.id FROM po_line_items li
                          WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))))
        """
    )
    op.execute(
        """
        UPDATE shipment_return_items SET resulting_inventory_location_id = NULL
        WHERE resulting_inventory_location_id IN (
          SELECT il.id FROM inventory_locations il
          WHERE il.po_line_item_id IN (
                  SELECT li.id FROM po_line_items li
                  WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
             OR il.receive_line_item_id IN (
                  SELECT rli.id FROM receive_line_items rli
                  WHERE rli.receive_record_id IN (
                          SELECT rr.id FROM receive_records rr
                          WHERE rr.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
                     OR rli.po_line_item_id IN (
                          SELECT li.id FROM po_line_items li
                          WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))))
        """
    )
    op.execute(
        """
        DELETE FROM inventory_locations
        WHERE po_line_item_id IN (
                SELECT li.id FROM po_line_items li
                WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
           OR receive_line_item_id IN (
                SELECT rli.id FROM receive_line_items rli
                WHERE rli.receive_record_id IN (
                        SELECT rr.id FROM receive_records rr
                        WHERE rr.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
                   OR rli.po_line_item_id IN (
                        SELECT li.id FROM po_line_items li
                        WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')))
        """
    )
    op.execute(
        """
        DELETE FROM receive_line_items
        WHERE receive_record_id IN (
                SELECT rr.id FROM receive_records rr
                WHERE rr.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
           OR po_line_item_id IN (
                SELECT li.id FROM po_line_items li
                WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
        """
    )
    # Release schedule hardware the GP lines claimed, so dropping the lines does not trip the RESTRICT FK.
    op.execute(
        """
        UPDATE hardware_items SET state = 'AVAILABLE', po_line_item_id = NULL
        WHERE po_line_item_id IN (
          SELECT li.id FROM po_line_items li
          WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
        """
    )
    # Receive drafts and their lines (draft lines have a RESTRICT FK onto po_line_items).
    op.execute(
        """
        DELETE FROM receive_draft_line_items
        WHERE po_line_item_id IN (
          SELECT li.id FROM po_line_items li
          WHERE li.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
        """
    )
    op.execute(
        """
        UPDATE receive_drafts SET receive_record_id = NULL
        WHERE receive_record_id IN (
          SELECT rr.id FROM receive_records rr
          WHERE rr.po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP'))
        """
    )
    op.execute("DELETE FROM receive_drafts WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')")
    op.execute("DELETE FROM receive_records WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')")
    op.execute("DELETE FROM po_documents WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')")
    op.execute("DELETE FROM po_document_data WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')")
    op.execute("DELETE FROM po_line_items WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'GP')")
    op.execute("DELETE FROM purchase_orders WHERE origin = 'GP'")

    op.alter_column("purchase_orders", "request_number", existing_type=sa.String(50), nullable=False)
    op.drop_column("purchase_orders", "gp_synced_at")
    op.drop_column("purchase_orders", "origin")
    _ORIGIN_ENUM.drop(op.get_bind(), checkfirst=True)
