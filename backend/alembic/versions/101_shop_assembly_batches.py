"""Shop-assembly batching: openings, batches, batch-held reservations (#646/#643/#644)

Revision ID: 101
Revises: 100
Create Date: 2026-08-31

A shop-assembly request stops being a composed pull and becomes a flag the PM raises over openings.
Allocation moves to the Shop Assembly Manager, who works the request in batches, so this adds:

  shop_assembly_request_openings  per-opening state (PENDING / BATCHED / DISMISSED)
  shop_assembly_batches           one dispatch, carrying the pull it minted
  shop_assembly_batch_items       what that dispatch allocated per line

and moves two things that used to hang off the request itself. `shop_assembly_request_items.quantity`
becomes `requested_quantity` and loses `allocated_quantity` (nothing is allocated at creation), and
`inventory_reservations` swaps its SHOP_ASSEMBLY_REQUEST holder for SHOP_ASSEMBLY_BATCH - the batch
is the unit a pull cancellation releases, and a request-level holder would make cancelling one
batch's pull drop its siblings' claims.

Existing data (dev only):

  - every PENDING request keeps its lines and gains an opening row per distinct opening number, and
    its creation-time reservations are RELEASED. Those claims were minted by a gate that no longer
    exists; leaving them would hold stock behind openings nobody has decided to dispatch.
  - every APPROVED request's pull is wrapped in a backfilled batch B1, its openings are marked
    BATCHED against it, and the reservations it still holds are re-pointed at that batch so a pick
    or a cancel finds them exactly where the new code looks. The pull keeps its number: the batch
    takes `{request_number}-B1` for its own, but the already-minted pull is not renamed, because
    renaming a live pick sheet under the warehouse would be worse than a batch number that does not
    match one legacy row.
  - REJECTED requests get opening rows marked DISMISSED - they were never worked, and PENDING would
    put them back on a board they left.

Downgrade rebuilds `pull_request_id` on the request from its first batch, restores the two item
columns (allocated = requested, the pre-#342 all-or-nothing reading), re-points reservations at the
request and drops the three tables.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


_OPENING_STATUS_ENUM = "shop_assembly_opening_status"
_BATCH_STATUS_ENUM = "shop_assembly_batch_status"


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. the three new tables -------------------------------------------------------------
    # The enum types are created by the create_table that first names them, which is why the batch
    # table is built before the openings table that references it either way.
    op.create_table(
        "shop_assembly_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "CANCELLED", name=_BATCH_STATUS_ENUM), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("pull_request_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["shop_assembly_request_id"], ["shop_assembly_requests.id"]),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_number"),
        sa.UniqueConstraint("shop_assembly_request_id", "sequence", name="uq_shop_assembly_batches_request_sequence"),
        sa.CheckConstraint("sequence >= 1", name="ck_shop_assembly_batches_sequence_positive"),
    )
    op.create_index("ix_shop_assembly_batches_request", "shop_assembly_batches", ["shop_assembly_request_id"])
    op.create_index("ix_shop_assembly_batches_pull_request", "shop_assembly_batches", ["pull_request_id"])

    op.create_table(
        "shop_assembly_batch_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_batch_id", sa.Uuid(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["shop_assembly_batch_id"], ["shop_assembly_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("allocated_quantity >= 1", name="ck_shop_assembly_batch_items_allocated_positive"),
    )
    op.create_index("ix_shop_assembly_batch_items_batch", "shop_assembly_batch_items", ["shop_assembly_batch_id"])

    op.create_table(
        "shop_assembly_request_openings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "BATCHED", "DISMISSED", name=_OPENING_STATUS_ENUM), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("dismissed_by", sa.String(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("dismissal_reason", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["shop_assembly_request_id"], ["shop_assembly_requests.id"]),
        sa.ForeignKeyConstraint(["batch_id"], ["shop_assembly_batches.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_assembly_request_id",
            "opening_number",
            name="uq_shop_assembly_request_openings_request_opening",
        ),
    )
    op.create_index(
        "ix_shop_assembly_request_openings_request",
        "shop_assembly_request_openings",
        ["shop_assembly_request_id"],
    )
    op.create_index("ix_shop_assembly_request_openings_batch", "shop_assembly_request_openings", ["batch_id"])

    # --- 2. request items: quantity -> requested_quantity, allocated_quantity dropped ----------
    op.drop_constraint(
        "ck_shop_assembly_request_items_allocated_within_quantity",
        "shop_assembly_request_items",
        type_="check",
    )
    op.drop_constraint(
        "ck_shop_assembly_request_items_quantity_positive",
        "shop_assembly_request_items",
        type_="check",
    )
    op.drop_column("shop_assembly_request_items", "allocated_quantity")
    op.alter_column("shop_assembly_request_items", "quantity", new_column_name="requested_quantity")
    op.create_check_constraint(
        "ck_shop_assembly_request_items_quantity_positive",
        "shop_assembly_request_items",
        "requested_quantity >= 1",
    )

    # --- 3. backfill batches + opening rows off what exists ------------------------------------
    now = datetime.utcnow()
    requests = conn.execute(
        sa.text("SELECT id, request_number, status, pull_request_id, approved_by FROM shop_assembly_requests")
    ).all()
    openings_by_request = {}
    for request_id, opening_number in conn.execute(
        sa.text(
            "SELECT DISTINCT shop_assembly_request_id, opening_number FROM shop_assembly_request_items "
            "WHERE opening_number IS NOT NULL"
        )
    ).all():
        openings_by_request.setdefault(request_id, []).append(opening_number)

    batch_rows = []
    batch_item_rows = []
    opening_rows = []
    # request id -> backfilled batch id, for the reservation re-point below.
    batch_by_request = {}

    for request_id, request_number, status, pull_request_id, approved_by in requests:
        batch_id = None
        if status == "APPROVED" and pull_request_id is not None:
            batch_id = uuid.uuid4()
            batch_by_request[request_id] = batch_id
            batch_rows.append(
                {
                    "id": batch_id,
                    "shop_assembly_request_id": request_id,
                    "sequence": 1,
                    "batch_number": f"{request_number}-B1",
                    "status": "ACTIVE",
                    "created_by": approved_by or "Migration",
                    "created_at": now,
                    "pull_request_id": pull_request_id,
                }
            )
            # The batch's lines are the pull's, which is the record of what was actually dispatched.
            for opening_number, category, code, quantity in conn.execute(
                sa.text(
                    "SELECT opening_number, hardware_category, product_code, requested_quantity "
                    "FROM pull_request_items WHERE pull_request_id = :pid AND requested_quantity >= 1"
                ),
                {"pid": pull_request_id},
            ).all():
                batch_item_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "shop_assembly_batch_id": batch_id,
                        "opening_number": opening_number or "",
                        "hardware_category": category,
                        "product_code": code,
                        "allocated_quantity": quantity,
                    }
                )

        if status == "APPROVED":
            opening_status = "BATCHED" if batch_id is not None else "DISMISSED"
        elif status == "REJECTED":
            opening_status = "DISMISSED"
        else:
            opening_status = "PENDING"

        for opening_number in openings_by_request.get(request_id, []):
            opening_rows.append(
                {
                    "id": uuid.uuid4(),
                    "shop_assembly_request_id": request_id,
                    "opening_number": opening_number,
                    "status": opening_status,
                    "batch_id": batch_id if opening_status == "BATCHED" else None,
                    "dismissed_by": None,
                    "dismissed_at": now if opening_status == "DISMISSED" else None,
                    "dismissal_reason": (
                        "Carried over when shop-assembly batching was introduced."
                        if opening_status == "DISMISSED"
                        else None
                    ),
                }
            )

    if batch_rows:
        op.bulk_insert(
            sa.table(
                "shop_assembly_batches",
                sa.column("id", sa.Uuid()),
                sa.column("shop_assembly_request_id", sa.Uuid()),
                sa.column("sequence", sa.Integer()),
                sa.column("batch_number", sa.String()),
                sa.column("status", sa.String()),
                sa.column("created_by", sa.String()),
                sa.column("created_at", sa.DateTime()),
                sa.column("pull_request_id", sa.Uuid()),
            ),
            batch_rows,
        )
    if batch_item_rows:
        op.bulk_insert(
            sa.table(
                "shop_assembly_batch_items",
                sa.column("id", sa.Uuid()),
                sa.column("shop_assembly_batch_id", sa.Uuid()),
                sa.column("opening_number", sa.String()),
                sa.column("hardware_category", sa.String()),
                sa.column("product_code", sa.String()),
                sa.column("allocated_quantity", sa.Integer()),
            ),
            batch_item_rows,
        )
    if opening_rows:
        op.bulk_insert(
            sa.table(
                "shop_assembly_request_openings",
                sa.column("id", sa.Uuid()),
                sa.column("shop_assembly_request_id", sa.Uuid()),
                sa.column("opening_number", sa.String()),
                sa.column("status", sa.String()),
                sa.column("batch_id", sa.Uuid()),
                sa.column("dismissed_by", sa.String()),
                sa.column("dismissed_at", sa.DateTime()),
                sa.column("dismissal_reason", sa.String()),
            ),
            opening_rows,
        )

    # --- 4. reservations: holder moves from the request to the batch ---------------------------
    op.add_column("inventory_reservations", sa.Column("shop_assembly_batch_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_inventory_reservations_shop_assembly_batch",
        "inventory_reservations",
        "shop_assembly_batches",
        ["shop_assembly_batch_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_inventory_reservations_shop_assembly_batch",
        "inventory_reservations",
        ["shop_assembly_batch_id"],
    )

    # An APPROVED request's claim follows its pull onto the backfilled batch; a PENDING one's is
    # released outright, because the gate that minted it is gone and nothing pending holds stock now.
    for request_id, batch_id in batch_by_request.items():
        conn.execute(
            sa.text(
                "UPDATE inventory_reservations SET shop_assembly_batch_id = :bid "
                "WHERE source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id = :rid"
            ),
            {"bid": batch_id, "rid": request_id},
        )
    conn.execute(
        sa.text(
            "DELETE FROM inventory_reservations "
            "WHERE source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_batch_id IS NULL"
        )
    )

    # The check constraint has to go before the labels move, because it names the old one.
    op.drop_constraint("ck_inventory_reservations_source_matches_request", "inventory_reservations", type_="check")
    op.execute("ALTER TYPE reservation_source RENAME TO reservation_source_old")
    op.execute("CREATE TYPE reservation_source AS ENUM ('SHOP_ASSEMBLY_BATCH', 'SHIPPING_OUT_REQUEST')")
    op.execute(
        "ALTER TABLE inventory_reservations ALTER COLUMN source TYPE reservation_source "
        "USING replace(source::text, 'SHOP_ASSEMBLY_REQUEST', 'SHOP_ASSEMBLY_BATCH')::reservation_source"
    )
    op.execute("DROP TYPE reservation_source_old")
    op.create_check_constraint(
        "ck_inventory_reservations_source_matches_request",
        "inventory_reservations",
        "(source::text = 'SHOP_ASSEMBLY_BATCH' AND shop_assembly_batch_id IS NOT NULL "
        "AND shipping_out_request_id IS NULL) "
        "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
        "AND shop_assembly_batch_id IS NULL)",
    )
    op.drop_index("ix_inventory_reservations_shop_assembly_request", table_name="inventory_reservations")
    op.drop_column("inventory_reservations", "shop_assembly_request_id")

    # --- 5. the request's own pull link, now the batch's --------------------------------------
    op.drop_column("shop_assembly_requests", "pull_request_id")


def downgrade() -> None:
    conn = op.get_bind()

    op.add_column("shop_assembly_requests", sa.Column("pull_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_shop_assembly_requests_pull_request",
        "shop_assembly_requests",
        "pull_requests",
        ["pull_request_id"],
        ["id"],
    )
    # The pre-batching shape held ONE pull per request, so the earliest live batch's is the only
    # honest answer. A request with several batches loses the later ones' links; their pulls survive
    # untouched and are still findable by number.
    conn.execute(
        sa.text(
            "UPDATE shop_assembly_requests r SET pull_request_id = ("
            "  SELECT b.pull_request_id FROM shop_assembly_batches b "
            "  WHERE b.shop_assembly_request_id = r.id AND b.status = 'ACTIVE' "
            "  ORDER BY b.sequence LIMIT 1)"
        )
    )

    op.add_column("inventory_reservations", sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_inventory_reservations_shop_assembly_request",
        "inventory_reservations",
        "shop_assembly_requests",
        ["shop_assembly_request_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_inventory_reservations_shop_assembly_request",
        "inventory_reservations",
        ["shop_assembly_request_id"],
    )
    conn.execute(
        sa.text(
            "UPDATE inventory_reservations res SET shop_assembly_request_id = ("
            "  SELECT b.shop_assembly_request_id FROM shop_assembly_batches b "
            "  WHERE b.id = res.shop_assembly_batch_id) "
            "WHERE res.shop_assembly_batch_id IS NOT NULL"
        )
    )
    # A batch claim whose request cannot be resolved has nowhere to live in the old shape.
    conn.execute(
        sa.text(
            "DELETE FROM inventory_reservations "
            "WHERE source::text = 'SHOP_ASSEMBLY_BATCH' AND shop_assembly_request_id IS NULL"
        )
    )

    op.drop_constraint("ck_inventory_reservations_source_matches_request", "inventory_reservations", type_="check")
    op.execute("ALTER TYPE reservation_source RENAME TO reservation_source_old")
    op.execute("CREATE TYPE reservation_source AS ENUM ('SHOP_ASSEMBLY_REQUEST', 'SHIPPING_OUT_REQUEST')")
    op.execute(
        "ALTER TABLE inventory_reservations ALTER COLUMN source TYPE reservation_source "
        "USING replace(source::text, 'SHOP_ASSEMBLY_BATCH', 'SHOP_ASSEMBLY_REQUEST')::reservation_source"
    )
    op.execute("DROP TYPE reservation_source_old")
    op.create_check_constraint(
        "ck_inventory_reservations_source_matches_request",
        "inventory_reservations",
        "(source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
        "AND shipping_out_request_id IS NULL) "
        "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
        "AND shop_assembly_request_id IS NULL)",
    )
    op.drop_index("ix_inventory_reservations_shop_assembly_batch", table_name="inventory_reservations")
    op.drop_constraint("fk_inventory_reservations_shop_assembly_batch", "inventory_reservations", type_="foreignkey")
    op.drop_column("inventory_reservations", "shop_assembly_batch_id")

    op.drop_constraint(
        "ck_shop_assembly_request_items_quantity_positive",
        "shop_assembly_request_items",
        type_="check",
    )
    op.alter_column("shop_assembly_request_items", "requested_quantity", new_column_name="quantity")
    op.add_column("shop_assembly_request_items", sa.Column("allocated_quantity", sa.Integer(), nullable=True))
    # Fully allocated: the pre-composer all-or-nothing reading, and the only one that does not
    # invent a shortfall the request never had.
    conn.execute(sa.text("UPDATE shop_assembly_request_items SET allocated_quantity = quantity"))
    op.alter_column("shop_assembly_request_items", "allocated_quantity", nullable=False)
    op.create_check_constraint(
        "ck_shop_assembly_request_items_quantity_positive",
        "shop_assembly_request_items",
        "quantity >= 1",
    )
    op.create_check_constraint(
        "ck_shop_assembly_request_items_allocated_within_quantity",
        "shop_assembly_request_items",
        "allocated_quantity >= 0 AND allocated_quantity <= quantity",
    )

    op.drop_index("ix_shop_assembly_request_openings_batch", table_name="shop_assembly_request_openings")
    op.drop_index("ix_shop_assembly_request_openings_request", table_name="shop_assembly_request_openings")
    op.drop_table("shop_assembly_request_openings")
    op.drop_index("ix_shop_assembly_batch_items_batch", table_name="shop_assembly_batch_items")
    op.drop_table("shop_assembly_batch_items")
    op.drop_index("ix_shop_assembly_batches_pull_request", table_name="shop_assembly_batches")
    op.drop_index("ix_shop_assembly_batches_request", table_name="shop_assembly_batches")
    op.drop_table("shop_assembly_batches")
    # Dropping a table leaves its enum type behind, so both go explicitly.
    sa.Enum(name=_OPENING_STATUS_ENUM).drop(conn, checkfirst=True)
    sa.Enum(name=_BATCH_STATUS_ENUM).drop(conn, checkfirst=True)
