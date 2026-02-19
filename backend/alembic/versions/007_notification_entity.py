"""notification entity: notifications

Revision ID: 007
Revises: 006
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type
    notification_type_enum = sa.Enum(
        'pull_request_cancelled', 'pull_request_completed',
        'shop_assembly_request_rejected', 'shipment_completed',
        name='notification_type',
    )
    notification_type_enum.create(op.get_bind(), checkfirst=True)

    # notifications table
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('recipient_role', sa.String(), nullable=False),
        sa.Column('type', sa.Enum(
            'pull_request_cancelled', 'pull_request_completed',
            'shop_assembly_request_rejected', 'shipment_completed',
            name='notification_type', create_type=False,
        ), nullable=False),
        sa.Column('message', sa.String(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('notifications')

    op.execute('DROP TYPE IF EXISTS notification_type')
