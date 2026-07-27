"""Inventory reservations at request creation (#342)

Revision ID: 062
Revises: 061
Create Date: 2026-07-26

Creating a shop-assembly or shipping-out request now RESERVES the hardware it needs, so

    available = on-hand - deficient - active reservations

The creator is held to what is genuinely free at creation time (they refine the selection when it
does not fit); accept becomes a pure human gate with no inventory re-check; and approving the pull
consumes the claim and deducts FIFO in one transaction. That kills the accept-vs-pull TOCTOU race
and the "blocked pull waiting on backfill" limbo for normal requests.

`inventory_reservations` is aggregate-level - (project, hardware_category, product_code) - and
deliberately carries no opening, no leaf, and no `inventory_location_id`. A hinge is a hinge
(docs/HARDWARE_IDENTITY_LIFECYCLE.md), and pinning a claim to specific rows would fight the FIFO
deduction, which is unchanged: the reservation governs *how much* is free, never *which* row.

Also here: `integrity_note` on both request tables. One nullable message, two writers, because the
acceptor's question is the same either way - "can I still trust this request?". A `replace_schedule`
re-upload landing under an in-flight request writes one; so does this migration's backfill when it
cannot cover a request.

## Backfill policy

Existing in-flight requests were created before reservations existed, so they hold no claim. Left
alone, the first request created after this migration would reserve stock the older ones are already
counting on, and the older pull would come up short at approval - exactly the failure the slice
removes. So they are backfilled, **oldest first** (the queue everybody already understands):

- A shop-assembly request is in flight when it is PENDING, or APPROVED while the PullRequest it
  minted (matched on the shared, unique `request_number`) is still PENDING. A shipping-out request,
  the same, via `pull_request_id`. Once the pull is IN_PROGRESS or COMPLETED the inventory has
  already moved and there is nothing left to reserve.
- Shipping-out OPENING_ITEM lines reserve nothing - an assembled leaf left fungible inventory when
  it was built.
- Where the remaining stock covers a request, its reservation is written and it behaves from now on
  exactly like one created after this slice.
- Where it does not, **nothing partial is written** and the request is flagged via `integrity_note`.
  A half-reservation would be the worst of both: it reads as covered while the pull is still short.
  Flagged-and-unreserved is honest - the request keeps the pre-#342 behaviour (its pull can come up
  short and go to PO backfill) and the acceptor is told so before they act on it.

Downgrade drops the table and both columns. Verified against a live cluster holding reservation rows
and flagged requests, not just an empty schema - the drop is unconditional, so the claims simply
cease to exist and availability reverts to on-hand minus deficient, which is what the pre-#342 code
computes.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

_TABLE = "inventory_reservations"

_BACKFILL_NOTE = (
    "Created before inventory reservations existed, and stock could not cover it at the time of "
    "the upgrade, so it holds no reservation. Its pull can still come up short."
)


def upgrade() -> None:
    reservation_source = postgresql.ENUM(
        "SHOP_ASSEMBLY_REQUEST",
        "SHIPPING_OUT_REQUEST",
        name="reservation_source",
        create_type=False,
    )
    reservation_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("source", reservation_source, nullable=False),
        sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=True),
        sa.Column("shipping_out_request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["shop_assembly_request_id"], ["shop_assembly_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shipping_out_request_id"], ["shipping_out_requests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 1", name="ck_inventory_reservations_quantity_positive"),
        sa.CheckConstraint(
            "(source = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
            "AND shipping_out_request_id IS NULL) "
            "OR (source = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
            "AND shop_assembly_request_id IS NULL)",
            name="ck_inventory_reservations_source_matches_request",
        ),
    )
    op.create_index(
        "ix_inventory_reservations_project_combo",
        _TABLE,
        ["project_id", "hardware_category", "product_code"],
    )
    op.create_index("ix_inventory_reservations_shop_assembly_request", _TABLE, ["shop_assembly_request_id"])
    op.create_index("ix_inventory_reservations_shipping_out_request", _TABLE, ["shipping_out_request_id"])

    op.add_column("shop_assembly_requests", sa.Column("integrity_note", sa.String(length=500), nullable=True))
    op.add_column("shipping_out_requests", sa.Column("integrity_note", sa.String(length=500), nullable=True))

    _backfill_reservations()


def _backfill_reservations() -> None:
    """Reserve for existing in-flight requests where stock allows; flag them where it does not."""
    conn = op.get_bind()

    # (created_at, kind, request_id, project_id) for every in-flight request, oldest first. Ordering
    # is what makes the outcome deterministic and defensible: the queue the warehouse already works.
    in_flight = conn.execute(
        sa.text(
            """
            SELECT sar.created_at AS created_at,
                   'SHOP_ASSEMBLY_REQUEST' AS kind,
                   sar.id AS request_id,
                   sar.project_id AS project_id
              FROM shop_assembly_requests sar
              LEFT JOIN pull_requests pr ON pr.request_number = sar.request_number
             WHERE sar.status = 'PENDING'
                OR (sar.status = 'APPROVED' AND (pr.id IS NULL OR pr.status = 'PENDING'))
            UNION ALL
            SELECT sor.created_at, 'SHIPPING_OUT_REQUEST', sor.id, sor.project_id
              FROM shipping_out_requests sor
              LEFT JOIN pull_requests pr ON pr.id = sor.pull_request_id
             WHERE sor.status = 'PENDING'
                OR (sor.status = 'APPROVED' AND (pr.id IS NULL OR pr.status = 'PENDING'))
             ORDER BY created_at, request_id
            """
        )
    ).fetchall()
    if not in_flight:
        return

    sa_demand = sa.text(
        """
        SELECT saoi.hardware_category AS hardware_category,
               saoi.product_code AS product_code,
               SUM(saoi.quantity) AS quantity
          FROM shop_assembly_opening_items saoi
          JOIN shop_assembly_openings sao ON sao.id = saoi.shop_assembly_opening_id
         WHERE sao.shop_assembly_request_id = :request_id
         GROUP BY saoi.hardware_category, saoi.product_code
        """
    )
    # OPENING_ITEM lines are excluded: the assembled leaf ships as itself and claims no loose stock.
    so_demand = sa.text(
        """
        SELECT hardware_category, product_code, SUM(requested_quantity) AS quantity
          FROM shipping_out_request_items
         WHERE shipping_out_request_id = :request_id
           AND item_type = 'LOOSE'
           AND hardware_category IS NOT NULL
           AND product_code IS NOT NULL
         GROUP BY hardware_category, product_code
        """
    )
    available_sql = sa.text(
        """
        SELECT COALESCE(SUM(quantity - deficient_quantity), 0)
          FROM inventory_locations
         WHERE project_id = :project_id
           AND hardware_category = :hardware_category
           AND product_code = :product_code
        """
    )
    reserved_sql = sa.text(
        """
        SELECT COALESCE(SUM(quantity), 0)
          FROM inventory_reservations
         WHERE project_id = :project_id
           AND hardware_category = :hardware_category
           AND product_code = :product_code
        """
    )
    insert_sql = sa.text(
        """
        INSERT INTO inventory_reservations
            (id, project_id, hardware_category, product_code, quantity, source,
             shop_assembly_request_id, shipping_out_request_id, created_at)
        VALUES (gen_random_uuid(), :project_id, :hardware_category, :product_code, :quantity, :source,
                :sa_request_id, :so_request_id, NOW())
        """
    )

    for row in in_flight:
        kind = row.kind
        demand = conn.execute(
            sa_demand if kind == "SHOP_ASSEMBLY_REQUEST" else so_demand,
            {"request_id": row.request_id},
        ).fetchall()
        if not demand:
            continue

        covered = True
        for line in demand:
            params = {
                "project_id": row.project_id,
                "hardware_category": line.hardware_category,
                "product_code": line.product_code,
            }
            on_hand = conn.execute(available_sql, params).scalar() or 0
            reserved = conn.execute(reserved_sql, params).scalar() or 0
            if on_hand - reserved < line.quantity:
                covered = False
                break

        if not covered:
            table = "shop_assembly_requests" if kind == "SHOP_ASSEMBLY_REQUEST" else "shipping_out_requests"
            conn.execute(
                sa.text(f"UPDATE {table} SET integrity_note = :note WHERE id = :id"),
                {"note": _BACKFILL_NOTE, "id": row.request_id},
            )
            continue

        for line in demand:
            conn.execute(
                insert_sql,
                {
                    "project_id": row.project_id,
                    "hardware_category": line.hardware_category,
                    "product_code": line.product_code,
                    "quantity": int(line.quantity),
                    "source": kind,
                    "sa_request_id": row.request_id if kind == "SHOP_ASSEMBLY_REQUEST" else None,
                    "so_request_id": row.request_id if kind == "SHIPPING_OUT_REQUEST" else None,
                },
            )


def downgrade() -> None:
    op.drop_column("shipping_out_requests", "integrity_note")
    op.drop_column("shop_assembly_requests", "integrity_note")

    op.drop_index("ix_inventory_reservations_shipping_out_request", table_name=_TABLE)
    op.drop_index("ix_inventory_reservations_shop_assembly_request", table_name=_TABLE)
    op.drop_index("ix_inventory_reservations_project_combo", table_name=_TABLE)
    op.drop_table(_TABLE)
    op.execute("DROP TYPE IF EXISTS reservation_source")
