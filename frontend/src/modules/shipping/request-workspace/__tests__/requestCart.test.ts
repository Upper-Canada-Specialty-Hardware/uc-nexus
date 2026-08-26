import { describe, it, expect } from 'vitest';
import {
  addScheduleRowAtSuggested,
  aggregateCoverageByProduct,
  buildRequestItems,
  cartGroups,
  headroomByProduct,
  heldByRequest,
  productLinesQuantity,
  removeLine,
  setLineQuantity,
  setProductQuantity,
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
    assembledQuantity: 0,
    shippedQuantity: 0,
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

// ---- #632: one product-level row per product, and the single quantity field behind it ----

/** The cart's lines as `{ opening | 'loose': qty }` - a distribution reads at a glance. Only used on
 *  single-product carts, where the opening alone identifies the line. */
function shape(lines: CartLine[]): Record<string, number> {
  return Object.fromEntries(lines.map((l) => [l.openingNumber ?? 'loose', l.quantity]));
}

/** Two openings of the one product, each owing its own quantity - the aggregate's `rows`. */
function twoOpenings(a: number, b: number): CoverageRow[] {
  return [
    coverage({ openingNumber: 'A01', suggestedQuantity: a, owedQuantity: a }),
    coverage({ openingNumber: 'A02', suggestedQuantity: b, owedQuantity: b }),
  ];
}

describe('aggregateCoverageByProduct', () => {
  it('sums every per-opening column across the openings behind one product', () => {
    const [agg] = aggregateCoverageByProduct([
      coverage({
        openingNumber: 'A01',
        owedQuantity: 6,
        assembledQuantity: 1,
        shippedQuantity: 2,
        claimedQuantity: 1,
        suggestedQuantity: 3,
      }),
      coverage({
        openingNumber: 'A02',
        owedQuantity: 4,
        assembledQuantity: 2,
        shippedQuantity: 0,
        claimedQuantity: 1,
        suggestedQuantity: 1,
      }),
    ]);
    expect(agg.requiredQuantity).toBe(10);
    expect(agg.assembledQuantity).toBe(3);
    expect(agg.shippedQuantity).toBe(2);
    expect(agg.claimedQuantity).toBe(2);
    expect(agg.suggestedQuantity).toBe(4);
    expect(agg.key).toBe(KEY);
  });

  it('takes on-order from the first row and NEVER sums it - one PO is not one PO per door', () => {
    // The server reports on-order project-wide per product. Summing it over three openings would
    // report the same purchase order three times.
    const [agg] = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A01', onOrderQuantity: 5 }),
      coverage({ openingNumber: 'A02', onOrderQuantity: 5 }),
      coverage({ openingNumber: 'A03', onOrderQuantity: 5 }),
    ]);
    expect(agg.onOrderQuantity).toBe(5);
  });

  it('keeps the classification the openings agree on', () => {
    const [agg] = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A01', classification: 'SHOP_HARDWARE' }),
      coverage({ openingNumber: 'A02', classification: 'SHOP_HARDWARE' }),
    ]);
    expect(agg.classification).toBe('SHOP_HARDWARE');
  });

  it('collapses the classification to null when the openings disagree - no chip beats a wrong chip', () => {
    const [agg] = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A01', classification: 'SITE_HARDWARE' }),
      coverage({ openingNumber: 'A02', classification: 'SHOP_HARDWARE' }),
      coverage({ openingNumber: 'A03', classification: 'SITE_HARDWARE' }),
    ]);
    expect(agg.classification).toBeNull();
  });

  it('an unclassified opening among classified ones also collapses to null', () => {
    const [agg] = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A01', classification: 'SITE_HARDWARE' }),
      coverage({ openingNumber: 'A02', classification: null }),
    ]);
    expect(agg.classification).toBeNull();
  });

  it('orders the per-opening rows ascending by opening, whatever order they arrived in', () => {
    const [agg] = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A03' }),
      coverage({ openingNumber: 'A01' }),
      coverage({ openingNumber: 'A02' }),
    ]);
    expect(agg.rows.map((r) => r.openingNumber)).toEqual(['A01', 'A02', 'A03']);
  });

  it('splits the rows product-first and sorts the products by category then code', () => {
    const aggs = aggregateCoverageByProduct([
      coverage({ openingNumber: 'A01' }),
      coverage({ openingNumber: 'A01', hardwareCategory: 'LOCK', productCode: 'LK-200' }),
      coverage({ openingNumber: 'A02', hardwareCategory: 'LOCK', productCode: 'LK-200' }),
      coverage({ openingNumber: 'A01', hardwareCategory: 'LOCK', productCode: 'LK-100' }),
    ]);
    expect(aggs.map((a) => a.key)).toEqual(['HINGE|HG-100', 'LOCK|LK-100', 'LOCK|LK-200']);
    expect(aggs[2].rows).toHaveLength(2);
  });

  it('no coverage is no products', () => {
    expect(aggregateCoverageByProduct([])).toEqual([]);
  });
});

