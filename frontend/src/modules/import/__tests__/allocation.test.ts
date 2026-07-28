import {
  allocatedFor,
  autoAssign,
  buildAllocatedDrafts,
  clampCeiling,
  comboSummary,
  draftsSignature,
  leafAllocatedTotal,
  leafCoverage,
  leafKey,
  remainingPool,
  setLineAllocation,
  type ShopAssemblyOpeningDraft,
} from '../allocation';

/**
 * The assignment rules behind the shop-assembly allocator.
 *
 * These are the numbers the requester is held to and the numbers the server reserves against, so
 * they are worth pinning down without rendering anything. The single property everything else hangs
 * off: a leaf never gets more than it is owed, and the combos never hand out more than is available.
 */

const draft = (
  openingNumber: string,
  items: Array<[string, string, number]>,
  leaf: number | null = 1,
): ShopAssemblyOpeningDraft => ({
  openingNumber,
  leaf,
  items: items.map(([hardwareCategory, productCode, quantity]) => ({
    hardwareCategory,
    productCode,
    quantity,
  })),
});

const pool = (entries: Array<[string, number]>) => new Map(entries);
const allKeys = (drafts: ShopAssemblyOpeningDraft[]) => new Set(drafts.map((d) => leafKey(d)));

describe('autoAssign', () => {
  it('gives every leaf its full owed quantity when the pool covers everything', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 8]]));
    expect(leafAllocatedTotal(allocation, drafts[0])).toBe(4);
    expect(leafAllocatedTotal(allocation, drafts[1])).toBe(4);
    expect(drafts.map((d) => leafCoverage(allocation, d))).toEqual(['FULL', 'FULL']);
  });

  it('fills whole leaves in schedule order rather than spreading scarcity across all of them', () => {
    // 6 hinges, 3 leaves wanting 4 each. Spreading gives three unassemblable half-leaves; filling in
    // order gives one finished leaf, one partial and one that is simply not sent.
    const drafts = [
      draft('A01', [['HINGE', 'HG-100', 4]]),
      draft('A02', [['HINGE', 'HG-100', 4]]),
      draft('A03', [['HINGE', 'HG-100', 4]]),
    ];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 6]]));
    expect(drafts.map((d) => leafAllocatedTotal(allocation, d))).toEqual([4, 2, 0]);
    expect(drafts.map((d) => leafCoverage(allocation, d))).toEqual(['FULL', 'PARTIAL', 'NONE']);
  });

  it('allocates nothing when the pool is empty, and reports every leaf as not covered', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 0]]));
    expect(leafAllocatedTotal(allocation, drafts[0])).toBe(0);
    expect(leafCoverage(allocation, drafts[0])).toBe('NONE');
  });

  it('treats a combo with no availability row as zero, not as unlimited', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    expect(leafAllocatedTotal(autoAssign(drafts, pool([])), drafts[0])).toBe(0);
  });

  it('keeps combos independent - one running out does not starve another', () => {
    const drafts = [
      draft('A01', [
        ['HINGE', 'HG-100', 4],
        ['CLOSER', 'CL-1', 1],
      ]),
      draft('A02', [
        ['HINGE', 'HG-100', 4],
        ['CLOSER', 'CL-1', 1],
      ]),
    ];
    const allocation = autoAssign(
      drafts,
      pool([
        ['HINGE|HG-100', 4],
        ['CLOSER|CL-1', 2],
      ]),
    );
    expect(allocatedFor(allocation, drafts[1], drafts[1].items[0])).toBe(0);
    expect(allocatedFor(allocation, drafts[1], drafts[1].items[1])).toBe(1);
    // A leaf with one line covered and one not is PARTIAL, not NONE - it still has a cart to build.
    expect(leafCoverage(allocation, drafts[1])).toBe('PARTIAL');
  });

  it('never hands a leaf more than it is owed, even with stock to spare', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 2]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 99]]));
    expect(leafAllocatedTotal(allocation, drafts[0])).toBe(2);
  });

  it('is deterministic - the same inputs give the same allocation', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 3]]), draft('A02', [['HINGE', 'HG-100', 3]])];
    const first = autoAssign(drafts, pool([['HINGE|HG-100', 4]]));
    const second = autoAssign(drafts, pool([['HINGE|HG-100', 4]]));
    expect(drafts.map((d) => leafAllocatedTotal(first, d))).toEqual(
      drafts.map((d) => leafAllocatedTotal(second, d)),
    );
  });

  it('distinguishes the two leaves of a pair', () => {
    // Same opening number, different leaves: two work units, two carts, two allocations.
    const drafts = [
      draft('A01', [['HINGE', 'HG-100', 2]], 1),
      draft('A01', [['HINGE', 'HG-100', 2]], 2),
    ];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 3]]));
    expect(drafts.map((d) => leafAllocatedTotal(allocation, d))).toEqual([2, 1]);
  });
});

describe('remainingPool', () => {
  it('counts only the included leaves, so an excluded one hands its hardware back', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const available = pool([['HINGE|HG-100', 6]]);
    const allocation = autoAssign(drafts, available);
    expect(remainingPool(drafts, allocation, available, allKeys(drafts)).get('HINGE|HG-100')).toBe(0);
    // Drop A01 and its 4 units are assignable again.
    const withoutFirst = new Set([leafKey(drafts[1])]);
    expect(remainingPool(drafts, allocation, available, withoutFirst).get('HINGE|HG-100')).toBe(4);
  });
});

