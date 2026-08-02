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

// What a successful receive invalidates, on top of the inventory summaries above (#416). The three
// added here are the Receiving page's own reads, and they only became worth naming when the
// back-order grid moved onto that page: a receive that closes a line has to take that line out of
// the section sitting directly under the button that was just pressed, and the PO table and recent
// feed beside it move for the same reason. Refetching by name is self-scoping - Apollo only touches
// mounted instances - so this costs nothing anywhere else in the app.
export const RECEIVE_REFETCH_QUERIES = [
  ...WAREHOUSE_REFETCH_QUERIES,
  'GetOpenPOs',
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
// Refetched. GetOpeningLeafStatus is cache-and-network but stays mounted for the whole flow, so
// nothing re-triggers it on its own and the rollup keeps its pre-shipment count.
//
// GetPackingSlips is here for the same reason. A confirm CREATES a shipment, and a list gaining a
// row is the one case normalisation cannot cover: the mutation's PackingSlip is written to the cache
// but no watcher holds a reference to it, so a ShipmentsList mounted elsewhere in the module keeps
// showing the list it read before. Refetched rather than evicted because it is a list somebody is
// looking at - eviction transiently empties every mounted watcher, and this one would flash "No
// shipments match this search." on its way to showing the shipment that was just booked.
export const SHIPPING_REFETCH_QUERIES = ['GetOpeningLeafStatus', 'GetPackingSlips'];

// Evicted. Both are read cache-first by a query that may not be active when a shipment is confirmed,
// which is precisely what refetchQueries cannot reach:
// - shipReadyItems: the Ship view is usually mounted behind the dialog, and eviction makes its
//   watcher re-run (an incomplete cache diff repairs itself by refetching). But the cart drawer is
//   rendered outside <Routes>, so a shipment can also be confirmed from the Requests/Returns tab
//   with the Ship view unmounted - refetchQueries would silently skip it there.
// - openingItems: warehouse Opening Items is another module entirely, never active at ship time.
//
// Absent on purpose: packingSlips, which is refetched by name above rather than evicted (a mounted
// ShipmentsList must not flash empty), and notifications (NotificationBell polls every 30s and
// mounts two instances with different variables, so listing it costs two round-trips for a badge
// that self-corrects).
export const SHIPPING_STALE_ROOT_FIELDS = ['shipReadyItems', 'openingItems'];

// The pipeline read (#344). It is a route of its own inside the shop-assembly module, so it is by
// definition NOT mounted while anybody is accepting a request, staging a cart, saving progress,
// completing a leaf or cancelling a pull - every one of which moves a leaf along the ladder it draws.
// That makes it eviction-only in every list below: refetchQueries reaches mounted instances, and
// there are none.
//
// Both fields, always together. `assemblyPipelineSummaries` is the list and `assemblyPipeline` the
// detail; they are computed from the same aggregates, so leaving one behind would be the one way to
// make the two screens disagree - which is the exact failure this view exists to fix.
export const PIPELINE_STALE_ROOT_FIELDS = ['assemblyPipelineSummaries', 'assemblyPipeline'];

// What a shop-assembly progress save invalidates (#340). Same disjointness rule as above: a root
// field that is evicted must not also be refetched by name, or Apollo fires a repair fetch for the
// incomplete cache diff on top of the explicit refetch.
//
// Refetched, and `assembleList` is refetched here rather than evicted. Both lists behind this modal
// are refetched by name: GetMyWork is the assembler's own board, GetAssembleList is the other entry
// point into the same modal. refetchQueries reaches only mounted instances, so naming both is a
// no-op for whichever one is not live.
//
// `assembleList` used to be evicted instead, on the belief that the two views are never mounted
// together. They are: ManagerAssignPanel runs GET_ASSEMBLE_LIST from inside AssignmentBoard, and the
// Assemble List page opens this modal over its own grid. Eviction transiently empties `assembleList`
// for every mounted watcher, so the row this modal is rendered from disappears and the modal
// unmounts mid-save - the assembler loses the leaf they were working on. A refetch swaps the data in
// without ever passing through empty.
//
// Note that recordAssemblyProgress already returns the updated opening with its items, so the modal
// itself needs neither of these - these lists exist for the *lists* behind it, whose status chip and
// "5/8 units" column would otherwise sit stale.
export const ASSEMBLY_PROGRESS_REFETCH_QUERIES = ['GetMyWork', 'GetAssembleList'];

// There is deliberately no ASSEMBLY_PROGRESS_STALE_ROOT_FIELDS any more. Everything a progress save
// invalidates and can reach is refetched above; the only thing left to evict is the pipeline, and
// the call site evicts PIPELINE_STALE_ROOT_FIELDS directly so the disjointness of the two lists is
// visible at a glance rather than hidden behind a name that once meant something wider.

// What installing a replacement onto a finished leaf invalidates (#341). Same disjointness rule.
//
// Refetched. GetReplacementWork is the list the install was launched from and is mounted by
// definition, so refetchQueries reaches it; the row either drops out or its pendingQuantity falls.
export const REPLACEMENT_INSTALL_REFETCH_QUERIES = ['GetReplacementWork'];

// Evicted. openingItems carries awaitingReplacementQuantity, which the shipping wizard reads to
// decide whether a leaf is flagged - and the wizard is a different module that is never mounted
// while an assembler is installing, which is exactly what refetchQueries cannot reach.
export const REPLACEMENT_INSTALL_STALE_ROOT_FIELDS = ['openingItems', ...PIPELINE_STALE_ROOT_FIELDS];

// What completing a leaf invalidates (#340 made completion the sole writer of the assembled unit,
// reading the persisted counters instead of taking a claim as input).
//
// Eviction-only, and there is deliberately nothing paired to refetch by name: the two views that can
// launch a completion (My Work and the Assemble List) each refetch their own list in the modal's
// onCompleted callback, so naming those root fields here would fire a repair fetch on top of that
// refetch - the double-run this file exists to prevent. What their local refetch cannot reach is the
// other modules:
//   - openingItems: the warehouse's assembled-leaf grid, and the carrier of the #341
//     awaitingReplacementQuantity flag.
//   - shipReadyItems: a newly assembled leaf is new shipping inventory, and the shipping wizard is a
//     different module entirely.
export const ASSEMBLY_COMPLETE_STALE_ROOT_FIELDS = [
  'openingItems',
  'shipReadyItems',
  ...PIPELINE_STALE_ROOT_FIELDS,
];

// What claiming or releasing an opening invalidates. All three assignment surfaces (the Assemble
// List, the manager board, the manager panel) share GET_ASSEMBLE_LIST and refetch it themselves, so
// again this is eviction-only and `assembleList` is deliberately absent. `myWork` is the assembler's
// own board, which is a different route and never mounted while a manager is assigning.
export const ASSIGNMENT_STALE_ROOT_FIELDS = ['myWork', ...PIPELINE_STALE_ROOT_FIELDS];

// What starting or completing a pull invalidates, beyond the queue the caller already refetches.
//
// #343 re-keyed workability from "the pull is COMPLETED" to "this opening is PULLED", which made both
// of these moments change what the assembly floor can see: starting a pick lets the Assemble List
// show the pull's openings as waiting, and completing stages whatever is left. Neither list is
// mounted while a warehouse user is working a pull, so both are evicted rather than refetched.
// shipReadyItems is here for the shipping-out side, where completing the pull is what flips leaves
// to SHIP_READY.
export const PULL_LIFECYCLE_STALE_ROOT_FIELDS = [
  'assembleList',
  'myWork',
  'shipReadyItems',
  'projectInventoryAvailability',
  ...PIPELINE_STALE_ROOT_FIELDS,
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
// summaries behind the pick page, the Start-a-Task wizard's availability (the consumed reservation
// and the deduction both change what may be claimed), and the assembly floor's work lists, which
// #343 made sensitive to the pull moving.
export const PICK_CONFIRM_STALE_ROOT_FIELDS = [
  'inventoryHierarchy',
  'inventoryByVendor',
  'unlocatedInventory',
  'warehouseDashboard',
  'projectProgressByProduct',
  'projectInventoryAvailability',
  'assembleList',
  'myWork',
  'shipReadyItems',
  ...PIPELINE_STALE_ROOT_FIELDS,
];

// What creating, accepting, rejecting or reopening a request invalidates (#342). Creating a request
// RESERVES inventory, so every one of these moments changes `available = on-hand - deficient -
// reservations` for the whole project.
//
// Evicted, not refetched, and there is nothing paired to refetch by name: the reader is the Start a
// Task wizard, which is a full-screen dialog in another module and is by definition NOT mounted when
// a request is accepted or rejected - exactly the case refetchQueries cannot reach. Eviction is what
// stops the next wizard session from opening on the cache-first half of its cache-and-network read
// and gating a selection against pre-reservation numbers for a beat.
export const RESERVATION_STALE_ROOT_FIELDS = [
  'projectInventoryAvailability',
  // Creating, accepting, rejecting and reopening are the first four rungs of the pipeline ladder
  // (#344), so all four move a request along it.
  ...PIPELINE_STALE_ROOT_FIELDS,
];

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
export const PULL_STAGING_STALE_ROOT_FIELDS = ['assembleList', 'myWork', ...PIPELINE_STALE_ROOT_FIELDS];

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
  // Cancelling a shipping-out pull returns its request to PENDING too, and that queue lives on
  // another route entirely - so like shopAssemblyRequests it has to be evicted, not refetched.
  'shippingOutRequests',
  // A cancellation puts the request back at the start of the ladder and leaves a cancelled pull in
  // its history (#344), which is the reading that stops it looking like it was never accepted.
  ...PIPELINE_STALE_ROOT_FIELDS,
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
  'purchaseOrders',
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
  'openPOs',
  'warehouseDashboard',
  'inventoryHierarchy',
  'inventoryByVendor',
  'projectInventoryAvailability',
  // A queued approval persists NOTHING until the drain: no receive record, no inventory, and no
  // keep-or-ship decision for the person who raised the PO. The drain is when all three appear, and
  // it lands while the browser is on an arbitrary route - so the draft's own status (APPROVED with a
  // receipt now, rather than APPROVED and still syncing) and the decision that came with it are only
  // reachable this way.
  'receiveDrafts',
  'myReceiveDecisions',
];
