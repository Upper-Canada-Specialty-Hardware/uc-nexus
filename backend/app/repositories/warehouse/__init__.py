"""Warehouse repository package - split by sub-domain (#265).

Sub-modules: receiving, locations, inventory, pull_requests, audit, progress.
The package re-exports the full public API so callers keep a single import surface.
"""

from .audit import (
    _log_audit_event,
    get_audit_log,
)
from .inventory import (
    adjust_inventory_quantity,
    get_inventory_by_vendor,
    get_inventory_hierarchy,
    get_inventory_items,
    get_opening_item_details,
    get_opening_items,
    get_opening_leaf_counts,
    get_opening_leaf_status,
    get_unlocated_inventory,
    override_inventory_quantity,
)
from .locations import (
    _normalize_and_validate_location_fields,
    assign_inventory_location,
    assign_opening_item_location,
    get_distinct_location_values,
    get_location_audit_history,
    get_location_contents,
    get_location_duplicates,
    get_location_utilization,
    mark_inventory_unlocated,
    mark_opening_item_unlocated,
    merge_locations,
    move_inventory_location,
    move_opening_item_location,
    normalize_location_value,
)
from .progress import (
    PLACED_PO_STATUSES,
    get_project_progress_by_product,
    get_warehouse_dashboard,
)
from .pull_requests import (
    Shortfall,
    SufficiencyResult,
    approve_pull_request,
    check_inventory_sufficiency,
    complete_pull_request,
    get_pull_request_details,
    get_pull_requests,
)
from .receiving import (
    create_receive,
    get_back_ordered_items,
    get_expected_deliveries,
    get_po_receiving_details,
    get_recent_receive_records,
    validate_receive_eligibility,
)

__all__ = [
    "PLACED_PO_STATUSES",
    "Shortfall",
    "SufficiencyResult",
    "_log_audit_event",
    "_normalize_and_validate_location_fields",
    "adjust_inventory_quantity",
    "approve_pull_request",
    "assign_inventory_location",
    "assign_opening_item_location",
    "check_inventory_sufficiency",
    "complete_pull_request",
    "create_receive",
    "get_audit_log",
    "get_back_ordered_items",
    "get_distinct_location_values",
    "get_expected_deliveries",
    "get_inventory_by_vendor",
    "get_inventory_hierarchy",
    "get_inventory_items",
    "get_location_audit_history",
    "get_location_contents",
    "get_location_duplicates",
    "get_location_utilization",
    "get_opening_item_details",
    "get_opening_items",
    "get_opening_leaf_counts",
    "get_opening_leaf_status",
    "get_po_receiving_details",
    "get_project_progress_by_product",
    "get_pull_request_details",
    "get_pull_requests",
    "get_recent_receive_records",
    "get_unlocated_inventory",
    "get_warehouse_dashboard",
    "mark_inventory_unlocated",
    "mark_opening_item_unlocated",
    "merge_locations",
    "move_inventory_location",
    "move_opening_item_location",
    "normalize_location_value",
    "override_inventory_quantity",
    "validate_receive_eligibility",
]
