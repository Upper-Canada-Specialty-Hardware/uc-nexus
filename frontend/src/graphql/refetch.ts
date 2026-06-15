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
