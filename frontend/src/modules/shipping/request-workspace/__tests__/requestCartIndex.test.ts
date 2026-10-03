import { describe, it, expect } from 'vitest';
import {
  cartLineKey,
  indexCart,
  lineQuantity,
  productKey,
  productLinesQuantity,
  remainingForProduct,
  setLineQuantity,
  setProductQuantity,
  type CartLine,
  type Headroom,
} from '../requestCart';
import type { CoverageRow } from '../../../import/composer';

// #1290: the cart is indexed once per render and setProductQuantity builds its cart in one pass.
// Behaviour must not move, so each is checked against the line-by-line version it replaced.

function legacyRemaining(lines: CartLine[], key: string, headroom: Headroom, excludingLineKey?: string): number {
  const ceiling = headroom.get(key) ?? 0;
  let othersHold = 0;
  for (const line of lines) {
    if (productKey(line) !== key) continue;
    if (excludingLineKey !== undefined && cartLineKey(line) === excludingLineKey) continue;
    othersHold += line.quantity;
  }
  return Math.max(0, ceiling - othersHold);
}

function legacyLineQuantity(lines: CartLine[], target: Omit<CartLine, 'quantity'>): number {
  const key = cartLineKey(target);
  return lines.find((line) => cartLineKey(line) === key)?.quantity ?? 0;
}

function legacySetProductQuantity(lines: CartLine[], rows: CoverageRow[], desired: number, headroom: Headroom) {
  if (rows.length === 0) return lines;
  const key = productKey(rows[0]);
  const aggregateKeys = new Set(rows.map((r) => cartLineKey(r)));
  const ceiling = headroom.get(key) ?? 0;
  let othersHold = 0;
  for (const line of lines) {
    if (productKey(line) !== key) continue;
    if (aggregateKeys.has(cartLineKey(line))) continue;
    othersHold += line.quantity;
  }
  const pool = Math.max(0, ceiling - othersHold);
  const suggestedTotal = rows.reduce((sum, r) => sum + r.suggestedQuantity, 0);
  let target = Math.max(0, Math.min(Number.isFinite(desired) ? Math.floor(desired) : 0, pool, suggestedTotal));
  const ordered = [...rows].sort((a, b) => a.openingNumber.localeCompare(b.openingNumber));
  let next = lines;
  for (const row of ordered) next = setLineQuantity(next, row, 0, headroom);
  for (const row of ordered) {
    const take = Math.min(row.suggestedQuantity, target);
    target -= take;
    next = setLineQuantity(next, row, take, headroom);
  }
  return next;
}

function row(opening: string, suggested: number, code = 'HG-100'): CoverageRow {
  return {
    openingNumber: opening,
    hardwareCategory: 'HINGE',
    productCode: code,
    classification: null,
    owedQuantity: suggested,
    sentQuantity: 0,
    assembledQuantity: 0,
    shippedQuantity: 0,
    claimedQuantity: 0,
    suggestedQuantity: suggested,
    onOrderQuantity: 0,
  };
}

const line = (opening: string | null, quantity: number, code = 'HG-100'): CartLine => ({
  openingNumber: opening,
  hardwareCategory: 'HINGE',
  productCode: code,
  quantity,
});

/** A cart shaped like a real composition: ~300 openings across a few products, a loose line, a zero. */
function bigCart(): { lines: CartLine[]; rows: CoverageRow[]; headroom: Headroom } {
  const lines: CartLine[] = [];
  const rows: CoverageRow[] = [];
  for (let i = 0; i < 300; i++) {
    const opening = `A${String(i).padStart(3, '0')}`;
    rows.push(row(opening, (i % 4) + 1));
    if (i % 3 === 0) lines.push(line(opening, (i % 4) + 1));
    lines.push(line(opening, 2, 'LK-9'));
  }
  lines.push(line(null, 5));
  lines.push(line('Z99', 0, 'CL-1'));
  const headroom: Headroom = new Map([
    ['HINGE|HG-100', 600],
    ['HINGE|LK-9', 900],
  ]);
  return { lines, rows, headroom };
}

