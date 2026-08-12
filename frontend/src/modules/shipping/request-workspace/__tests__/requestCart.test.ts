import { describe, it, expect } from 'vitest';
import {
  addScheduleRowAtSuggested,
  buildRequestItems,
  cartGroups,
  headroomByProduct,
  heldByRequest,
  removeLine,
  setLineQuantity,
  takeAllFreeLoose,
  type CartLine,
} from '../requestCart';
import type { CoverageRow } from '../../../import/composer';

const HINGE = { hardwareCategory: 'HINGE', productCode: 'HG-100' };
const KEY = 'HINGE|HG-100';

function coverage(overrides: Partial<CoverageRow> = {}): CoverageRow {
  return {
    openingNumber: 'A01',
    hardwareCategory: 'HINGE',
    productCode: 'HG-100',
    classification: 'SITE_HARDWARE',
    owedQuantity: 6,
    sentQuantity: 0,
    claimedQuantity: 0,
    suggestedQuantity: 6,
    onOrderQuantity: 0,
    ...overrides,
  };
}

describe('headroom and the per-product invariant', () => {
  it('caps the sum of ALL cart lines for a product at what is free, across schedule and loose', () => {
    // 10 hinges free, no prior hold. A schedule line for A01 and a loose line share the one pool.
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    let lines: CartLine[] = [];

    // Add 6 to opening A01 off the schedule.
    lines = setLineQuantity(lines, { ...HINGE, openingNumber: 'A01' }, 6, headroom);
    // A loose add now sees only 4 left, even though it asks for 10.
    lines = setLineQuantity(lines, { ...HINGE, openingNumber: null }, 10, headroom);

    const total = lines.reduce((s, l) => s + l.quantity, 0);
    expect(total).toBe(10);
    expect(lines.find((l) => l.openingNumber === null)?.quantity).toBe(4);
  });

  it('lets a line be re-typed up to the ceiling, not capped by what it already holds', () => {
    const headroom = headroomByProduct(new Map([[KEY, 8]]), new Map());
    let lines = setLineQuantity([], { ...HINGE, openingNumber: 'A01' }, 5, headroom);
    // Re-typing the same line to 8 is allowed - its own 5 is not counted against it.
    lines = setLineQuantity(lines, { ...HINGE, openingNumber: 'A01' }, 8, headroom);
    expect(lines[0].quantity).toBe(8);
  });

  it('adds a loose line only up to the free remainder when a schedule line is already down', () => {
    const headroom = headroomByProduct(new Map([[KEY, 7]]), new Map());
    let lines = setLineQuantity([], { ...HINGE, openingNumber: 'A01' }, 5, headroom);
    lines = takeAllFreeLoose(lines, HINGE, headroom);
    expect(lines.find((l) => l.openingNumber === null)?.quantity).toBe(2);
  });

  it('treats a product with no availability as a ceiling of zero', () => {
    const headroom = headroomByProduct(new Map(), new Map());
    const lines = setLineQuantity([], { ...HINGE, openingNumber: 'A01' }, 5, headroom);
    expect(lines).toEqual([]);
  });
});

describe('edit-mode add-back', () => {
  it('adds back every held line of a product so an edit can keep what it is sitting on', () => {
    // Availability is net of BOTH held lines (3 + 2). Free is 6. Held total is 5, so the ceiling
    // for the product is 11 - the request can grow back to everything it had plus the free stock.
    const held = heldByRequest([
      { hardwareCategory: 'HINGE', productCode: 'HG-100', requestedQuantity: 3 },
      { hardwareCategory: 'HINGE', productCode: 'HG-100', requestedQuantity: 2 },
    ]);
    const headroom = headroomByProduct(new Map([[KEY, 6]]), held);
    expect(headroom.get(KEY)).toBe(11);

    const lines = setLineQuantity([], { ...HINGE, openingNumber: 'A01' }, 11, headroom);
    expect(lines[0].quantity).toBe(11);
    // One over the ceiling is refused.
    const over = setLineQuantity([], { ...HINGE, openingNumber: 'A01' }, 12, headroom);
    expect(over[0].quantity).toBe(11);
  });

  it('a new request has no add-back, so the ceiling is just what is free', () => {
    const headroom = headroomByProduct(new Map([[KEY, 6]]), heldByRequest([]));
    expect(headroom.get(KEY)).toBe(6);
  });
});

describe('adding schedule rows at suggested', () => {
  it('adds a schedule row at its suggestion when the pool covers it', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const lines = addScheduleRowAtSuggested([], coverage({ suggestedQuantity: 6 }), headroom);
    expect(lines).toEqual([{ openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 6 }]);
  });

  it('clamps a schedule add to the free remainder rather than the raw suggestion', () => {
    const headroom = headroomByProduct(new Map([[KEY, 4]]), new Map());
    const lines = addScheduleRowAtSuggested([], coverage({ suggestedQuantity: 6 }), headroom);
    expect(lines[0].quantity).toBe(4);
  });

  it('a suggested-zero row adds nothing', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const lines = addScheduleRowAtSuggested([], coverage({ suggestedQuantity: 0 }), headroom);
    expect(lines).toEqual([]);
  });
});

describe('cart shape and submission', () => {
  it('groups by product with opening lines before the loose one, and flags an over-commit', () => {
    const lines: CartLine[] = [
      { openingNumber: null, hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 2 },
      { openingNumber: 'A02', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 },
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 },
    ];
    // Ceiling of 6 but the cart holds 8 - a persisted draft the pool moved under.
    const groups = cartGroups(lines, new Map([[KEY, 6]]));
    expect(groups).toHaveLength(1);
    expect(groups[0].lines.map((l) => l.openingNumber)).toEqual(['A01', 'A02', null]);
    expect(groups[0].total).toBe(8);
    expect(groups[0].overCommitted).toBe(true);
  });

  it('drops zero and empty lines from the submitted payload, keeping null openings for loose', () => {
    const items = buildRequestItems([
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 2 },
      { openingNumber: null, hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 1 },
      { openingNumber: 'A03', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 0 },
    ]);
    expect(items).toEqual([
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', requestedQuantity: 2 },
      { openingNumber: null, hardwareCategory: 'HINGE', productCode: 'HG-100', requestedQuantity: 1 },
    ]);
  });

  it('removes a line by its opening identity, leaving the same product on other openings', () => {
    const lines: CartLine[] = [
      { openingNumber: 'A01', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 },
      { openingNumber: 'A02', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 },
    ];
    const next = removeLine(lines, { ...HINGE, openingNumber: 'A01' });
    expect(next).toEqual([{ openingNumber: 'A02', hardwareCategory: 'HINGE', productCode: 'HG-100', quantity: 3 }]);
  });
});
