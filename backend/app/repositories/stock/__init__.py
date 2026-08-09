"""Stock repository package - split by sub-domain (#265).

Sub-modules: items (reads + in-pool corrections), movements (destock / allocate /
receive-to-stock / transfer), deficiency (report / review / resolve), common (shared internals).
The package re-exports the full public API so callers keep a single import surface.
"""

from .common import (
    _find_or_create_stock_row,
    _log_audit_event,
)
from .deficiency import (
    get_deficiency_reviews,
    get_deficient_items,
    report_inventory_deficiency,
    report_stock_deficiency,
    resolve_deficiency,
)
from .items import (
    adjust_stock_quantity,
    assign_stock_item_location,
    get_stock_item,
    get_stock_items,
    mark_stock_item_unlocated,
    move_stock_location,
    reclassify_stock_item,
)
from .movements import (
    allocate_stock_to_project,
    destock_inventory,
    receive_into_stock,
    transfer_inventory,
)

__all__ = [
    "_find_or_create_stock_row",
    "_log_audit_event",
    "adjust_stock_quantity",
    "allocate_stock_to_project",
    "assign_stock_item_location",
    "destock_inventory",
    "get_deficiency_reviews",
    "get_deficient_items",
    "get_stock_item",
    "get_stock_items",
    "mark_stock_item_unlocated",
    "move_stock_location",
    "receive_into_stock",
    "reclassify_stock_item",
    "report_inventory_deficiency",
    "report_stock_deficiency",
    "resolve_deficiency",
    "transfer_inventory",
]