describe('the cart index answers what a scan answered', () => {
  const cases: CartLine[][] = [
    [],
    [line('A01', 3), line('A02', 2), line(null, 4), line('A01', 1, 'LK-9')],
    // Duplicate keys only arrive from a hand-edited draft, but the answers still must not move.
    [line('A01', 3), line('A01', 5), line(null, 0)],
    bigCart().lines,
  ];
  const headroom: Headroom = new Map([
    ['HINGE|HG-100', 20],
    ['HINGE|LK-9', 7],
  ]);

  it('lineQuantity, remainingForProduct and productLinesQuantity agree with the scan', () => {
    const targets = [line('A01', 0), line('A02', 0), line(null, 0), line('A01', 0, 'LK-9'), line('A150', 0)];
    for (const lines of cases) {
      const index = indexCart(lines);
      for (const target of targets) {
        expect(lineQuantity(index, target)).toBe(legacyLineQuantity(lines, target));
        for (const key of ['HINGE|HG-100', 'HINGE|LK-9', 'HINGE|CL-1']) {
          expect(remainingForProduct(index, key, headroom)).toBe(legacyRemaining(lines, key, headroom));
          expect(remainingForProduct(index, key, headroom, cartLineKey(target))).toBe(
            legacyRemaining(lines, key, headroom, cartLineKey(target)),
          );
        }
      }
      const rows = [row('A01', 2), row('A02', 2), row('A150', 2)];
      const scanned = rows.reduce((s, r) => s + legacyLineQuantity(lines, r), 0);
      expect(productLinesQuantity(index, rows)).toBe(scanned);
      expect(productLinesQuantity(lines, rows)).toBe(scanned);
    }
  });
});

describe('setProductQuantity in one pass matches the line-by-line version', () => {
  const small = [row('A02', 3), row('A01', 4), row('A03', 2)];
  const smallCarts: CartLine[][] = [
    [],
    [line('A03', 2)],
    [line('A01', 1), line(null, 6), line('B01', 2)],
    [line('A02', 3), line('X', 0, 'LK-9'), line('A01', 0)],
    [line(null, 3, 'LK-9')],
  ];
  const headrooms: Headroom[] = [
    new Map([['HINGE|HG-100', 20]]),
    new Map([['HINGE|HG-100', 7]]),
    new Map([['HINGE|HG-100', 0]]),
    new Map(),
  ];
  const desires = [0, 1, 4, 5, 9, 100, -3, 2.7, Number.NaN, Number.POSITIVE_INFINITY];

  it('gives the same cart for every small case', () => {
    for (const lines of smallCarts) {
      for (const headroom of headrooms) {
        for (const desired of desires) {
          expect(setProductQuantity(lines, small, desired, headroom)).toEqual(
            legacySetProductQuantity(lines, small, desired, headroom),
          );
        }
      }
    }
  });

  it('gives the same cart on a large one, raising and lowering', () => {
    const { lines, rows, headroom } = bigCart();
    for (const desired of [0, 1, 150, 449, 750, 10_000]) {
      expect(setProductQuantity(lines, rows, desired, headroom)).toEqual(
        legacySetProductQuantity(lines, rows, desired, headroom),
      );
    }
  });

  it('keeps the old path for two rows on one opening', () => {
    const dup = [row('A01', 3), row('A01', 2)];
    for (const desired of [0, 2, 5]) {
      expect(setProductQuantity([line('A01', 1)], dup, desired, new Map([['HINGE|HG-100', 10]]))).toEqual(
        legacySetProductQuantity([line('A01', 1)], dup, desired, new Map([['HINGE|HG-100', 10]])),
      );
    }
  });

  it('returns the very cart when nothing changes', () => {
    const lines = [line(null, 2)];
    expect(setProductQuantity(lines, small, 0, new Map([['HINGE|HG-100', 5]]))).toBe(lines);
  });
});
