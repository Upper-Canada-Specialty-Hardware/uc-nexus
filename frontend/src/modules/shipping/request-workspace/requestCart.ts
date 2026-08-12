/**
 * The draft cart a shipping request is composed in, as pure functions (no React, no Apollo).
 *
 * One cart holds two kinds of line against the same job: schedule-driven lines, which carry the
 * opening a quantity is owed to, and loose lines raised straight off project inventory, which carry
 * no opening because shelf stock belongs to the project rather than to a door
 * (docs/HARDWARE_IDENTITY_LIFECYCLE.md). Both kinds reserve from the SAME fungible pool - inventory
 * availability is per (category, product) and does not care whether a line names an opening - so the
 * governing rule is per product, not per line:
 *
 *   sum of every cart line for a product  <=  availableQuantity(product) + heldByThisRequest(product)
 *
 * `availableQuantity` (projectInventoryAvailability, #342) is already net of every reservation,
 * including - in edit mode - this request's own. The add-back term is what lets an edit keep the
 * units it is already sitting on: without it, trimming a line would read as asking for more.
 *
 * The arithmetic lives here, apart from the screen, because it is the part that has to be exactly
 * right. The tabs and the rail all clamp against these functions so they cannot propose a cart the
 * server would refuse.
 */

import type { CoverageRow } from '../../import/composer';

/** One line the cart is building. `openingNumber` null is a loose line - stock owed to the job, not
 *  to a door. */
