import { describe, it, expect } from 'vitest';
import { buildPoDrafts } from '../poDrafts';
import type { DraftGroup, AggregatedHardwareItem } from '../types';

function hw(
  opening: string,
  product: string,
  qty: number,
  opts: { category?: string; unitCost?: number; vendor?: string } = {},
): AggregatedHardwareItem {
  return {
    opening_number: opening,
    product_code: product,
    leaf: null,
    hardware_category: opts.category ?? 'HINGE',
    item_quantity: qty,
    unit_cost: opts.unitCost ?? 10,
    unit_price: null,
    list_price: null,
    vendor_discount: null,
    markup_pct: null,
    vendor_no: opts.vendor ?? 'VEND-A',
    manufacturer: null,
    phase_code: null,
    item_category_code: null,
    product_group_code: null,
    submittal_id: null,
  };
}

function draft(id: string, lines: Record<string, number>, included = true): DraftGroup {
  return {
    id,
    label: id,
    included,
    info: { notes: '', preferredDeliveryDate: '', costCode: '' },
    lines: new Map(Object.entries(lines)),
  };
}

describe('buildPoDrafts', () => {
  it('claims a whole opening with quantity=null (the pre-#570 behaviour)', () => {
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 3)]]]);
    const drafts = buildPoDrafts([draft('a', { 'HG-100|HINGE': 3 })], vendorGroups, new Map());
    expect(drafts).toHaveLength(1);
    expect(drafts[0].hardwareItemRefs).toEqual([
      { openingNumber: 'O-1', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: null },
    ]);
  });

  it('apportions a line across openings, partial on the boundary opening', () => {
    // 3 requested, O-1 holds 2 (taken whole), O-2 the remaining 1 (partial).
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 2), hw('O-2', 'HG-100', 3)]]]);
    const drafts = buildPoDrafts([draft('a', { 'HG-100|HINGE': 3 })], vendorGroups, new Map());
    expect(drafts[0].hardwareItemRefs).toEqual([
      { openingNumber: 'O-1', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: null },
      { openingNumber: 'O-2', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: 1 },
    ]);
  });

  it('splits one product across two drafts, partitioning the boundary opening', () => {
    // HG-100: O-1=2, O-2=3, O-3=1 (total 6). Draft A takes 3, draft B takes 3. O-2 straddles them:
    // A gets 1 of it, B the other 2. The refs for O-2 across the two drafts sum to its total, 3.
    const vendorGroups = new Map([
      ['VEND-A', [hw('O-1', 'HG-100', 2), hw('O-2', 'HG-100', 3), hw('O-3', 'HG-100', 1)]],
    ]);
    const drafts = buildPoDrafts(
      [draft('a', { 'HG-100|HINGE': 3 }), draft('b', { 'HG-100|HINGE': 3 })],
      vendorGroups,
      new Map(),
    );
    expect(drafts[0].hardwareItemRefs).toEqual([
      { openingNumber: 'O-1', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: null },
      { openingNumber: 'O-2', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: 1 },
    ]);
    expect(drafts[1].hardwareItemRefs).toEqual([
      { openingNumber: 'O-2', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: 2 },
      { openingNumber: 'O-3', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: null },
    ]);
  });

  it('skips drafts that are not included, and their units are simply not referenced', () => {
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 2), hw('O-2', 'HG-100', 2)]]]);
    const drafts = buildPoDrafts(
      [draft('a', { 'HG-100|HINGE': 2 }, false), draft('b', { 'HG-100|HINGE': 2 }, true)],
      vendorGroups,
      new Map(),
    );
    // Only draft B is built; it claims from the first opening (the excluded draft consumes no cursor).
    expect(drafts).toHaveLength(1);
    expect(drafts[0].hardwareItemRefs).toEqual([
      { openingNumber: 'O-1', productCode: 'HG-100', hardwareCategory: 'HINGE', quantity: null },
    ]);
  });

  it('drops an included draft that ended up empty', () => {
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 2)]]]);
    const drafts = buildPoDrafts([draft('a', {}, true), draft('b', { 'HG-100|HINGE': 2 })], vendorGroups, new Map());
    expect(drafts).toHaveLength(1);
    expect(drafts[0].notes).toBeNull();
  });

  it('attaches order-as aliases per productKey and carries the draft info', () => {
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 2)]]]);
    const orderAs = new Map([['HG-100|HINGE', 'ACME-9000']]);
    const d = draft('a', { 'HG-100|HINGE': 2 });
    d.info = { notes: 'rush', preferredDeliveryDate: '2026-09-01', costCode: 'CC-1' };
    const drafts = buildPoDrafts([d], vendorGroups, orderAs);
    expect(drafts[0].notes).toBe('rush');
    expect(drafts[0].preferredDeliveryDate).toBe('2026-09-01');
    expect(drafts[0].costCode).toBe('CC-1');
    expect(drafts[0].lineItemAliases).toEqual([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', orderAs: 'ACME-9000' },
    ]);
  });

  it('carries the source draft id on every emitted payload, in draftGroups order (#588)', () => {
    const vendorGroups = new Map([['VEND-A', [hw('O-1', 'HG-100', 2), hw('O-2', 'HG-100', 2)]]]);
    const drafts = buildPoDrafts(
      [draft('a', { 'HG-100|HINGE': 2 }), draft('skip', {}, true), draft('b', { 'HG-100|HINGE': 2 })],
      vendorGroups,
      new Map(),
    );
    // The empty 'skip' draft is dropped, so the emitted order is a, b - the same order finalize
    // returns the created POs in, which is what the doc-upload mapping relies on.
    expect(drafts.map((d) => d.sourceDraftId)).toEqual(['a', 'b']);
  });

  it('conserves each product total across the refs of every included draft', () => {
    const vendorGroups = new Map([
      ['VEND-A', [hw('O-1', 'HG-100', 2), hw('O-2', 'HG-100', 3), hw('O-3', 'HG-100', 1)]],
    ]);
    const drafts = buildPoDrafts(
      [draft('a', { 'HG-100|HINGE': 4 }), draft('b', { 'HG-100|HINGE': 2 })],
      vendorGroups,
      new Map(),
    );
    // Every ref's effective quantity (null = the whole opening) summed per opening equals the schedule.
    const openingTotals: Record<string, number> = { 'O-1': 2, 'O-2': 3, 'O-3': 1 };
    const claimed: Record<string, number> = {};
    for (const d of drafts) {
      for (const ref of d.hardwareItemRefs) {
        const amount = ref.quantity ?? openingTotals[ref.openingNumber];
        claimed[ref.openingNumber] = (claimed[ref.openingNumber] ?? 0) + amount;
      }
    }
    expect(claimed).toEqual(openingTotals);
  });
});
