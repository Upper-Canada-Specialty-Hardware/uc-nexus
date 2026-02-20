"""shipping entities: packing_slips, packing_slip_items

Revision ID: 006
Revises: 005
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'packing_slips',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('packing_slip_number', sa.String(50), unique=True, nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('shipped_by', sa.String(), nullable=False),
        sa.Column('shipped_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_packing_slips_project', 'packing_slips', ['project_id'])

    op.create_table(
        'packing_slip_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('packing_slip_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('packing_slips.id'), nullable=False),
        sa.Column('item_type', sa.Enum(
            'Loose', 'Opening_Item',
            name='pull_request_item_type',
        ), nullable=False),
        sa.Column('opening_item_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('opening_items.id'), nullable=True),
        sa.Column('opening_number', sa.String(), nullable=True),
        sa.Column('product_code', sa.String(), nullable=False),
        sa.Column('hardware_category', sa.String(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.CheckConstraint('quantity >= 1', name='ck_packing_slip_items_quantity_positive'),
    )
    op.create_index('ix_packing_slip_items_packing_slip', 'packing_slip_items', ['packing_slip_id'])


def downgrade() -> None:
    op.drop_index('ix_packing_slip_items_packing_slip', table_name='packing_slip_items')
    op.drop_table('packing_slip_items')
    op.drop_index('ix_packing_slips_project', table_name='packing_slips')
    op.drop_table('packing_slips')
