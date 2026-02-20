"""all explicit indexes

Revision ID: 008
Revises: 007
Create Date: 2026-02-18
"""

from alembic import op

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_projects_project_id', 'projects', ['project_id'])
    op.create_index('ix_openings_project_opening', 'openings', ['project_id', 'opening_number'])
    op.create_index('ix_hardware_items_project_cat_code', 'hardware_items', ['project_id', 'hardware_category', 'product_code'])
    op.create_index('ix_hardware_items_state', 'hardware_items', ['state'])
    op.create_index('ix_hardware_items_po_line_item', 'hardware_items', ['po_line_item_id'])
    op.create_index('ix_purchase_orders_project_status', 'purchase_orders', ['project_id', 'status'])
    op.create_index('ix_purchase_orders_po_number', 'purchase_orders', ['po_number'])
    op.create_index('ix_po_line_items_po_id', 'po_line_items', ['po_id'])
    op.create_index('ix_receive_records_po_id', 'receive_records', ['po_id'])
    op.create_index('ix_receive_line_items_receive_record', 'receive_line_items', ['receive_record_id'])
    op.create_index('ix_receive_line_items_po_line_item', 'receive_line_items', ['po_line_item_id'])
    op.create_index('ix_inventory_locations_project_cat_code', 'inventory_locations', ['project_id', 'hardware_category', 'product_code'])
    op.create_index('ix_inventory_locations_shelf', 'inventory_locations', ['shelf'])
    op.create_index('ix_pull_requests_project_source_status', 'pull_requests', ['project_id', 'source', 'status'])
    op.create_index('ix_pull_requests_assigned_to', 'pull_requests', ['assigned_to'])
    op.create_index('ix_pull_requests_created_at', 'pull_requests', ['created_at'])
    op.create_index('ix_pull_request_items_pull_request', 'pull_request_items', ['pull_request_id'])
    op.create_index('ix_pull_request_items_opening_item', 'pull_request_items', ['opening_item_id'])
    op.create_index('ix_opening_items_project_state', 'opening_items', ['project_id', 'state'])
    op.create_index('ix_opening_items_opening_id', 'opening_items', ['opening_id'])
    op.create_index('ix_opening_item_hardware_opening_item', 'opening_item_hardware', ['opening_item_id'])
    op.create_index('ix_shop_assembly_requests_project_status', 'shop_assembly_requests', ['project_id', 'status'])
    op.create_index('ix_shop_assembly_openings_request', 'shop_assembly_openings', ['shop_assembly_request_id'])
    op.create_index('ix_shop_assembly_openings_opening_pull', 'shop_assembly_openings', ['opening_id', 'pull_status'])
    op.create_index('ix_shop_assembly_opening_items_opening', 'shop_assembly_opening_items', ['shop_assembly_opening_id'])
    # ix_packing_slips_project and ix_packing_slip_items_packing_slip
    # already created in 006_shipping_entities
    op.create_index('ix_notifications_project_role_read', 'notifications', ['project_id', 'recipient_role', 'is_read'])


def downgrade() -> None:
    op.drop_index('ix_notifications_project_role_read', 'notifications')
    # ix_packing_slip_items_packing_slip and ix_packing_slips_project
    # are dropped by 006_shipping_entities downgrade
    op.drop_index('ix_shop_assembly_opening_items_opening', 'shop_assembly_opening_items')
    op.drop_index('ix_shop_assembly_openings_opening_pull', 'shop_assembly_openings')
    op.drop_index('ix_shop_assembly_openings_request', 'shop_assembly_openings')
    op.drop_index('ix_shop_assembly_requests_project_status', 'shop_assembly_requests')
    op.drop_index('ix_opening_item_hardware_opening_item', 'opening_item_hardware')
    op.drop_index('ix_opening_items_opening_id', 'opening_items')
    op.drop_index('ix_opening_items_project_state', 'opening_items')
    op.drop_index('ix_pull_request_items_opening_item', 'pull_request_items')
    op.drop_index('ix_pull_request_items_pull_request', 'pull_request_items')
    op.drop_index('ix_pull_requests_created_at', 'pull_requests')
    op.drop_index('ix_pull_requests_assigned_to', 'pull_requests')
    op.drop_index('ix_pull_requests_project_source_status', 'pull_requests')
    op.drop_index('ix_inventory_locations_shelf', 'inventory_locations')
    op.drop_index('ix_inventory_locations_project_cat_code', 'inventory_locations')
    op.drop_index('ix_receive_line_items_po_line_item', 'receive_line_items')
    op.drop_index('ix_receive_line_items_receive_record', 'receive_line_items')
    op.drop_index('ix_receive_records_po_id', 'receive_records')
    op.drop_index('ix_po_line_items_po_id', 'po_line_items')
    op.drop_index('ix_purchase_orders_po_number', 'purchase_orders')
    op.drop_index('ix_purchase_orders_project_status', 'purchase_orders')
    op.drop_index('ix_hardware_items_po_line_item', 'hardware_items')
    op.drop_index('ix_hardware_items_state', 'hardware_items')
    op.drop_index('ix_hardware_items_project_cat_code', 'hardware_items')
    op.drop_index('ix_openings_project_opening', 'openings')
    op.drop_index('ix_projects_project_id', 'projects')
