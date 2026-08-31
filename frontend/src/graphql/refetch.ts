// Operation names of the warehouse list/summary queries that go stale after an inventory or
// stock mutation (destock, allocate, flag/resolve deficient, adjust/move/reclassify, correction).
// Passed to useMutation's `refetchQueries` by operation name: Apollo refetches only the query
// instances currently mounted, so applying this superset uniformly is safe and self-scoping.
export const WAREHOUSE_REFETCH_QUERIES = [
  'GetUnlocatedInventory',
  'GetStockItems',
  'GetDeficientItems',
  'GetDeficiencyReviews',
  'GetWarehouseDashboard',
  'GetProjectProgressByProduct',
];

// What a successful receive invalidates, on top of the inventory summaries above (#416). The three
// added here are the Receiving page's own reads, and they only became worth naming when the
// back-order grid moved onto that page: a receive that closes a line has to take that line out of
// the section sitting directly under the button that was just pressed, and the PO table and recent
// feed beside it move for the same reason. Refetching by name is self-scoping - Apollo only touches
// mounted instances - so this costs nothing anywhere else in the app.
export const RECEIVE_REFETCH_QUERIES = [
  ...WAREHOUSE_REFETCH_QUERIES,
  'GetOpenPosSummary',
  'GetBackOrderedItems',
  'GetRecentReceiveRecords',
];

// What a draft-lifecycle write invalidates: create, edit, resubmit, reject, delete. Nothing in
// inventory moves at any of them - a draft is a count somebody wrote down - so the only stale read is
// the draft lists themselves, and every call site has one mounted (the approvals queue, or the
// author's My Drafts view). Refetching by name is self-scoping, so naming both surfaces costs
// nothing for whichever one is not live.
export const RECEIVE_DRAFT_REFETCH_QUERIES = ['GetReceiveDrafts', 'GetWarehouseDashboard'];

// What APPROVING a draft invalidates. Approval is where the posting moment went, so it inherits the
// whole meaning of RECEIVE_REFETCH_QUERIES - inventory summaries, the Receiving page's own lists -
// and adds the queue the approve button was pressed in. De-duplicated because the two lists overlap
// on the dashboard, and a name listed twice is a query refetched twice.
export const RECEIVE_APPROVE_REFETCH_QUERIES = [
  ...new Set([...RECEIVE_REFETCH_QUERIES, ...RECEIVE_DRAFT_REFETCH_QUERIES]),
];

// What confirmShipment invalidates (#337). The two lists are deliberately DISJOINT: evicting a root
// field that a mounted query also refetches makes Apollo fire a repair fetch for the incomplete
// cache diff on top of the explicit refetch, so the heaviest shipping resolvers would run twice
// concurrently - the pool-starvation pattern the perf rules in CLAUDE.md warn about.
//
// Refetched. A confirm CREATES a shipment, and a list gaining a row is the one case normalisation
// cannot cover: the mutation's PackingSlip is written to the cache but no watcher holds a reference
// to it, so a ShipmentsList mounted elsewhere in the module keeps showing the list it read before.
// Refetched rather than evicted because it is a list somebody is looking at - eviction transiently
// empties every mounted watcher, and this one would flash "No shipments match this search." on its
// way to showing the shipment that was just booked.
export const SHIPPING_REFETCH_QUERIES = ['GetPackingSlips'];

// Evicted. Both are read cache-first by a query that may not be active when a shipment is confirmed,
// which is precisely what refetchQueries cannot reach:
// - stagingPool: confirming from the staging workspace leaves it mounted, but a shipment can also be
//   confirmed and then navigated away from, and the pool has to be right when it is next opened.
// - requestCoverage: a slip is the moment hardware leaves, so it moves the composer's `sent` term.
//
// Absent on purpose: packingSlips, which is refetched by name above rather than evicted (a mounted
// ShipmentsList must not flash empty), and notifications (NotificationBell polls every 30s and
// mounts two instances with different variables, so listing it costs two round-trips for a badge
// that self-corrects).
export const SHIPPING_STALE_ROOT_FIELDS = ['stagingPool', 'shipReadyItems', 'requestCoverage'];

// What starting or completing a pull invalidates. Eviction-only, including the queue itself.
//
// pullRequests is evicted, not refetched, because completing happens from the pick page - where the
// active queue (it lists PENDING + IN_PROGRESS only) is not mounted, so a refetchQueries by name is
// skipped and the queue would next mount cache-first on a list still holding the completed pull: the
// "forced to refresh" symptom #613 set out to kill. Eviction reaches that unmounted-then-mounted
// queue, and the mounted case (completing from the modal on the queue) repairs itself the same way.
//
// The rest is a terminal exit's fallout in other modules: the staging pool a completed shipping pull
// feeds, the composer's `sent` term, and the derived stage the requests list draws as columns.
export const PULL_LIFECYCLE_STALE_ROOT_FIELDS = [
  'pullRequests',
  'shipReadyItems',
  'requestCoverage',
  'shopAssemblyRequests',
  'projectInventoryAvailability',
];

// What confirming a pick invalidates (#367). This is the moment stock actually leaves inventory, so
// it is the widest inventory blast radius in the warehouse short of a cancel.
//
// Refetched. The pick page's own sheet is refetched by name because the page stays mounted through
// the confirmation and has to re-render from the server's answer - a short confirm leaves rows the
// picker must keep working, and an optimistic guess about which ones would be a guess about
// physical hardware. The queue behind it carries the phase cell that this confirmation moves.
export const PICK_CONFIRM_REFETCH_QUERIES = ['GetPullPickSheet', 'GetPullRequests'];