describe('productLinesQuantity', () => {
  it("counts only the aggregate's own openings - loose lines and other openings are not its units", () => {
    const rows = twoOpenings(6, 6);
    const lines: CartLine[] = [
      { openingNumber: 'A01', ...HINGE, quantity: 2 },
      { openingNumber: 'A02', ...HINGE, quantity: 3 },
      // An opening outside this selection, the loose lane, and a different product all sit out.
      { openingNumber: 'A09', ...HINGE, quantity: 4 },
      { openingNumber: null, ...HINGE, quantity: 5 },
      { openingNumber: 'A01', hardwareCategory: 'LOCK', productCode: 'LK-200', quantity: 9 },
    ];
    expect(productLinesQuantity(lines, rows)).toBe(5);
  });

  it('is zero when the cart holds none of the product', () => {
    expect(productLinesQuantity([], twoOpenings(6, 6))).toBe(0);
  });
});

describe('setProductQuantity', () => {
  it('fills ascending by opening, each opening capped at its own suggestion', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    // Rows arrive out of order; the fill still runs A01 before A02.
    const rows = [
      coverage({ openingNumber: 'A02', suggestedQuantity: 3 }),
      coverage({ openingNumber: 'A01', suggestedQuantity: 2 }),
    ];
    expect(shape(setProductQuantity([], rows, 4, headroom))).toEqual({ A01: 2, A02: 2 });
  });

  it('never exceeds the summed suggestion, however much stock is free', () => {
    const headroom = headroomByProduct(new Map([[KEY, 100]]), new Map());
    const next = setProductQuantity([], twoOpenings(2, 3), 50, headroom);
    expect(shape(next)).toEqual({ A01: 2, A02: 3 });
  });

  it('caps the whole add at the pool a competing loose line leaves behind', () => {
    // 10 free, but the loose lane is already sitting on 6 of them, so only 4 can be tagged - even
    // though the two openings between them suggest 8.
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const start: CartLine[] = [{ openingNumber: null, ...HINGE, quantity: 6 }];
    const next = setProductQuantity(start, twoOpenings(4, 4), 8, headroom);
    expect(shape(next)).toEqual({ loose: 6, A01: 4 });
  });

  it('counts an opening OUTSIDE the aggregate against the pool too', () => {
    // A09 is not in the selection, so its 7 units are somebody else's claim on the same product.
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const start: CartLine[] = [{ openingNumber: 'A09', ...HINGE, quantity: 7 }];
    const next = setProductQuantity(start, twoOpenings(4, 4), 8, headroom);
    expect(shape(next)).toEqual({ A09: 7, A01: 3 });
  });

  it('lowering then raising the same number lands on exactly the same lines', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const rows = twoOpenings(4, 4);
    const full = setProductQuantity([], rows, 8, headroom);
    expect(shape(full)).toEqual({ A01: 4, A02: 4 });

    // Lowering drains the last opening first, because the fill assigns ascending.
    const lowered = setProductQuantity(full, rows, 3, headroom);
    expect(shape(lowered)).toEqual({ A01: 3 });

    expect(shape(setProductQuantity(lowered, rows, 8, headroom))).toEqual(shape(full));
  });

  it('re-fills from a cart holding only a LATER opening, instead of reading its own units as a rival claim', () => {
    // All 6 free units sit on A02 - added straight off that opening's row, so the lines are not the
    // ascending prefix a product-level add would have left. Asking for 5 must land 5.
    const headroom = headroomByProduct(new Map([[KEY, 6]]), new Map());
    const start: CartLine[] = [{ openingNumber: 'A02', ...HINGE, quantity: 6 }];
    const next = setProductQuantity(start, twoOpenings(6, 6), 5, headroom);
    expect(next.reduce((sum, l) => sum + l.quantity, 0)).toBe(5);
    expect(shape(next)).toEqual({ A01: 5 });
  });

  it('drops a line the redistribution empties rather than leaving a zero on the request', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const rows = twoOpenings(4, 4);
    const next = setProductQuantity(setProductQuantity([], rows, 8, headroom), rows, 4, headroom);
    expect(next.some((l) => l.openingNumber === 'A02')).toBe(false);
    expect(next.every((l) => l.quantity > 0)).toBe(true);
  });

  it('zero clears the product on these openings and leaves the loose line alone', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const rows = twoOpenings(4, 4);
    const start: CartLine[] = [
      { openingNumber: null, ...HINGE, quantity: 2 },
      { openingNumber: 'A01', ...HINGE, quantity: 4 },
      { openingNumber: 'A02', ...HINGE, quantity: 4 },
    ];
    expect(shape(setProductQuantity(start, rows, 0, headroom))).toEqual({ loose: 2 });
  });

  it('keeps every line opening-tagged - the product field is a faster way of writing the same lines', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const next = setProductQuantity([], twoOpenings(4, 4), 6, headroom);
    expect(next.every((l) => l.openingNumber !== null)).toBe(true);
    expect(next.every((l) => l.hardwareCategory === 'HINGE' && l.productCode === 'HG-100')).toBe(true);
  });

  it('a product with no pool takes nothing', () => {
    const headroom = headroomByProduct(new Map(), new Map());
    expect(setProductQuantity([], twoOpenings(4, 4), 8, headroom)).toEqual([]);
  });

  it('a non-numeric quantity reads as zero, and no rows is a no-op', () => {
    const headroom = headroomByProduct(new Map([[KEY, 10]]), new Map());
    const rows = twoOpenings(4, 4);
    const full = setProductQuantity([], rows, 8, headroom);
    expect(setProductQuantity(full, rows, Number.NaN, headroom)).toEqual([]);
    expect(setProductQuantity(full, [], 3, headroom)).toBe(full);
  });
});
