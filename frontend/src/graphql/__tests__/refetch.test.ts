import { describe, it, expect } from 'vitest';
import * as refetch from '../refetch';

// refetch.ts encodes one rule with real consequences (CLAUDE.md perf rules, #337): for any single
// mutation, the queries refetched by name and the root fields evicted must be DISJOINT. Evicting a
// root field a mounted query also refetches makes Apollo fire a repair fetch for the incomplete
// cache diff on top of the explicit refetch, and the two heaviest resolvers then run concurrently
// against a small connection pool.
//
// The rule is stated in prose at the top of that file and was, until now, checked by nobody. These
// tests are cheap and they fail on exactly the edit that would break it.

/** Operation name -> the root field it writes, for the pairs the lists below actually use. */
const ROOT_FIELD_OF_QUERY: Record<string, string> = {
  GetPullRequests: 'pullRequests',
  GetShopAssemblyRequests: 'shopAssemblyRequests',
  GetPackingSlips: 'packingSlips',
  GetUnlocatedInventory: 'unlocatedInventory',
  GetStockItems: 'stockItems',
  GetDeficientItems: 'deficientItems',
  GetDeficiencyReviews: 'deficiencyReviews',
  GetWarehouseDashboard: 'warehouseDashboard',
  GetProjectProgressByProduct: 'projectProgressByProduct',
  GetReceiveDrafts: 'receiveDrafts',
  GetMyReceiveDecisions: 'myReceiveDecisions',
};

const PAIRS: [string, string[], string[]][] = [
  ['shipment confirm', refetch.SHIPPING_REFETCH_QUERIES, refetch.SHIPPING_STALE_ROOT_FIELDS],
  ['pick confirm', refetch.PICK_CONFIRM_REFETCH_QUERIES, refetch.PICK_CONFIRM_STALE_ROOT_FIELDS],
  ['pull cancel', refetch.PULL_CANCEL_REFETCH_QUERIES, refetch.PULL_CANCEL_STALE_ROOT_FIELDS],
];

it('refetches a draft list after a draft write and never evicts it in the same breath', () => {
  // A draft write moves nothing in inventory, so the only stale read is the list itself - and one is
  // always mounted, since the write is launched from it.
  expect(refetch.RECEIVE_DRAFT_REFETCH_QUERIES).toContain('GetReceiveDrafts');
  expect(refetch.RECEIVE_APPROVE_REFETCH_QUERIES).toContain('GetReceiveDrafts');
});

it('makes approval inherit the whole meaning of a receive, without refetching anything twice', () => {
  // Approval is where the posting moment went, so everything a receive used to invalidate it now
  // invalidates. The two source lists overlap on the dashboard, and a name listed twice is a query
  // fetched twice.
  for (const op of refetch.RECEIVE_REFETCH_QUERIES) {
    expect(refetch.RECEIVE_APPROVE_REFETCH_QUERIES).toContain(op);
  }
  expect(new Set(refetch.RECEIVE_APPROVE_REFETCH_QUERIES).size).toBe(
    refetch.RECEIVE_APPROVE_REFETCH_QUERIES.length,
  );
});

it('refreshes the drafts and the decisions when the GP outbox drains', () => {
  // A queued approval persists NOTHING until the drain: no receive record, no inventory, and no
  // keep-or-ship decision. The drain is when all three appear, and it lands while the browser is on
  // an arbitrary route - which is exactly what refetchQueries cannot reach.
  expect(refetch.GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS).toContain('receiveDrafts');
  expect(refetch.GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS).toContain('myReceiveDecisions');
});

describe('refetch/evict lists stay disjoint', () => {
  it.each(PAIRS)('%s', (_label, refetched, evicted) => {
    const evictedSet = new Set(evicted);
    const collisions = refetched
      .map((op) => ROOT_FIELD_OF_QUERY[op])
      .filter((field) => field !== undefined && evictedSet.has(field));
    expect(collisions).toEqual([]);
  });
});

it('invalidates the composer whenever a claim moves', () => {
  // `requestCoverage` answers `owed - sent - claimed`, so every moment that moves one of those terms
  // has to evict it. The reader is the Start-a-Request wizard, which is by definition not mounted
  // when a request is accepted, a pull is picked, or a shipment is confirmed - exactly the case
  // refetchQueries cannot reach.
  expect(refetch.RESERVATION_STALE_ROOT_FIELDS).toContain('requestCoverage');
  expect(refetch.PULL_LIFECYCLE_STALE_ROOT_FIELDS).toContain('requestCoverage');
  expect(refetch.PULL_CANCEL_STALE_ROOT_FIELDS).toContain('requestCoverage');
  expect(refetch.SHIPPING_STALE_ROOT_FIELDS).toContain('requestCoverage');
});

it('has no bench-era lists left', () => {
  // Every one of these named a screen the door pipeline owned. Leaving a constant behind would let a
  // call site keep evicting a root field the schema no longer has, which fails silently.
  for (const dead of [
    'PIPELINE_STALE_ROOT_FIELDS',
    'ASSEMBLY_PROGRESS_REFETCH_QUERIES',
    'ASSEMBLY_PROGRESS_STALE_ROOT_FIELDS',
    'ASSEMBLY_COMPLETE_STALE_ROOT_FIELDS',
    'ASSIGNMENT_STALE_ROOT_FIELDS',
    'REPLACEMENT_INSTALL_REFETCH_QUERIES',
    'REPLACEMENT_INSTALL_STALE_ROOT_FIELDS',
    'PULL_STAGING_REFETCH_QUERIES',
    'PULL_STAGING_STALE_ROOT_FIELDS',
  ]) {
    expect(dead in refetch).toBe(false);
  }
});

it('refetches the shipments list after a confirm rather than evicting it', () => {
  // A confirm adds a row, which normalisation cannot deliver to a watcher that never held the new
  // entity. Refetch, not evict: ShipmentsList may be mounted, and eviction empties it for a beat.
  expect(refetch.SHIPPING_REFETCH_QUERIES).toContain('GetPackingSlips');
  expect(refetch.SHIPPING_STALE_ROOT_FIELDS).not.toContain('packingSlips');
});

it('refreshes the receiving history when the GP outbox drains', () => {
  // The row and the panel behind it are one reading: the expanded receives and the count on the row
  // come from different queries, so evicting one without the other makes them disagree.
  expect(refetch.GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS).toContain('receivingHistoryPos');
  expect(refetch.GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS).toContain('poReceivingDetails');
});

it('invalidates both request queues when a pull is cancelled', () => {
  // Cancelling returns the source request to PENDING, and that is true of either source. Both
  // queues live on routes that are not mounted at cancel time, so both have to be evicted.
  expect(refetch.PULL_CANCEL_STALE_ROOT_FIELDS).toContain('shopAssemblyRequests');
  expect(refetch.PULL_CANCEL_STALE_ROOT_FIELDS).toContain('shippingOutRequests');
});
