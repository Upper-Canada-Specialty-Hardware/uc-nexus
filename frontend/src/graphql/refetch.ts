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

// What confirmShipment invalidates (#337). The two lists are deliberately DISJOINT: evicting a root
// field that a mounted query also refetches makes Apollo fire a repair fetch for the incomplete
// cache diff on top of the explicit refetch, so the heaviest shipping resolvers would run twice
// concurrently - the pool-starvation pattern the perf rules in CLAUDE.md warn about.
//
// Refetched. GetOpeningLeafStatus is cache-and-network but stays mounted for the whole flow, so
// nothing re-triggers it on its own and the rollup keeps its pre-shipment count.
export const SHIPPING_REFETCH_QUERIES = ['GetOpeningLeafStatus'];

// Evicted. Both are read cache-first by a query that may not be active when a shipment is confirmed,
// which is precisely what refetchQueries cannot reach:
// - shipReadyItems: the Ship view is usually mounted behind the dialog, and eviction makes its
//   watcher re-run (an incomplete cache diff repairs itself by refetching). But the cart drawer is
//   rendered outside <Routes>, so a shipment can also be confirmed from the Requests/Returns tab
//   with the Ship view unmounted - refetchQueries would silently skip it there.
// - openingItems: warehouse Opening Items is another module entirely, never active at ship time.
//
// Absent on purpose: packingSlips (ShipmentsList reads cache-and-network, so its next mount already
// goes to the network) and notifications (NotificationBell polls every 30s and mounts two instances
// with different variables, so listing it costs two round-trips for a badge that self-corrects).
export const SHIPPING_STALE_ROOT_FIELDS = ['shipReadyItems', 'openingItems'];

// What a shop-assembly progress save invalidates (#340). Same disjointness rule as above: a root
// field that is evicted must not also be refetched by name, or Apollo fires a repair fetch for the
// incomplete cache diff on top of the explicit refetch.
//
// Refetched. GetMyWork is the assembler's own board and is mounted whenever they are saving from My
// Work; refetchQueries reaches only mounted instances, so this is a no-op when the save came from
// the Assemble List instead. Note that recordAssemblyProgress already returns the updated opening
// with its items, so the modal itself needs neither of these - these lists exist for the *lists*
// behind it, whose status chip and "5/8 units" column would otherwise sit stale.
export const ASSEMBLY_PROGRESS_REFETCH_QUERIES = ['GetMyWork'];

// Evicted. assembleList is read by the other entry point into the same modal, and the two views are
// never mounted together (separate routes), so whichever one is live repairs its own diff.
export const ASSEMBLY_PROGRESS_STALE_ROOT_FIELDS = ['assembleList'];

// What installing a replacement onto a finished leaf invalidates (#341). Same disjointness rule.
//
// Refetched. GetReplacementWork is the list the install was launched from and is mounted by
// definition, so refetchQueries reaches it; the row either drops out or its pendingQuantity falls.
export const REPLACEMENT_INSTALL_REFETCH_QUERIES = ['GetReplacementWork'];

// Evicted. openingItems carries awaitingReplacementQuantity, which the shipping wizard reads to
// decide whether a leaf is flagged - and the wizard is a different module that is never mounted
// while an assembler is installing, which is exactly what refetchQueries cannot reach.
export const REPLACEMENT_INSTALL_STALE_ROOT_FIELDS = ['openingItems'];

// What creating, accepting, rejecting or reopening a request invalidates (#342). Creating a request
// RESERVES inventory, so every one of these moments changes `available = on-hand - deficient -
// reservations` for the whole project.
//
// Evicted, not refetched, and there is nothing paired to refetch by name: the reader is the Start a
// Task wizard, which is a full-screen dialog in another module and is by definition NOT mounted when
// a request is accepted or rejected - exactly the case refetchQueries cannot reach. Eviction is what
// stops the next wizard session from opening on the cache-first half of its cache-and-network read
// and gating a selection against pre-reservation numbers for a beat.
export const RESERVATION_STALE_ROOT_FIELDS = ['projectInventoryAvailability'];

// What confirming a batch of openings as staged invalidates (#343). Same disjointness rule as above.
//
// Refetched. GetPullRequests is the queue the staging modal was opened from and is mounted by
// definition, so refetchQueries reaches it; its staging chip goes from "3 of 8" to "4 of 8", and the
// pull's own status flips when the last opening lands. The panel refetches its own
// GetPullRequestOpenings in onCompleted, so that one is deliberately not listed here.
export const PULL_STAGING_REFETCH_QUERIES = ['GetPullRequests'];

// Evicted. Newly staged openings become assignable and workable at once, and both readers live in
// the shop-assembly module - a different route that is by definition not mounted while a warehouse
// user is picking, which is exactly what refetchQueries cannot reach.
export const PULL_STAGING_STALE_ROOT_FIELDS = ['assembleList', 'myWork'];

// What cancelling a pull invalidates (#343). It is the widest blast radius in the warehouse: stock
// goes back on the shelf, the source request returns to the accept queue, its claim is re-created,
// and the openings leave the assembly floor.
//
// Refetched. GetPullRequests is the queue the cancel was launched from (the row must show
// Cancelled), and the warehouse inventory summaries are the ones a mounted warehouse view is
// showing while the restock happens.
export const PULL_CANCEL_REFETCH_QUERIES = ['GetPullRequests', ...WAREHOUSE_REFETCH_QUERIES];

// Evicted. All three are read by modules that are not mounted at cancel time: the assembly floor's
// two work lists, the Start-a-Task wizard's availability (the re-created reservation changes what
// may be claimed), and the accept queue that the source request has just rejoined.
export const PULL_CANCEL_STALE_ROOT_FIELDS = [
  'assembleList',
  'myWork',
  'projectInventoryAvailability',
  'shopAssemblyRequests',
];
