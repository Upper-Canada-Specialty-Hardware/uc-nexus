"""Purge every TUCSH row the runaway PO mirror left behind

Revision ID: 105
Revises: 104
Create Date: 2026-09-03

TUCSH is excluded from every relay interaction from now on: the relay stops reporting it on its
hello frame, so no backend will sync it or offer it again. What the exclusion cannot undo is what is
already in the database - the PO history yesterday's mirror pulled from TUCSH before it was stopped,
the sync cursor it advanced, and whatever the job sync adopted alongside it. Those rows are now
unreachable by design: nothing will ever refresh them, and no screen scoped to a live company will
show them. The owner ruled they go.

Two rules shape what "go" means here, and they are the reason this is not one DELETE per table.

A row that is TUCSH bookkeeping is deleted. A row that is somebody's work is not, and the migration
says so in its log rather than cascading through it:

- A purchase order whose lines (or whose receipts) still back `inventory_locations` rows is LEFT.
  Its stock is physically on a shelf, `ck_inventory_locations_has_origin` will not let the origin be
  nulled out, and deleting the shelf row to get at the PO is not a purge, it is a write-off. Every
  such PO is printed by id and number.
- A TUCSH project with any dependent work is LEFT and printed the same way. Only a project that is
  bare once its POs are gone is deleted.

`hardware_items` is the one attachment that is neither deleted nor a blocker. A PO going away
already has sanctioned semantics for it - `gp_po_sync_repository._release_linked_hardware`, which
migration 073 encodes - so the rows are released back to AVAILABLE with a null link instead. The
count is reported as released, not deleted.

The per-table audit, every model carrying a company column plus every child of a purged purchase
order:

  purchase_orders          deleted (company = TUCSH OR gp_company = TUCSH), minus the ones holding
                           inventory, which are left and named
  po_line_items            deleted with their PO (the FK is NO ACTION, nothing cascades)
  po_documents             deleted with their PO
  po_document_data         deleted with their PO
  receive_records          deleted with their PO
  receive_line_items       deleted with their receive record / PO line
  receive_drafts           deleted with their PO (their line items cascade, and are also deleted
                           explicitly so the count is honest)
  receive_draft_line_items deleted with the draft or the PO line
  hardware_items           released (po_line_item_id NULL, state AVAILABLE), never deleted
  inventory_locations      not touched. Its presence is what makes a PO a blocker
  gp_po_sync_state         deleted (company)
  gp_write_outbox          deleted (company)
  gp_write_idempotency     deleted. No company column: the rows are found through
                           relay_result->>'company', through the outbox row that carries the same
                           key, and through result_id pointing at a TUCSH PO or receive record
  projects                 deleted only when bare; the rest left and named
  notifications            deleted with a bare project
  project_excluded_items   deleted with a bare project
  project_request_counters deleted with a bare project
  buyer_assignment_projects deleted with a bare project. The `buyer_assignments` row itself stays -
                           it is a GP buyer, not a company row
  warehouses               deleted when no inventory, stock, receive draft or return references the
                           building; `warehouse_locations` cascade with it
  inventory_item_types     deleted (company). Attributes, custom items and their values cascade
  shipment_methods         deleted (company). Nothing references them - a packing slip snapshots the
                           method as text
  manufacturer_vendor_map  deleted (gp_company)
  relay_events             not applicable. A connection-history log, not a per-company row, and the
                           point of keeping it is that retiring something must not erase its past
  relay_installs           not applicable. 104 removed the company list; an install is a credential
  po_document_settings     not applicable. `company_from_address` is the letterhead block on the
                           generated PO document, single-row and company-wide

Every statement is scoped to the one code in COMPANY and parameterised on it, and every one is
idempotent: a second run matches nothing and prints zeros.
"""

import sqlalchemy as sa

from alembic import context, op

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None

COMPANY = "TUCSH"

# Reported with a different verb: these rows are detached from the purged PO, not removed.
_RELEASED_TABLES = frozenset({"hardware_items"})

# The purchase orders this migration owns. `company` is the tenant, `gp_company` is the GP company a
# PO was pushed to or mirrored from - the mirror stamps the second, so a row can carry TUCSH there
# while its tenant column says otherwise, and both are in scope.
#
# The two NOT EXISTS clauses are the blocker rule. A PO is out of scope while inventory still points
# at it, whether through the PO line directly or through the receive line that credited the stock.
# The set stays stable for the whole purge: nothing below ever deletes a row belonging to a PO this
# query excludes, so a blocked PO cannot become purgeable halfway through.
_PURGEABLE_POS = """
    SELECT po.id
    FROM purchase_orders po
    WHERE (po.company = :company OR po.gp_company = :company)
      AND NOT EXISTS (
          SELECT 1 FROM po_line_items li
          JOIN inventory_locations il ON il.po_line_item_id = li.id
          WHERE li.po_id = po.id)
      AND NOT EXISTS (
          SELECT 1 FROM receive_records rr
          JOIN receive_line_items rli ON rli.receive_record_id = rr.id
          JOIN inventory_locations il ON il.receive_line_item_id = rli.id
          WHERE rr.po_id = po.id)
"""

