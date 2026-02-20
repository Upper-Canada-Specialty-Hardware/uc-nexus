"""check constraints on quantity fields

Revision ID: 009
Revises: 008
Create Date: 2026-02-19
"""

from alembic import op

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint('ck_hardware_items_item_quantity_positive', 'hardware_items', 'item_quantity >= 1')
    op.create_check_constraint('ck_po_line_items_ordered_quantity_positive', 'po_line_items', 'ordered_quantity >= 1')
    op.create_check_constraint('ck_po_line_items_received_quantity_nonneg', 'po_line_items', 'received_quantity >= 0')
    op.create_check_constraint('ck_receive_line_items_quantity_received_positive', 'receive_line_items', 'quantity_received >= 1')
    op.create_check_constraint('ck_inventory_locations_quantity_nonneg', 'inventory_locations', 'quantity >= 0')
    op.create_check_constraint('ck_opening_items_quantity_positive', 'opening_items', 'quantity >= 1')
    op.create_check_constraint('ck_opening_item_hardware_quantity_positive', 'opening_item_hardware', 'quantity >= 1')
    op.create_check_constraint('ck_pull_request_items_requested_quantity_positive', 'pull_request_items', 'requested_quantity >= 1')
    op.create_check_constraint('ck_shop_assembly_opening_items_quantity_positive', 'shop_assembly_opening_items', 'quantity >= 1')
    # ck_packing_slip_items_quantity_positive already created inline in 006_shipping_entities


def downgrade() -> None:
    # ck_packing_slip_items_quantity_positive dropped by 006_shipping_entities downgrade
    op.drop_constraint('ck_shop_assembly_opening_items_quantity_positive', 'shop_assembly_opening_items', type_='check')
    op.drop_constraint('ck_pull_request_items_requested_quantity_positive', 'pull_request_items', type_='check')
    op.drop_constraint('ck_opening_item_hardware_quantity_positive', 'opening_item_hardware', type_='check')
    op.drop_constraint('ck_opening_items_quantity_positive', 'opening_items', type_='check')
    op.drop_constraint('ck_inventory_locations_quantity_nonneg', 'inventory_locations', type_='check')
    op.drop_constraint('ck_receive_line_items_quantity_received_positive', 'receive_line_items', type_='check')
    op.drop_constraint('ck_po_line_items_received_quantity_nonneg', 'po_line_items', type_='check')
    op.drop_constraint('ck_po_line_items_ordered_quantity_positive', 'po_line_items', type_='check')
    op.drop_constraint('ck_hardware_items_item_quantity_positive', 'hardware_items', type_='check')