// Evicted, and disjoint from the list above (see the note at the top of this file). Every one of
// these is read by a view that is not mounted while somebody is picking: the warehouse inventory
// summaries behind the pick page, the Start-a-Request wizard's availability (the consumed reservation
// and the deduction both change what may be claimed), and the assembly floor's work lists, which
// #343 made sensitive to the pull moving.
export const PICK_CONFIRM_STALE_ROOT_FIELDS = [
  'inventoryRows',
  'unlocatedInventory',
  'warehouseDashboard',
  'projectProgressByProduct',
  'projectInventoryAvailability',
  'shipReadyItems',
];

// What raising, dispatching, accepting, rejecting or discarding a request invalidates (#342). Each
// of those moments moves either the reservation book or the composer's `claimed` term, so
// `available = on-hand - deficient - reservations` changes for the whole project.
//
// Which moment reserves depends on the request type since #646: a shipping-out request reserves at
// creation, a shop-assembly one only when the manager dispatches a BATCH. Raising a shop-assembly
// request still moves `claimed`, which is why both fields are here for every one of these writes.
//
// Evicted, not refetched, and there is nothing paired to refetch by name: the reader is the Start a
// Task wizard, which is a full-screen dialog in another module and is by definition NOT mounted when
// a request is accepted or rejected - exactly the case refetchQueries cannot reach. Eviction is what
// stops the next wizard session from opening on the cache-first half of its cache-and-network read
// and gating a selection against pre-reservation numbers for a beat.
export const RESERVATION_STALE_ROOT_FIELDS = [
  'projectInventoryAvailability',
  // Creating a request adds to the composer's `claimed` term and rejecting one takes it away, so a
  // later composer session must re-read rather than open on a stale offer.
  'requestCoverage',
];

// What cancelling a pull invalidates (#343). It is the widest blast radius in the warehouse: stock
// goes back on the shelf, the source request returns to the accept queue, its claim is re-created,
// and the openings leave the assembly floor.
//
// Refetched. GetPullRequests is the queue the cancel was launched from (the row must show
// Cancelled), and the warehouse inventory summaries are the ones a mounted warehouse view is
// showing while the restock happens.
export const PULL_CANCEL_REFETCH_QUERIES = ['GetPullRequests', ...WAREHOUSE_REFETCH_QUERIES];

// Evicted. All of these are read by modules that are not mounted at cancel time: the composer's
// availability and its offer (the re-created reservation changes both), and the two queues the
// source request has just rejoined.
export const PULL_CANCEL_STALE_ROOT_FIELDS = [
  'projectInventoryAvailability',
  'requestCoverage',
  'shopAssemblyRequests',
  // Cancelling a shipping-out pull returns its request to PENDING too, and that queue lives on
  // another route entirely - so like shopAssemblyRequests it has to be evicted, not refetched.
  'shippingOutRequests',
];

// What a background GP-outbox drain invalidates (#353 PR E). A queued receive or PO registration
// lands minutes or hours after the user submitted it, while the browser is sitting on an arbitrary
// route - which is precisely the case `refetchQueries` cannot reach, since it only touches mounted
// instances of queries it can name.
//
// Eviction-only, and deliberately nothing paired to refetch by name: pairing an evict with a refetch
// is the double-run this whole file exists to prevent (see the disjointness note above). The
// GpOutboxWatcher evicts these when `lastDrainedAt` advances, and whichever watchers are mounted
// repair their own incomplete cache diffs.
//
// The set is "everything a receive or a PO registration changes": the PO lists and the PO's own
// detail/receiving view (status moves DRAFT -> GP_REGISTERED, received quantities move), the recent
// receives feed, and the warehouse inventory reads that a drained receipt has just added stock to.
export const GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS = [
  // The server-driven PO register list (#631: was `purchaseOrders`, now the paged field), so a
  // queued registration that drains does not leave the register showing the PO as DRAFT.
  'purchaseOrdersPage',
  'purchaseOrder',
  'poReceivingDetails',
  'recentReceiveRecords',
  // The History view's list (#447), which is the row above the panel poReceivingDetails fills. Both
  // or neither: evicting only the detail updates an expanded panel with the drained receipt while
  // the row directly above it keeps its pre-drain receive count and last-received date.
  'receivingHistoryPos',
  // A receipt that finally posts is a receipt that closes back-ordered lines and moves the PO's
  // received quantities, and since #416 both readings sit on the same page - the one the user is
  // most likely on when the drain lands. Evicting one without the other is what would let the
  // awaiting-receipt table keep pre-receipt pending counts directly above a grid that had updated.
  'backOrderedItems',
  // The lean receiving picker (#631: was `openPOs`, now the summary field).
  'openPosSummary',
  'warehouseDashboard',
  'inventoryRows',
  'projectInventoryAvailability',
  // A queued approval persists NOTHING until the drain: no receive record and no inventory. The
  // drain is when both appear, and it lands while the browser is on an arbitrary route - so the
  // draft's own status (APPROVED with a receipt now, rather than APPROVED and still syncing) is only
  // reachable this way.
  'receiveDrafts',
];
