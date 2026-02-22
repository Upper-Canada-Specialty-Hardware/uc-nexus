"""Rename enum values from Title_Case to UPPER_CASE

Revision ID: 010
Revises: 009
Create Date: 2026-02-22
"""

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None

# (enum_type_name, old_value, new_value)
_RENAMES = [
    # classification
    ("classification", "Site_Hardware", "SITE_HARDWARE"),
    ("classification", "Shop_Hardware", "SHOP_HARDWARE"),
    # hardware_item_state
    ("hardware_item_state", "In_PO", "IN_PO"),
    # po_status
    ("po_status", "Draft", "DRAFT"),
    ("po_status", "Ordered", "ORDERED"),
    ("po_status", "Partially_Received", "PARTIALLY_RECEIVED"),
    ("po_status", "Closed", "CLOSED"),
    ("po_status", "Cancelled", "CANCELLED"),
    # pull_request_source
    ("pull_request_source", "Shop_Assembly", "SHOP_ASSEMBLY"),
    ("pull_request_source", "Shipping_Out", "SHIPPING_OUT"),
    # pull_request_status
    ("pull_request_status", "Pending", "PENDING"),
    ("pull_request_status", "In_Progress", "IN_PROGRESS"),
    ("pull_request_status", "Completed", "COMPLETED"),
    ("pull_request_status", "Cancelled", "CANCELLED"),
    # pull_request_item_type
    ("pull_request_item_type", "Loose", "LOOSE"),
    ("pull_request_item_type", "Opening_Item", "OPENING_ITEM"),
    # opening_item_state
    ("opening_item_state", "In_Inventory", "IN_INVENTORY"),
    ("opening_item_state", "Ship_Ready", "SHIP_READY"),
    ("opening_item_state", "Shipped_Out", "SHIPPED_OUT"),
    # shop_assembly_request_status
    ("shop_assembly_request_status", "Pending", "PENDING"),
    ("shop_assembly_request_status", "Approved", "APPROVED"),
    ("shop_assembly_request_status", "Rejected", "REJECTED"),
    # pull_status
    ("pull_status", "Not_Pulled", "NOT_PULLED"),
    ("pull_status", "Partial", "PARTIAL"),
    ("pull_status", "Pulled", "PULLED"),
    # assembly_status
    ("assembly_status", "Pending", "PENDING"),
    ("assembly_status", "Completed", "COMPLETED"),
    # notification_type
    ("notification_type", "pull_request_cancelled", "PULL_REQUEST_CANCELLED"),
    ("notification_type", "pull_request_completed", "PULL_REQUEST_COMPLETED"),
    ("notification_type", "shop_assembly_request_rejected", "SHOP_ASSEMBLY_REQUEST_REJECTED"),
    ("notification_type", "shipment_completed", "SHIPMENT_COMPLETED"),
]


def upgrade() -> None:
    for type_name, old, new in _RENAMES:
        op.execute(f"ALTER TYPE {type_name} RENAME VALUE '{old}' TO '{new}'")


def downgrade() -> None:
    for type_name, old, new in _RENAMES:
        op.execute(f"ALTER TYPE {type_name} RENAME VALUE '{new}' TO '{old}'")