_PURGEABLE_PO_LINES = f"SELECT li.id FROM po_line_items li WHERE li.po_id IN ({_PURGEABLE_POS})"

# Every TUCSH PO, blocked or not. The GP write ledger is dedup state for a company that no longer
# exists here, so it goes whether or not the PO it names survived.
_ALL_COMPANY_POS = """
    SELECT po.id FROM purchase_orders po
    WHERE po.company = :company OR po.gp_company = :company
"""

# Work. A project holding any of this is left standing and named in the log.
_PROJECT_WORK_TABLES = (
    "openings",
    "hardware_items",
    "inventory_locations",
    "inventory_reservations",
    "inventory_audit_log",
    "pull_requests",
    "packing_slips",
    "shipment_containers",
    "shipping_out_requests",
    "shop_assembly_requests",
    "sharepoint_migration_marks",
    # By the time the project pass runs, the only TUCSH POs left are the blocked ones - so this
    # clause is what stops a project being deleted out from under a PO holding inventory.
    "purchase_orders",
)

# Rows that exist only to serve a project and mean nothing without it.
_PROJECT_BOOKKEEPING_TABLES = (
    "buyer_assignment_projects",
    "notifications",
    "project_excluded_items",
    "project_request_counters",
)

_PURGEABLE_PROJECTS = "SELECT p.id FROM projects p WHERE p.company = :company" + "".join(
    f"\n      AND NOT EXISTS (SELECT 1 FROM {table} d WHERE d.project_id = p.id)" for table in _PROJECT_WORK_TABLES
)

# Anything that would strand a foreign key if the building went away. warehouse_locations is absent
# on purpose: its FK cascades, and an empty aisle registry is part of the building, not a dependent.
_WAREHOUSE_DEPENDENT_TABLES = (
    "inventory_locations",
    "stock_items",
    "receive_drafts",
    "shipment_returns",
)

_PURGEABLE_WAREHOUSES = "".join(
    f"\n      AND NOT EXISTS (SELECT 1 FROM {table} d WHERE d.warehouse_id = w.id)"
    for table in _WAREHOUSE_DEPENDENT_TABLES
)