export interface CartLine {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

/** The fungible pool is per (category, product); every headroom calculation keys on this. */
export const productKey = (l: { hardwareCategory: string; productCode: string }): string =>
  `${l.hardwareCategory}|${l.productCode}`;

/** A line's own identity, so the same product on two openings (or loose) is three separate lines. */
export const cartLineKey = (l: {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
}): string => `${l.openingNumber ?? ''}|${l.hardwareCategory}|${l.productCode}`;

/** What one product may be claimed for at all: what is free, plus what this request already holds. */
export type Headroom = Map<string, number>;

/**
 * The per-product ceiling every quantity is clamped to.
 *
 * `available` is the reservation-aware free count per product. `held` is what THIS request holds of
 * each product before editing began (empty in create mode); it is added back because `available` is
 * already net of it. A product with neither is absent from both maps and gets a ceiling of 0.
 */
export function headroomByProduct(available: Map<string, number>, held: Map<string, number>): Headroom {
  const headroom: Headroom = new Map(available);
  for (const [key, qty] of held) {
    headroom.set(key, (headroom.get(key) ?? 0) + qty);
  }
  return headroom;
}

/** What this request held of each product before editing, summed over however many openings carried
 *  it. Empty for a new request. */
export function heldByRequest(
  items: { hardwareCategory: string; productCode: string; requestedQuantity: number }[],
): Map<string, number> {
  const held = new Map<string, number>();
  for (const item of items) {
    const key = productKey(item);
    held.set(key, (held.get(key) ?? 0) + item.requestedQuantity);
  }
  return held;
}

/** How much of each product the whole cart currently holds, across schedule and loose lines alike. */
export function cartTotalsByProduct(lines: CartLine[]): Map<string, number> {
  const totals = new Map<string, number>();
  for (const line of lines) {
    const key = productKey(line);
    totals.set(key, (totals.get(key) ?? 0) + line.quantity);
  }
  return totals;
}

/**
 * What is still free to add of a product, once every OTHER cart line for it has taken its share.
 *
 * `excludingLine` is the line being edited: its own quantity is left out so a line can be re-typed up
 * to the product's ceiling rather than being capped by what it is already sitting on. Adding a brand
 * new line passes a key nothing matches, so the whole product total counts against the ceiling.
 */
export function remainingForProduct(
  lines: CartLine[],
  key: string,
  headroom: Headroom,
  excludingLineKey?: string,
): number {
  const ceiling = headroom.get(key) ?? 0;
  let othersHold = 0;
  for (const line of lines) {
    if (productKey(line) !== key) continue;
    if (excludingLineKey !== undefined && cartLineKey(line) === excludingLineKey) continue;
    othersHold += line.quantity;
  }
  return Math.max(0, ceiling - othersHold);
}

/**
 * Set one line's quantity, clamped so the product's total can never cross its ceiling.
 *
 * A quantity of zero (or less) removes the line rather than leaving a zero that reserves nothing and
 * reads on the request as a promise nobody can keep. A new line is appended; an existing one is
 * rewritten in place so its position - and the opening it carries - is kept.
 */
export function setLineQuantity(
  lines: CartLine[],
  target: { openingNumber: string | null; hardwareCategory: string; productCode: string },
  desired: number,
  headroom: Headroom,
): CartLine[] {
  const key = productKey(target);
  const lineKey = cartLineKey(target);
  const ceiling = remainingForProduct(lines, key, headroom, lineKey);
  const clamped = Math.max(0, Math.min(Number.isFinite(desired) ? desired : 0, ceiling));

  const exists = lines.some((line) => cartLineKey(line) === lineKey);
  if (!exists) {
    return clamped > 0
      ? [
          ...lines,
          {
            openingNumber: target.openingNumber,
            hardwareCategory: target.hardwareCategory,
            productCode: target.productCode,
            quantity: clamped,
          },
        ]
      : lines;
  }
  return lines
    .map((line) => (cartLineKey(line) === lineKey ? { ...line, quantity: clamped } : line))
    .filter((line) => line.quantity > 0);
}

/** The quantity of one line currently in the cart, or 0 if it is not there. */
export function lineQuantity(
  lines: CartLine[],
  target: { openingNumber: string | null; hardwareCategory: string; productCode: string },
): number {
  const lineKey = cartLineKey(target);
  return lines.find((line) => cartLineKey(line) === lineKey)?.quantity ?? 0;
}

/**
 * Add a schedule row at its suggested quantity, clamped to what the pool can still cover.
 *
 * "Suggested" is `max(owed - sent - claimed, 0)` from the server, but the cart in front of the user
 * is state the server has not seen - six hinges already added loose shrink what this line can still
 * take. So the ceiling is the live remaining pool, not the raw suggestion.
 */
export function addScheduleRowAtSuggested(lines: CartLine[], row: CoverageRow, headroom: Headroom): CartLine[] {
  return setLineQuantity(
    lines,
    { openingNumber: row.openingNumber, hardwareCategory: row.hardwareCategory, productCode: row.productCode },
    row.suggestedQuantity,
    headroom,
  );
}

/** Take all of a product that is still free onto its loose (opening-less) line. */
export function takeAllFreeLoose(
  lines: CartLine[],
  product: { hardwareCategory: string; productCode: string },
  headroom: Headroom,
): CartLine[] {
  const target = { openingNumber: null, hardwareCategory: product.hardwareCategory, productCode: product.productCode };
  const current = lineQuantity(lines, target);
  const remaining = remainingForProduct(lines, productKey(product), headroom, cartLineKey(target));
  return setLineQuantity(lines, target, current + remaining, headroom);
}

/** Remove one line outright (the rail's trash button). */
export function removeLine(
  lines: CartLine[],
  target: { openingNumber: string | null; hardwareCategory: string; productCode: string },
): CartLine[] {
  const lineKey = cartLineKey(target);
  return lines.filter((line) => cartLineKey(line) !== lineKey);
}

/** One product's group in the rail: the lines under it and how they sit against the ceiling. */
export interface CartProductGroup {
  key: string;
  hardwareCategory: string;
  productCode: string;
  /** Opening-attributed lines first (by opening), the loose line last. */
  lines: CartLine[];
  total: number;
  headroom: number;
  /** total > headroom - only reachable if availability moved under a persisted draft. */
  overCommitted: boolean;
}

/**
 * The cart grouped by product for the rail, opening lines before the loose one, products sorted by
 * code. Empty groups never appear - a product drops out of the rail when its last line is removed.
 */
export function cartGroups(lines: CartLine[], headroom: Headroom): CartProductGroup[] {
  const byProduct = new Map<string, CartLine[]>();
  for (const line of lines) {
    const key = productKey(line);
    const bucket = byProduct.get(key);
    if (bucket) bucket.push(line);
    else byProduct.set(key, [line]);
  }
  const groups: CartProductGroup[] = [];
  for (const [key, group] of byProduct) {
    const sorted = [...group].sort((a, b) => {
      if (a.openingNumber === null) return 1;
      if (b.openingNumber === null) return -1;
      return a.openingNumber.localeCompare(b.openingNumber);
    });
    const total = sorted.reduce((sum, line) => sum + line.quantity, 0);
    const ceiling = headroom.get(key) ?? 0;
    groups.push({
      key,
      hardwareCategory: sorted[0].hardwareCategory,
      productCode: sorted[0].productCode,
      lines: sorted,
      total,
      headroom: ceiling,
      overCommitted: total > ceiling,
    });
  }
  return groups.sort((a, b) => a.productCode.localeCompare(b.productCode));
}

/** One item as the create/edit mutation takes it. Loose lines send `openingNumber: null`. */
export interface RequestItemInput {
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
}

/** The exact payload the cart submits: every line with a positive quantity, zero-lines dropped. */
export function buildRequestItems(lines: CartLine[]): RequestItemInput[] {
  return lines
    .filter((line) => line.quantity > 0)
    .map((line) => ({
      openingNumber: line.openingNumber,
      hardwareCategory: line.hardwareCategory,
      productCode: line.productCode,
      requestedQuantity: line.quantity,
    }));
}

export const totalUnits = (lines: CartLine[]): number => lines.reduce((sum, line) => sum + line.quantity, 0);
