"""shipment photos: containers as loaded, loads as delivered (issue #1728)

From the outbound supervisor's walkthrough review (#1720): the floor photographs every container
before it is loaded, and the drivers asked to photograph the delivery, today filed by hand. New table
`shipment_photos`; the images are in object storage, keyed by `s3_key`.

Revision ID: 148
Revises: 147
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "148"
down_revision = "147"
branch_labels = None
depends_on = None

_KINDS = ("LOADING", "DELIVERY")


def upgrade() -> None:
    postgresql.ENUM(*_KINDS, name="shipment_photo_kind").create(op.get_bind(), checkfirst=True)
    op.create_table(
        "shipment_photos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("container_id", sa.Uuid(), nullable=True),
        sa.Column("packing_slip_id", sa.Uuid(), nullable=True),
        sa.Column("kind", postgresql.ENUM(*_KINDS, name="shipment_photo_kind", create_type=False), nullable=False),
        sa.Column("s3_key", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("taken_by", sa.String(), nullable=False),
        sa.Column("taken_by_user_id", sa.String(), nullable=True),
        sa.Column("taken_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "container_id IS NOT NULL OR packing_slip_id IS NOT NULL", name="ck_shipment_photos_has_subject"
        ),
        sa.CheckConstraint("file_size >= 1", name="ck_shipment_photos_file_size_positive"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["container_id"], ["shipment_containers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["packing_slip_id"], ["packing_slips.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipment_photos_container", "shipment_photos", ["container_id"])
    op.create_index("ix_shipment_photos_packing_slip", "shipment_photos", ["packing_slip_id"])


def downgrade() -> None:
    op.drop_index("ix_shipment_photos_packing_slip", table_name="shipment_photos")
    op.drop_index("ix_shipment_photos_container", table_name="shipment_photos")
    op.drop_table("shipment_photos")
    postgresql.ENUM(name="shipment_photo_kind").drop(op.get_bind(), checkfirst=True)
