"""shipment loads: the truck trip packing slips ride on (issue #1720)

A load groups the packing slips that leave together and is named for its lead project and ship date
(`22713-10152026`, then `-2` for that project's second load the same day; `D-` in front for the demo
company). New table `shipment_loads`, and `packing_slips.load_id` pointing at it.

Backfill: every slip already there gets a load of its own, named for its project and its pickup date,
or the Toronto date it was confirmed when it has none. Nothing old is grouped - which slips shared a
truck was never recorded, so it is not guessed.

Downgrade drops the column and the table.

Revision ID: 145
Revises: 144
Create Date: 2026-10-19
"""

import uuid
from datetime import UTC
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision = "145"
down_revision = "144"
branch_labels = None
depends_on = None

_TORONTO = ZoneInfo("America/Toronto")


def upgrade() -> None:
    op.create_table(
        "shipment_loads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("load_number", sa.String(length=60), nullable=False),
        sa.Column("company", sa.String(length=15), nullable=False),
        sa.Column("lead_project_id", sa.Uuid(), nullable=False),
        sa.Column("ship_date", sa.Date(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company", "load_number", name="uq_shipment_loads_company_number"),
    )
    op.create_index("ix_shipment_loads_company_ship_date", "shipment_loads", ["company", "ship_date"])
    op.add_column("packing_slips", sa.Column("load_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("packing_slips_load_id_fkey", "packing_slips", "shipment_loads", ["load_id"], ["id"])
    op.create_index("ix_packing_slips_load", "packing_slips", ["load_id"])

    bind = op.get_bind()
    slips = bind.execute(
        sa.text(
            """
            SELECT ps.id, ps.project_id, ps.pickup_date, ps.shipped_at, ps.shipped_by,
                   p.project_id AS project_number, p.company
            FROM packing_slips ps JOIN projects p ON p.id = ps.project_id
            ORDER BY ps.shipped_at, ps.id
            """
        )
    ).all()
    loads = sa.table(
        "shipment_loads",
        sa.column("id", sa.Uuid()),
        sa.column("load_number", sa.String()),
        sa.column("company", sa.String()),
        sa.column("lead_project_id", sa.Uuid()),
        sa.column("ship_date", sa.Date()),
        sa.column("created_by", sa.String()),
        sa.column("created_at", sa.DateTime()),
    )
    seen: dict[tuple[str, str], int] = {}
    for slip in slips:
        day = slip.pickup_date or slip.shipped_at.replace(tzinfo=UTC).astimezone(_TORONTO).date()
        base = f"{slip.project_number.strip()}-{day:%m%d%Y}"
        if (slip.company or "").strip().upper() == "DEMO":
            base = f"D-{base}"
        key = (slip.company, base)
        count = seen.get(key, 0) + 1
        seen[key] = count
        load_id = uuid.uuid4()
        bind.execute(
            loads.insert().values(
                id=load_id,
                load_number=base if count == 1 else f"{base}-{count}",
                company=slip.company,
                lead_project_id=slip.project_id,
                ship_date=day,
                created_by=slip.shipped_by,
                created_at=slip.shipped_at,
            )
        )
        bind.execute(
            sa.text("UPDATE packing_slips SET load_id = :load WHERE id = :slip"),
            {"load": load_id, "slip": slip.id},
        )


def downgrade() -> None:
    op.drop_index("ix_packing_slips_load", table_name="packing_slips")
    op.drop_constraint("packing_slips_load_id_fkey", "packing_slips", type_="foreignkey")
    op.drop_column("packing_slips", "load_id")
    op.drop_index("ix_shipment_loads_company_ship_date", table_name="shipment_loads")
    op.drop_table("shipment_loads")
