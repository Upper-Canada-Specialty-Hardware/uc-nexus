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
  GetAssembleList: 'assembleList',
  GetMyWork: 'myWork',
  GetReplacementWork: 'replacementWork',
  GetPullRequests: 'pullRequests',
  GetOpeningLeafStatus: 'openingLeafStatus',
  GetPackingSlips: 'packingSlips',
  GetInventoryHierarchy: 'inventoryHierarchy',
  GetInventoryByVendor: 'inventoryByVendor',
  GetUnlocatedInventory: 'unlocatedInventory',
  GetStockItems: 'stockItems',
  GetDeficientItems: 'deficientItems',
  GetDeficiencyReviews: 'deficiencyReviews',
  GetWarehouseDashboard: 'warehouseDashboard',
  GetProjectProgressByProduct: 'projectProgressByProduct',
};

const PAIRS: [string, string[], string[]][] = [
  ['shipment confirm', refetch.SHIPPING_REFETCH_QUERIES, refetch.SHIPPING_STALE_ROOT_FIELDS],
  ['assembly progress save', refetch.ASSEMBLY_PROGRESS_REFETCH_QUERIES, refetch.PIPELINE_STALE_ROOT_FIELDS],
  [
    'replacement install',
    refetch.REPLACEMENT_INSTALL_REFETCH_QUERIES,
    refetch.REPLACEMENT_INSTALL_STALE_ROOT_FIELDS,
  ],
  ['pull staging', refetch.PULL_STAGING_REFETCH_QUERIES, refetch.PULL_STAGING_STALE_ROOT_FIELDS],
  ['pull cancel', refetch.PULL_CANCEL_REFETCH_QUERIES, refetch.PULL_CANCEL_STALE_ROOT_FIELDS],
];

describe('refetch/evict lists stay disjoint', () => {
  it.each(PAIRS)('%s', (_label, refetched, evicted) => {
    const evictedSet = new Set(evicted);
    const collisions = refetched
      .map((op) => ROOT_FIELD_OF_QUERY[op])
      .filter((field) => field !== undefined && evictedSet.has(field));
    expect(collisions).toEqual([]);
  });
});

it('refetches the Assemble List after a progress save rather than evicting it', () => {
  // The modal is rendered from a row of `assembleList`, and the manager board reads the same query,
  // so evicting the field empties it for every mounted watcher and unmounts the modal mid-save.
  expect(refetch.ASSEMBLY_PROGRESS_REFETCH_QUERIES).toContain('GetAssembleList');
  expect(refetch.PIPELINE_STALE_ROOT_FIELDS).not.toContain('assembleList');
  // The constant that used to carry that eviction is gone for good.
  expect('ASSEMBLY_PROGRESS_STALE_ROOT_FIELDS' in refetch).toBe(false);
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
