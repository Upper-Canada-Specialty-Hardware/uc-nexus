"""v1 stops managing doors as objects

Revision ID: 091
Revises: 090
Create Date: 2026-08-09

The door stops being a thing the system owns and becomes a label: demand attribution before
inventory, a text tag after it. Hardware exits through pull completion - shop assembly as one
terminal exit, shipping out as the other - and nothing downstream of receiving carries a door leaf.

What that costs, structurally:

- `opening_items` / `opening_item_hardware` go. The assembled leaf was the only object that made
  hardware stop being fungible mid-pipeline, and with bench work untracked there is nothing to
  materialize it from.
- `shop_assembly_openings` / `shop_assembly_opening_items` go. A shop-assembly request was a
  request -> openings -> items tree so that per-leaf review, assignment and progress had somewhere
  to live; all three are gone, so the tree collapses to `shop_assembly_request_items`, flat, with
  `opening_number` as a tag. Grouping by that tag is a UI concern from here on.
- `item_type` / `opening_item_id` / `leaf` come off every line table that carried them
  (`pull_request_items`, `shipping_out_request_items`, `packing_slip_items`,
  `shipment_container_items`). With one item type left there is nothing to discriminate, and OPENING_ITEM
  rows name a table that no longer exists - they are deleted, not converted, because the loose
  hardware they stood for left inventory at assembly and re-crediting it would invent stock.
- `pull_request_items.fetched_at` / `fetched_by` go with them. The fetch check-off was the
  OPENING_ITEM affordance - walk to the rack and collect an already-tagged leaf - and every
  remaining line is picked by quantity instead.
- `inventory_reservations` loses REPLACEMENT_PULL and `pull_request_id`. Replacements are ordinary
  new request lines now, so every claim has a request behind it again and the check constraint goes
  back to two-way.

`shop_assembly_requests` gains `pull_request_id`, which it needs for the same reason
`shipping_out_requests` always had one: the openings that used to carry the link to the minted pull
are gone, so the request has to hold it directly.

Existing shop-assembly requests are flattened rather than dropped - `shop_assembly_opening_items`
summed per (request, opening_number, category, product) is exactly the flat line the new table
wants, and the pull link is lifted off any one of the request's openings.

Downgrade rebuilds every table, column, index, constraint and enum type this removes. It cannot
bring the rows back: an assembled leaf is not derivable from the tag that replaced it, and the
per-leaf review, assignment and progress state was never recorded anywhere else. The schema is
restored exactly, which is what the migration-integrity job checks.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None

_RESERVATIONS = "inventory_reservations"
_SOURCE_CHECK = "ck_inventory_reservations_source_matches_request"
_RES_PULL_FK = "fk_inventory_reservations_pull_request"
_RES_PULL_INDEX = "ix_inventory_reservations_pull_request"

_TWO_WAY_SOURCE = (
    "(source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
    "AND shipping_out_request_id IS NULL) "
    "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL)"
)
_THREE_WAY_SOURCE = (
    "(source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
    "AND shipping_out_request_id IS NULL AND pull_request_id IS NULL) "
    "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL AND pull_request_id IS NULL) "
    "OR (source::text = 'REPLACEMENT_PULL' AND pull_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL AND shipping_out_request_id IS NULL)"
)

# Every table that discriminated its lines by PullRequestItemType: (table, index over its
# opening_items FK if it had one, explicit FK name if the FK was ever created with one).
#
# `pull_request_items` is the odd one out on both counts. Its FK to opening_items was added after the
# fact, by name, because opening_items did not exist yet when the table was created - and 005's
# downgrade drops it by that name, so restoring it under any other name would break the way back.
_TYPED_LINE_TABLES = (
    ("pull_request_items", "ix_pull_request_items_opening_item", "fk_pull_request_items_opening_item_id"),
    ("shipping_out_request_items", "ix_shipping_out_request_items_opening_item", None),
    ("packing_slip_items", None, None),
    ("shipment_container_items", "ix_shipment_container_items_opening_item", None),
)


def upgrade() -> None:
    _flatten_shop_assembly_requests()
    _strip_line_item_types()
    _narrow_reservations()

    op.drop_table("shop_assembly_opening_items")
    op.drop_table("shop_assembly_openings")
    op.drop_table("opening_item_hardware")
    op.drop_table("opening_items")

    for enum_name in (
        "pull_request_item_type",
        "opening_item_state",
        "opening_review_status",
        "pull_status",
        "assembly_status",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")


def _flatten_shop_assembly_requests() -> None:
    """Collapse request -> openings -> items into flat request lines."""
    op.add_column("shop_assembly_requests", sa.Column("pull_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_shop_assembly_requests_pull_request",
        "shop_assembly_requests",
        "pull_requests",
        ["pull_request_id"],
        ["id"],
    )

    op.create_table(
        "shop_assembly_request_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=True),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["shop_assembly_request_id"], ["shop_assembly_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 1", name="ck_shop_assembly_request_items_quantity_positive"),
        sa.CheckConstraint(
            "allocated_quantity >= 0 AND allocated_quantity <= quantity",
            name="ck_shop_assembly_request_items_allocated_within_quantity",
        ),
    )
    op.create_index(
        "ix_shop_assembly_request_items_request",
        "shop_assembly_request_items",
        ["shop_assembly_request_id"],
    )

    # Any of the request's openings will do: the accept minted one pull for the whole request and
    # pointed every opening at it.
    op.execute(
        """
        UPDATE shop_assembly_requests r
        SET pull_request_id = sub.pull_request_id
        FROM (
            SELECT DISTINCT ON (shop_assembly_request_id)
                   shop_assembly_request_id, pull_request_id
              FROM shop_assembly_openings
             WHERE shop_assembly_request_id IS NOT NULL AND pull_request_id IS NOT NULL
             ORDER BY shop_assembly_request_id, pull_request_id
        ) sub
        WHERE sub.shop_assembly_request_id = r.id
        """
    )

    op.execute(
        """
        INSERT INTO shop_assembly_request_items
            (id, shop_assembly_request_id, opening_number, hardware_category, product_code,
             quantity, allocated_quantity)
        SELECT gen_random_uuid(),
               sao.shop_assembly_request_id,
               sao.opening_number,
               saoi.hardware_category,
               saoi.product_code,
               SUM(saoi.quantity),
               SUM(saoi.allocated_quantity)
          FROM shop_assembly_opening_items saoi
          JOIN shop_assembly_openings sao ON sao.id = saoi.shop_assembly_opening_id
         WHERE sao.shop_assembly_request_id IS NOT NULL
         GROUP BY sao.shop_assembly_request_id, sao.opening_number,
                  saoi.hardware_category, saoi.product_code
        HAVING SUM(saoi.quantity) >= 1
        """
    )


def _strip_line_item_types() -> None:
    """Drop the LOOSE/OPENING_ITEM discriminator and everything that only OPENING_ITEM lines used."""
    for table, opening_item_index, _fk_name in _TYPED_LINE_TABLES:
        # An OPENING_ITEM row names an assembled leaf that is about to stop existing. It cannot
        # become a loose line: its hardware left fungible inventory when the leaf was built, so
        # converting it would re-credit stock that is physically on a door.
        op.execute(f"DELETE FROM {table} WHERE item_type::text = 'OPENING_ITEM'")
        if opening_item_index is not None:
            op.drop_index(opening_item_index, table_name=table)
        op.drop_column(table, "item_type")
        op.drop_column(table, "opening_item_id")
        op.drop_column(table, "leaf")

    op.drop_index("ix_pull_request_items_sa_opening_item", table_name="pull_request_items")
    op.drop_column("pull_request_items", "sa_opening_item_id")
    op.drop_column("pull_request_items", "fetched_at")
    op.drop_column("pull_request_items", "fetched_by")

    # Nullable only because an OPENING_ITEM line named a leaf instead of a product. Every surviving
    # line is loose hardware, so both are facts about it.
    for table in ("pull_request_items", "shipping_out_request_items"):
        op.execute(f"DELETE FROM {table} WHERE hardware_category IS NULL OR product_code IS NULL")
        op.alter_column(table, "hardware_category", existing_type=sa.String(), nullable=False)
        op.alter_column(table, "product_code", existing_type=sa.String(), nullable=False)


def _narrow_reservations() -> None:
    """Replacements are ordinary request lines now, so every claim has a request behind it again."""
    op.drop_constraint(_SOURCE_CHECK, _RESERVATIONS, type_="check")
    op.execute(f"DELETE FROM {_RESERVATIONS} WHERE source::text = 'REPLACEMENT_PULL'")
    op.drop_index(_RES_PULL_INDEX, table_name=_RESERVATIONS)
    op.drop_constraint(_RES_PULL_FK, _RESERVATIONS, type_="foreignkey")
    op.drop_column(_RESERVATIONS, "pull_request_id")

    # PostgreSQL cannot drop a label from an enum type, so the type is rebuilt around the column.
    op.execute("ALTER TYPE reservation_source RENAME TO reservation_source_old")
    op.execute("CREATE TYPE reservation_source AS ENUM ('SHOP_ASSEMBLY_REQUEST', 'SHIPPING_OUT_REQUEST')")
    op.execute(
        f"ALTER TABLE {_RESERVATIONS} ALTER COLUMN source TYPE reservation_source "
        "USING source::text::reservation_source"
    )
    op.execute("DROP TYPE reservation_source_old")

    op.create_check_constraint(_SOURCE_CHECK, _RESERVATIONS, _TWO_WAY_SOURCE)


def downgrade() -> None:
    opening_item_state = postgresql.ENUM(
        "IN_INVENTORY", "SHIP_READY", "SHIPPED_OUT", name="opening_item_state", create_type=False
    )
    pull_status = postgresql.ENUM("NOT_PULLED", "PARTIAL", "PULLED", name="pull_status", create_type=False)
    assembly_status = postgresql.ENUM("PENDING", "IN_PROGRESS", "COMPLETED", name="assembly_status", create_type=False)
    opening_review_status = postgresql.ENUM(
        "PENDING", "ACCEPTED", "REJECTED", "DEFERRED", name="opening_review_status", create_type=False
    )
    pull_request_item_type = postgresql.ENUM("LOOSE", "OPENING_ITEM", name="pull_request_item_type", create_type=False)
    for enum_type in (
        opening_item_state,
        pull_status,
        assembly_status,
        opening_review_status,
        pull_request_item_type,
    ):
        enum_type.create(op.get_bind(), checkfirst=True)

    _restore_opening_items(opening_item_state)
    _restore_shop_assembly_openings(pull_status, assembly_status, opening_review_status)
    _restore_line_item_types(pull_request_item_type)
    _widen_reservations()

    op.drop_index("ix_shop_assembly_request_items_request", table_name="shop_assembly_request_items")
    op.drop_table("shop_assembly_request_items")
    op.drop_constraint("fk_shop_assembly_requests_pull_request", "shop_assembly_requests", type_="foreignkey")
    op.drop_column("shop_assembly_requests", "pull_request_id")


def _restore_opening_items(opening_item_state: postgresql.ENUM) -> None:
    op.create_table(
        "opening_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("opening_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column("floor", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("leaf", sa.SmallInteger(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("assembly_completed_at", sa.DateTime(), nullable=False),
        sa.Column("state", opening_item_state, nullable=False),
        sa.Column("aisle", sa.String(), nullable=True),
        sa.Column("row", sa.String(), nullable=True),
        sa.Column("bay", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 1", name="ck_opening_items_quantity_positive"),
    )
    op.create_index("ix_opening_items_project_state", "opening_items", ["project_id", "state"])
    op.create_index("ix_opening_items_opening_id", "opening_items", ["opening_id"])
    op.create_index("ix_opening_items_warehouse", "opening_items", ["warehouse_id", "aisle", "row", "bay"])
    op.execute(
        "CREATE UNIQUE INDEX uq_opening_items_live_leaf ON opening_items "
        "(project_id, opening_id, coalesce(leaf, 0)) WHERE state <> 'SHIPPED_OUT'"
    )

    op.create_table(
        "opening_item_hardware",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("opening_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["opening_item_id"], ["opening_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 1", name="ck_opening_item_hardware_quantity_positive"),
    )
    op.create_index("ix_opening_item_hardware_opening_item", "opening_item_hardware", ["opening_item_id"])


def _restore_shop_assembly_openings(
    pull_status: postgresql.ENUM,
    assembly_status: postgresql.ENUM,
    opening_review_status: postgresql.ENUM,
) -> None:
    op.create_table(
        "shop_assembly_openings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_request_id", sa.Uuid(), nullable=True),
        sa.Column("pull_request_id", sa.Uuid(), nullable=True),
        sa.Column("opening_id", sa.Uuid(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column("floor", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("leaf", sa.SmallInteger(), nullable=True),
        sa.Column("pull_status", pull_status, nullable=False),
        sa.Column("staged_at", sa.DateTime(), nullable=True),
        sa.Column("staged_by", sa.String(), nullable=True),
        sa.Column("assigned_to_user_id", sa.String(), nullable=True),
        sa.Column("assigned_to", sa.String(), nullable=True),
        sa.Column("assembly_status", assembly_status, nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("review_status", opening_review_status, nullable=False, server_default="PENDING"),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("review_reason", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["shop_assembly_request_id"], ["shop_assembly_requests.id"]),
        sa.ForeignKeyConstraint(["pull_request_id"], ["pull_requests.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "pull_status IN ('NOT_PULLED', 'PULLED')",
            name="ck_shop_assembly_openings_pull_status_binary",
        ),
    )
    op.create_index("ix_shop_assembly_openings_request", "shop_assembly_openings", ["shop_assembly_request_id"])
    op.create_index("ix_shop_assembly_openings_pull_request", "shop_assembly_openings", ["pull_request_id"])
    op.create_index("ix_shop_assembly_openings_review_status", "shop_assembly_openings", ["review_status"])
    op.create_index(
        "ix_shop_assembly_openings_opening_pull",
        "shop_assembly_openings",
        ["opening_id", "pull_status"],
    )

    op.create_table(
        "shop_assembly_opening_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_assembly_opening_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("allocated_quantity", sa.Integer(), nullable=False),
        sa.Column("installed_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deficient_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("replacement_pending_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["shop_assembly_opening_id"], ["shop_assembly_openings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("quantity >= 1", name="ck_shop_assembly_opening_items_quantity_positive"),
        sa.CheckConstraint(
            "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
            "AND allocated_quantity >= 0 AND allocated_quantity <= quantity "
            "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= allocated_quantity",
            name="ck_shop_assembly_opening_items_progress_within_quantity",
        ),
    )
    op.create_index(
        "ix_shop_assembly_opening_items_opening",
        "shop_assembly_opening_items",
        ["shop_assembly_opening_id"],
    )
    op.execute(
        "CREATE INDEX ix_shop_assembly_opening_items_replacement_pending "
        "ON shop_assembly_opening_items (shop_assembly_opening_id) WHERE replacement_pending_quantity > 0"
    )


def _restore_line_item_types(pull_request_item_type: postgresql.ENUM) -> None:
    for table, opening_item_index, fk_name in _TYPED_LINE_TABLES:
        op.add_column(
            table,
            sa.Column("item_type", pull_request_item_type, nullable=False, server_default="LOOSE"),
        )
        op.alter_column(table, "item_type", server_default=None)
        if fk_name is None:
            # Anonymous, exactly as the create_table that first declared it left things - these
            # tables are dropped whole on the way further down, so the generated name is never named.
            op.add_column(
                table,
                sa.Column("opening_item_id", sa.Uuid(), sa.ForeignKey("opening_items.id"), nullable=True),
            )
        else:
            op.add_column(table, sa.Column("opening_item_id", sa.Uuid(), nullable=True))
            op.create_foreign_key(fk_name, table, "opening_items", ["opening_item_id"], ["id"])
        op.add_column(table, sa.Column("leaf", sa.SmallInteger(), nullable=True))
        if opening_item_index is not None:
            op.create_index(opening_item_index, table, ["opening_item_id"])

    op.add_column(
        "pull_request_items",
        sa.Column(
            "sa_opening_item_id",
            sa.Uuid(),
            sa.ForeignKey("shop_assembly_opening_items.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_pull_request_items_sa_opening_item", "pull_request_items", ["sa_opening_item_id"])
    op.add_column("pull_request_items", sa.Column("fetched_at", sa.DateTime(), nullable=True))
    op.add_column("pull_request_items", sa.Column("fetched_by", sa.String(), nullable=True))

    for table in ("pull_request_items", "shipping_out_request_items"):
        op.alter_column(table, "hardware_category", existing_type=sa.String(), nullable=True)
        op.alter_column(table, "product_code", existing_type=sa.String(), nullable=True)


def _widen_reservations() -> None:
    op.execute("ALTER TYPE reservation_source ADD VALUE IF NOT EXISTS 'REPLACEMENT_PULL'")

    op.drop_constraint(_SOURCE_CHECK, _RESERVATIONS, type_="check")
    op.add_column(_RESERVATIONS, sa.Column("pull_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        _RES_PULL_FK,
        _RESERVATIONS,
        "pull_requests",
        ["pull_request_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(_RES_PULL_INDEX, _RESERVATIONS, ["pull_request_id"])
    # `source::text` for the same reason 071 needed it: the label above was added in this
    # transaction, and validating a constraint that compares the enum directly would use it.
    op.create_check_constraint(_SOURCE_CHECK, _RESERVATIONS, _THREE_WAY_SOURCE)
