"""pull request entities: pull_requests, pull_request_items

Revision ID: 004
Revises: 003
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pull_requests table
    op.create_table(
        'pull_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('request_number', sa.String(50), unique=True, nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('source', sa.Enum(
            'Shop_Assembly', 'Shipping_Out',
            name='pull_request_source',
        ), nullable=False),
        sa.Column('status', sa.Enum(
            'Pending', 'In_Progress', 'Completed', 'Cancelled',
            name='pull_request_status',
        ), nullable=False),
        sa.Column('requested_by', sa.String(), nullable=False),
        sa.Column('assigned_to', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )

    # pull_request_items table
    # Note: opening_item_id FK will be added in migration 005 after opening_items exists
    op.create_table(
        'pull_request_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('pull_request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('pull_requests.id'), nullable=False),
        sa.Column('item_type', sa.Enum(
            'Loose', 'Opening_Item',
            name='pull_request_item_type',
        ), nullable=False),
        sa.Column('opening_number', sa.String(), nullable=False),
        sa.Column('opening_item_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('hardware_category', sa.String(), nullable=True),
        sa.Column('product_code', sa.String(), nullable=True),
        sa.Column('requested_quantity', sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('pull_request_items')
    op.drop_table('pull_requests')

    op.execute('DROP TYPE IF EXISTS pull_request_item_type')
    op.execute('DROP TYPE IF EXISTS pull_request_status')
    op.execute('DROP TYPE IF EXISTS pull_request_source')