def purge(conn) -> dict[str, int]:
    """Delete every purgeable TUCSH row on `conn`, printing one line per table.

    Returns {table name: rows affected}, in the order the statements ran. Takes a connection rather
    than reading one from `op` so the test can drive it against a transaction it controls.
    """
    counts: dict[str, int] = {}

    def run(table: str, sql: str) -> int:
        affected = conn.execute(sa.text(sql).bindparams(company=COMPANY)).rowcount
        counts[table] = affected
        verb = "released" if table in _RELEASED_TABLES else "deleted"
        print(f"purge {COMPANY}: {table} {affected} {verb}")
        return affected

    # The GP write ledger first: it is found through the outbox rows and the PO / receive ids below,
    # so it has to be resolved while all three still exist.
    run(
        "gp_write_idempotency",
        f"""
        DELETE FROM gp_write_idempotency AS led
        WHERE led.relay_result->>'company' = :company
           OR led.key IN (SELECT o.idempotency_key FROM gp_write_outbox o WHERE o.company = :company)
           OR led.result_id IN (SELECT po.id::text FROM ({_ALL_COMPANY_POS}) po)
           OR led.result_id IN (
                  SELECT rr.id::text FROM receive_records rr
                  WHERE rr.po_id IN ({_ALL_COMPANY_POS}))
        """,
    )
    run("gp_write_outbox", "DELETE FROM gp_write_outbox WHERE company = :company")

    # Counted rather than blind-updated, and skipped when the count is zero. 073 documents why: on a
    # fresh database this migration shares a transaction with 026's ALTER TYPE ... ADD VALUE, and
    # PostgreSQL refuses to parse a statement using an enum label that transaction added. An empty
    # table has nothing to release anyway.
    attached_hardware = conn.execute(
        sa.text(f"SELECT count(*) FROM hardware_items WHERE po_line_item_id IN ({_PURGEABLE_PO_LINES})").bindparams(
            company=COMPANY
        )
    ).scalar_one()
    if attached_hardware:
        conn.execute(
            sa.text(
                f"""
                UPDATE hardware_items SET state = 'AVAILABLE', po_line_item_id = NULL
                WHERE po_line_item_id IN ({_PURGEABLE_PO_LINES})
                """
            ).bindparams(company=COMPANY)
        )
    counts["hardware_items"] = attached_hardware
    print(f"purge {COMPANY}: hardware_items {attached_hardware} released")

    # Bottom-up from here. Drafts go before the documents and receive records they point at, receive
    # lines before their records and PO lines, and the PO row itself last - every query above reads
    # `purchase_orders` to decide its scope.
    run(
        "receive_draft_line_items",
        f"""
        DELETE FROM receive_draft_line_items
        WHERE po_line_item_id IN ({_PURGEABLE_PO_LINES})
           OR receive_draft_id IN (SELECT rd.id FROM receive_drafts rd WHERE rd.po_id IN ({_PURGEABLE_POS}))
        """,
    )
    run("receive_drafts", f"DELETE FROM receive_drafts WHERE po_id IN ({_PURGEABLE_POS})")
    run(
        "receive_line_items",
        f"""
        DELETE FROM receive_line_items
        WHERE po_line_item_id IN ({_PURGEABLE_PO_LINES})
           OR receive_record_id IN (SELECT rr.id FROM receive_records rr WHERE rr.po_id IN ({_PURGEABLE_POS}))
        """,
    )
    run("receive_records", f"DELETE FROM receive_records WHERE po_id IN ({_PURGEABLE_POS})")
    run("po_documents", f"DELETE FROM po_documents WHERE po_id IN ({_PURGEABLE_POS})")
    run("po_document_data", f"DELETE FROM po_document_data WHERE po_id IN ({_PURGEABLE_POS})")
    run("po_line_items", f"DELETE FROM po_line_items WHERE po_id IN ({_PURGEABLE_POS})")
    run("purchase_orders", f"DELETE FROM purchase_orders WHERE id IN ({_PURGEABLE_POS})")

    run("gp_po_sync_state", "DELETE FROM gp_po_sync_state WHERE company = :company")

    for table in _PROJECT_BOOKKEEPING_TABLES:
        run(table, f"DELETE FROM {table} WHERE project_id IN ({_PURGEABLE_PROJECTS})")
    run("projects", f"DELETE FROM projects WHERE id IN ({_PURGEABLE_PROJECTS})")

    run(
        "warehouses",
        f"DELETE FROM warehouses AS w WHERE w.company = :company{_PURGEABLE_WAREHOUSES}",
    )
    run("inventory_item_types", "DELETE FROM inventory_item_types WHERE company = :company")
    run("shipment_methods", "DELETE FROM shipment_methods WHERE company = :company")
    run("manufacturer_vendor_map", "DELETE FROM manufacturer_vendor_map WHERE gp_company = :company")

    _report_left_behind(conn)
    return counts


def _report_left_behind(conn) -> None:
    """Name every TUCSH row the rules above refused to delete, so the deploy log says what is still
    there and why rather than leaving it to be discovered."""
    for po_id, po_number in conn.execute(
        sa.text(
            """
            SELECT po.id, po.po_number FROM purchase_orders po
            WHERE po.company = :company OR po.gp_company = :company
            ORDER BY po.po_number NULLS LAST
            """
        ).bindparams(company=COMPANY)
    ):
        print(f"purge {COMPANY}: purchase_orders LEFT {po_id} ({po_number or 'no PO number'}) - inventory credited")

    for project_uuid, job_number in conn.execute(
        sa.text(
            "SELECT p.id, p.project_id FROM projects p WHERE p.company = :company ORDER BY p.project_id"
        ).bindparams(company=COMPANY)
    ):
        print(f"purge {COMPANY}: projects LEFT {project_uuid} (job {job_number}) - dependents remain")

    # Whatever is still here after the delete above is here because something references it.
    for warehouse_id, name in conn.execute(
        sa.text("SELECT w.id, w.name FROM warehouses w WHERE w.company = :company ORDER BY w.code").bindparams(
            company=COMPANY
        )
    ):
        print(f"purge {COMPANY}: warehouses LEFT {warehouse_id} ({name}) - stock or receiving references it")


def upgrade() -> None:
    if context.is_offline_mode():
        # What this migration deletes is decided by reading the database - which POs still hold
        # inventory, which projects are bare. An offline render has no connection to read, so there
        # is no statement list to emit.
        print(f"purge {COMPANY}: offline mode, nothing rendered - this migration reads before it deletes")
        return
    purge(op.get_bind())


def downgrade() -> None:
    """No-op. The rows are gone by an executive decision, not by an error, and nothing recorded what
    they held - there is nothing to restore."""