describe('clampCeiling', () => {
  it('never exceeds what the line is owed', () => {
    expect(clampCeiling(4, 2, 99)).toBe(4);
  });

  it('never exceeds what the line holds plus what is left in the pool', () => {
    expect(clampCeiling(10, 2, 3)).toBe(5);
  });

  it('holds at the current value when the pool is empty', () => {
    expect(clampCeiling(10, 2, 0)).toBe(2);
  });

  it('does not go negative on an over-drawn pool', () => {
    expect(clampCeiling(10, 0, -5)).toBe(0);
  });
});

describe('setLineAllocation', () => {
  it('clamps a raise to what is actually assignable', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 2]]));
    const next = setLineAllocation(allocation, drafts[0], drafts[0].items[0], 4, 0);
    expect(allocatedFor(next, drafts[0], drafts[0].items[0])).toBe(2);
  });

  it('allows lowering freely, and floors at zero', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 4]]));
    const next = setLineAllocation(allocation, drafts[0], drafts[0].items[0], -3, 0);
    expect(allocatedFor(next, drafts[0], drafts[0].items[0])).toBe(0);
  });

  it('does not mutate the allocation it was given', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const allocation = autoAssign(drafts, pool([['HINGE|HG-100', 4]]));
    setLineAllocation(allocation, drafts[0], drafts[0].items[0], 1, 0);
    expect(allocatedFor(allocation, drafts[0], drafts[0].items[0])).toBe(4);
  });
});

describe('comboSummary', () => {
  it('totals owed, allocated, what is left and what is short across the included leaves', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const available = pool([['HINGE|HG-100', 6]]);
    const rows = comboSummary(drafts, autoAssign(drafts, available), available, allKeys(drafts));
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ owed: 8, available: 6, allocated: 6, remaining: 0, short: 2 });
  });

  it('does not count an excluded leaf as short - it is not in the request at all', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const available = pool([['HINGE|HG-100', 6]]);
    const allocation = autoAssign(drafts, available);
    const rows = comboSummary(drafts, allocation, available, new Set([leafKey(drafts[0])]));
    expect(rows[0]).toMatchObject({ owed: 4, allocated: 4, short: 0, remaining: 2 });
  });
});

describe('buildAllocatedDrafts', () => {
  it('sends owed and allocated per line, and drops leaves with nothing on them', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const payload = buildAllocatedDrafts(drafts, autoAssign(drafts, pool([['HINGE|HG-100', 4]])), allKeys(drafts));
    expect(payload).toHaveLength(1);
    expect(payload[0].openingNumber).toBe('A01');
    expect(payload[0].items[0]).toMatchObject({ quantity: 4, allocatedQuantity: 4 });
  });

  it('keeps a zero line on a leaf that other lines cover, so the checklist stays whole', () => {
    // Owed is the schedule's number and the leaf still takes that closer; it just did not get one.
    const drafts = [
      draft('A01', [
        ['HINGE', 'HG-100', 2],
        ['CLOSER', 'CL-1', 1],
      ]),
    ];
    const payload = buildAllocatedDrafts(
      drafts,
      autoAssign(drafts, pool([['HINGE|HG-100', 2]])),
      allKeys(drafts),
    );
    expect(payload[0].items).toHaveLength(2);
    expect(payload[0].items[1]).toMatchObject({ productCode: 'CL-1', quantity: 1, allocatedQuantity: 0 });
  });

  it('drops a leaf the user excluded even though it is fully covered', () => {
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]])];
    expect(buildAllocatedDrafts(drafts, autoAssign(drafts, pool([['HINGE|HG-100', 4]])), new Set())).toEqual([]);
  });
});

describe('comboSummary and buildAllocatedDrafts agree on what is being sent', () => {
  it('does not count a leaf steppered down to zero as short', () => {
    // Its toggle is disabled and buildAllocatedDrafts drops it, so the server never learns its owed
    // quantities. Reporting them as short would show the user a shortfall purchasing is never told
    // about - the two readings have to describe the same request.
    const drafts = [draft('A01', [['HINGE', 'HG-100', 4]]), draft('A02', [['HINGE', 'HG-100', 4]])];
    const available = pool([['HINGE|HG-100', 8]]);
    let allocation = autoAssign(drafts, available);
    allocation = setLineAllocation(allocation, drafts[1], drafts[1].items[0], 0, 4);

    const rows = comboSummary(drafts, allocation, available, allKeys(drafts));
    expect(rows[0]).toMatchObject({ owed: 4, allocated: 4, short: 0 });
    expect(buildAllocatedDrafts(drafts, allocation, allKeys(drafts))).toHaveLength(1);
  });
});

describe('draftsSignature', () => {
  it('is stable across rebuilt draft objects, so stepping away and back does not re-seed', () => {
    const first = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const second = [draft('A01', [['HINGE', 'HG-100', 4]])];
    expect(draftsSignature(first)).toBe(draftsSignature(second));
  });

  it('changes when a leaf is added, so a new selection does get re-seeded', () => {
    const before = [draft('A01', [['HINGE', 'HG-100', 4]])];
    const after = [...before, draft('A02', [['HINGE', 'HG-100', 4]])];
    expect(draftsSignature(before)).not.toBe(draftsSignature(after));
  });

  it('changes when an owed quantity changes', () => {
    expect(draftsSignature([draft('A01', [['HINGE', 'HG-100', 4]])])).not.toBe(
      draftsSignature([draft('A01', [['HINGE', 'HG-100', 5]])]),
    );
  });

  it('does not depend on the order leaves arrive in', () => {
    const a = draft('A01', [['HINGE', 'HG-100', 2]]);
    const b = draft('A02', [['HINGE', 'HG-100', 2]]);
    expect(draftsSignature([a, b])).toBe(draftsSignature([b, a]));
  });
});
