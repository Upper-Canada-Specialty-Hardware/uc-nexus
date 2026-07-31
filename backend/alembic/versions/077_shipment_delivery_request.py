"""A shipment becomes a Delivery Request with a lifecycle (#447)

Revision ID: 077
Revises: 076
Create Date: 2026-07-31

A packing slip was a number, a project, who shipped it and a list of items. The paper UC Hardware's
shipping department actually fills in is a Delivery Request: pickup and delivery dates, who is
shipping it and how to reach them, where the truck collects from, the questions the site has to
answer before a truck is worth sending, and the two contacts. None of it was stored, so the form was
retyped from scratch every time one had to be reprinted, and nothing recorded that it had been
delivered.

Two pieces:

- `status` (shipment_status: SCHEDULED -> PICKED_UP -> DELIVERED) plus `picked_up_at`/`picked_up_by`
  and `delivered_at`/`delivered_by`. The lifecycle documents the physical journey only - **no
  inventory moves between these states**. Confirming the shipment is still what claims the hardware,
  because that is the moment the warehouse committed it.
- The header columns, every one nullable. A blank on the paper form is a real answer, not a missing
  one, so the schema records blanks rather than refusing them. Text (not String) for the three
  multi-line boxes; Date for the two dates, because nobody schedules a pickup to the minute and a
  timezone-shifted timestamp printed on a form would be actively misleading.

`status` is NOT NULL with a server default of DELIVERED, so existing slips backfill terminal. That is
the honest reading of them: every one predates the lifecycle and describes hardware that left the
building long ago, and landing them SCHEDULED would put a pile of historical shipments back on the
Shipments page presenting Mark Picked Up buttons for trucks that came and went. The default is left
on the column (precedent: migration 036) rather than dropped, so the one thing it can ever affect
again - an insert that does not name a status - degrades to "this is history" instead of failing.
New rows come from `confirm_shipment`, which names SCHEDULED explicitly.

There is no backfill for the header columns and there cannot be: the data only ever existed on paper
in a filing cabinet. Null means "shipped before Nexus recorded this", which the Delivery Request
prints as an empty box - the same thing the original form said.

`downgrade()` drops every column and then the enum type, losing the Delivery Request header and the
journey. The shipment itself, its items and everything the confirm did to inventory are untouched.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None

_STATUS_ENUM = "shipment_status"

# (column name, type) for the Delivery Request header. The order is the order of the paper form.
_HEADER_COLUMNS = [
    ("pickup_date", sa.Date()),
    ("delivery_date", sa.Date()),
    ("shipper_email", sa.String()),
    ("shipper_phone", sa.String()),
    ("pickup_location", sa.Text()),
    ("carrier_tag_bol", sa.String()),
    ("weight_lbs", sa.Numeric(10, 2)),
    ("delivery_address", sa.Text()),
    ("special_instructions", sa.Text()),
    ("gate_number", sa.String()),
    ("forklift_onsite", sa.String()),
    ("material_coming_back", sa.String()),
    ("site_material_included", sa.String()),
    ("construction_temp_keys", sa.String()),
    ("extra_frame_anchors", sa.String()),
    ("contractor_contact_name", sa.String()),
    ("contractor_contact_phone", sa.String()),
    ("ucsh_contact_name", sa.String()),
    ("ucsh_contact_phone", sa.String()),
    ("sales_order_number", sa.String()),
]

_LIFECYCLE_COLUMNS = [
    ("picked_up_at", sa.DateTime()),
    ("picked_up_by", sa.String()),
    ("delivered_at", sa.DateTime()),
    ("delivered_by", sa.String()),
]


def upgrade() -> None:
    shipment_status = postgresql.ENUM("SCHEDULED", "PICKED_UP", "DELIVERED", name=_STATUS_ENUM)
    shipment_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "packing_slips",
        sa.Column(
            "status",
            postgresql.ENUM("SCHEDULED", "PICKED_UP", "DELIVERED", name=_STATUS_ENUM, create_type=False),
            nullable=False,
            server_default="DELIVERED",
        ),
    )

    for name, column_type in _HEADER_COLUMNS + _LIFECYCLE_COLUMNS:
        op.add_column("packing_slips", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_HEADER_COLUMNS + _LIFECYCLE_COLUMNS):
        op.drop_column("packing_slips", name)
    op.drop_column("packing_slips", "status")
    sa.Enum(name=_STATUS_ENUM).drop(op.get_bind(), checkfirst=True)
