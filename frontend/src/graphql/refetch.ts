// Operation names of the warehouse list/summary queries that go stale after an inventory or
// stock mutation (destock, allocate, flag/resolve deficient, adjust/move/reclassify, correction).
// Passed to useMutation's `refetchQueries` by operation name: Apollo refetches only the query
// instances currently mounted, so applying this superset uniformly is safe and self-scoping.
//
// GetInventoryItems (the lazy per-product-code detail grid) is intentionally NOT here - each
// caller already refetches that grid in its own onCompleted/onSuccess callback, so listing it
// would double-fetch. This list is what fixes the stale summary header and accordion counts.
export const WAREHOUSE_REFETCH_QUERIES = [
  'GetInventoryHierarchy',
  'GetInventoryByVendor',
  'GetUnlocatedInventory',
  'GetStockItems',
  'GetDeficientItems',
  'GetDeficiencyReviews',
  'GetWarehouseDashboard',
  'GetProjectProgressByProduct',
];

// Everything confirmShipment invalidates (#337). It flips OpeningItems to Shipped_Out and creates a
// packing slip, which contradicts four cached reads. Two lists because they heal different things:
//
// - SHIPPING_REFETCH_QUERIES heals what is MOUNTED. Apollo's refetchQueries only touches active
//   queries, which is what fixes the reported bug: the Ship view sits open behind the packing-slip
//   dialog, so GetShipReadyItems (cache-first) and GetOpeningLeafStatus never re-run on their own
//   and keep rendering the just-shipped leaf as Ship_Ready.
// - SHIPPING_STALE_ROOT_FIELDS heals what is NOT. Warehouse Opening Items and the Returns tab live
//   in other routes, so refetchQueries skips them and their next mount would serve a pre-shipment
//   cache-first snapshot. Evicting the root fields forces that mount to go to the network.
//
// GetNotifications is deliberately absent: NotificationBell mounts two instances with different
// variables and already polls every 30s, so listing it costs two round-trips per shipment for a
// badge that self-corrects.
export const SHIPPING_REFETCH_QUERIES = [
  'GetShipReadyItems',
  'GetOpeningLeafStatus',
  'GetPackingSlips',
  'GetOpeningItems',
];

export const SHIPPING_STALE_ROOT_FIELDS = [
  'shipReadyItems',
  'openingLeafStatus',
  'packingSlips',
  'openingItems',
];
