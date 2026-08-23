import { describe, it, expect } from 'vitest';
import { seedDraftGroups, draftSeedSignature } from '../types';
import type { AggregatedHardwareItem } from '../types';
import { buildPoDrafts } from '../poDrafts';

function hw(opening: string, product: string, qty: number, category = 'HINGE'): AggregatedHardwareItem {
  return {
    opening_number: opening,
    product_code: product,
    leaf: null,
    hardware_category: category,
    item_quantity: qty,
    unit_cost: 10,
    unit_price: null,
    list_price: null,
    vendor_discount: null,
    markup_pct: null,
    vendor_no: 'VEND-A',
    manufacturer: null,
    phase_code: null,
    item_category_code: null,
    product_group_code: null,
    submittal_id: null,
  };
}

// One product HNG over two openings (3 + 2 = 5). productKey is `product|category`; the Order Qty
// override is keyed by itemGroupKey `category|product`, so the seed translates between them.
const vendorGroups = () =>
  new Map<string, AggregatedHardwareItem[]>([['VEND-A', [hw('O-1', 'HNG', 3), hw('O-2', 'HNG', 2)]]]);
const PK = 'HNG|HINGE';
const IGK = 'HINGE|HNG';

describe('seedDraftGroups - Order Qty overrides (#627)', () => {
  it('seeds the full schedule total when there is no override', () => {
    const [group] = seedDraftGroups(vendorGroups());
    expect(group.lines.get(PK)).toBe(5);
  });

  it('empty override map leaves the seed at the full total', () => {
    const [group] = seedDraftGroups(vendorGroups(), new Map());
    expect(group.lines.get(PK)).toBe(5);
  });

  it('caps the seeded line at the override', () => {
    const [group] = seedDraftGroups(vendorGroups(), new Map([[IGK, 3]]));
    expect(group.lines.get(PK)).toBe(3);
  });

  it('never seeds above the schedule total even if the override is larger', () => {
    const [group] = seedDraftGroups(vendorGroups(), new Map([[IGK, 99]]));
    expect(group.lines.get(PK)).toBe(5);
  });
});

describe('draftSeedSignature - Order Qty overrides (#627)', () => {
  it('changes when an override changes, so the drafts re-seed', () => {
    const base = draftSeedSignature(vendorGroups());
    const capped = draftSeedSignature(vendorGroups(), new Map([[IGK, 3]]));
    expect(capped).not.toBe(base);
    // A no-op override (equal to the total) leaves the signature unchanged.
    const noop = draftSeedSignature(vendorGroups(), new Map([[IGK, 5]]));
    expect(noop).toBe(base);
  });
});

describe('seedDraftGroups - override across multiple manufacturers (#627)', () => {
  // Same product (itemGroupKey LOCK|LCK) split across two manufacturers: 6 under SARGENT, 4 under
  // Schlage (product total 10). The override must cap the TOTAL, not each vendor line independently.
  const twoVendors = () =>
    new Map<string, AggregatedHardwareItem[]>([
      ['SARGENT', [hw('O1', 'LCK', 6, 'LOCK')]],
      ['Schlage', [hw('O2', 'LCK', 4, 'LOCK')]],
    ]);
  const lineOf = (groups: ReturnType<typeof seedDraftGroups>) =>
    Object.fromEntries(groups.map((g) => [g.label, g.lines.get('LCK|LOCK') ?? 0]));

  it('caps the total across vendor groups, not per group', () => {
    const groups = seedDraftGroups(twoVendors(), new Map([['LOCK|LCK', 5]]));
    const total = groups.reduce((s, g) => s + [...g.lines.values()].reduce((a, b) => a + b, 0), 0);
    expect(total).toBe(5); // NOT min(5,6)+min(5,4)=9
    // Greedy in vendor order: SARGENT takes 5 of its 6, Schlage's line is dropped.
    expect(lineOf(groups)).toEqual({ SARGENT: 5, Schlage: 0 });
  });

  it('fills the second vendor with the remaining budget', () => {
    // Override 8 across SARGENT(6) + Schlage(4): SARGENT full 6, Schlage min(4, 2)=2 -> total 8.
    const groups = seedDraftGroups(twoVendors(), new Map([['LOCK|LCK', 8]]));
    expect(lineOf(groups)).toEqual({ SARGENT: 6, Schlage: 2 });
  });

  it('the signature reflects the distributed quantities', () => {
    const base = draftSeedSignature(twoVendors());
    const capped = draftSeedSignature(twoVendors(), new Map([['LOCK|LCK', 5]]));
    expect(capped).not.toBe(base);
  });
});

describe('buildPoDrafts on an override-capped seed (#627)', () => {
  it('claims only the override, leaving the remainder unclaimed for AVAILABLE', () => {
    const groups = vendorGroups();
    const [seeded] = seedDraftGroups(groups, new Map([[IGK, 3]]));
    const drafts = buildPoDrafts([{ ...seeded, included: true }], groups, new Map());

    expect(drafts).toHaveLength(1);
    // The three claimed units come off O-1 (qty 3, whole, so quantity is null) - O-2's two units are
    // never referenced, so the backend persists them AVAILABLE. Claimed total (3) equals the override.
    expect(drafts[0].hardwareItemRefs).toEqual([
      { openingNumber: 'O-1', productCode: 'HNG', hardwareCategory: 'HINGE', quantity: null },
    ]);
  });
});
