/**
 * Assigning available inventory to door leaves, as pure functions.
 *
 * Shop assembly is deliberately not all-or-nothing. The old creation gate refused the whole request
 * when the selection did not fit available stock, which meant one leaf short of one hinge held up
 * every leaf behind it. The requester now decides: each checklist line gets an *allocated* quantity
 * out of what is genuinely free, a partially-covered leaf still goes to the bench, and the
 * send/don't-send call is theirs to make with the numbers in front of them.
 *
 * Nothing here touches React or Apollo on purpose - the assignment rules are the part that has to be
 * exactly right, and they are worth testing without rendering anything.
 */

/** One assembly work unit (a door leaf) the wizard would submit, with its checklist aggregated. */
export interface ShopAssemblyOpeningDraft {
  openingNumber: string;
  leaf: number | null;
  items: Array<{ hardwareCategory: string; productCode: string; quantity: number }>;
}

/** Allocated quantity per checklist line, keyed by leaf then by combo. */
export type Allocation = Map<string, Map<string, number>>;

/** How much of a leaf's owed hardware it actually got. */
export type LeafCoverage = 'FULL' | 'PARTIAL' | 'NONE';

export const comboKey = (item: { hardwareCategory: string; productCode: string }) =>
  `${item.hardwareCategory}|${item.productCode}`;

/** Identity of a work unit. Opening number alone is not unique - a pair has two leaves. */
export const leafKey = (draft: { openingNumber: string; leaf: number | null }) =>
  `${draft.openingNumber}|${draft.leaf ?? 'none'}`;

/**
 * Fill leaves from the available pool, in schedule order, until each combo's pool runs out.
 *
 * First-leaf-first rather than spreading thinly across every leaf. Half a leaf's hardware assembles
 * nothing: the leaf still occupies a cart, a bench and an assembler, and it still cannot ship. Whole
 * leaves are what the shop can actually finish, so scarcity is pushed to the *end* of the schedule
 * where it lands on the fewest leaves. Schedule order is also the order the site expects openings in.
 *
 * Deterministic by construction - same drafts and same pool in, same allocation out - which is what
 * lets the step re-run it after a race without the numbers moving under the user for no reason.
 */
export function autoAssign(
  drafts: ShopAssemblyOpeningDraft[],
  availableByCombo: Map<string, number>,
): Allocation {
  const pool = new Map<string, number>();
  const allocation: Allocation = new Map();

  for (const draft of drafts) {
    const lines = new Map<string, number>();
    for (const item of draft.items) {
      const key = comboKey(item);
      if (!pool.has(key)) pool.set(key, Math.max(0, availableByCombo.get(key) ?? 0));
      const remaining = pool.get(key)!;
      const take = Math.min(item.quantity, remaining);
      pool.set(key, remaining - take);
      lines.set(key, take);
    }
    allocation.set(leafKey(draft), lines);
  }
  return allocation;
}

/** What one line was allocated. A line the allocation has never seen counts as zero, not as owed. */
export function allocatedFor(
  allocation: Allocation,
  draft: ShopAssemblyOpeningDraft,
  item: { hardwareCategory: string; productCode: string },
): number {
  return allocation.get(leafKey(draft))?.get(comboKey(item)) ?? 0;
}

/** Total allocated across a leaf's lines. Zero means an empty cart. */
export function leafAllocatedTotal(allocation: Allocation, draft: ShopAssemblyOpeningDraft): number {
  return draft.items.reduce((sum, item) => sum + allocatedFor(allocation, draft, item), 0);
}

/**
 * How well a leaf is covered. NONE means nothing at all was allocated to it: an empty cart, with
 * nothing to pull, stage or assemble, so the step drops it from the request rather than sending a
 * work unit that could never be completed.
 */
export function leafCoverage(allocation: Allocation, draft: ShopAssemblyOpeningDraft): LeafCoverage {
  let allocated = 0;
  let owed = 0;
  for (const item of draft.items) {
    owed += item.quantity;
    allocated += allocatedFor(allocation, draft, item);
  }
  if (allocated <= 0) return 'NONE';
  return allocated >= owed ? 'FULL' : 'PARTIAL';
}

/**
 * What is left of each combo's pool once the *included* leaves have taken their share.
 *
 * Excluded and auto-dropped leaves hand their allocation back, which is what makes the exclude
 * toggle mean something: the freed units become assignable on a leaf the user would rather send.
 */
export function remainingPool(
  drafts: ShopAssemblyOpeningDraft[],
  allocation: Allocation,
  availableByCombo: Map<string, number>,
  includedLeafKeys: ReadonlySet<string>,
): Map<string, number> {
  const pool = new Map<string, number>();
  for (const draft of drafts) {
    for (const item of draft.items) {
      const key = comboKey(item);
      if (!pool.has(key)) pool.set(key, Math.max(0, availableByCombo.get(key) ?? 0));
    }
  }
  for (const draft of drafts) {
    if (!includedLeafKeys.has(leafKey(draft))) continue;
    for (const item of draft.items) {
      const key = comboKey(item);
      pool.set(key, (pool.get(key) ?? 0) - allocatedFor(allocation, draft, item));
    }
  }
  return pool;
}

/**
 * The most this line could be raised to right now: never above what the leaf is owed, and never
 * above what this line already holds plus what is left in the pool.
 *
 * Written as a ceiling rather than a "can I add N" predicate because it is what the stepper's max
 * has to be, and deriving the two separately is how they drift apart.
 */
export function clampCeiling(owed: number, allocatedNow: number, poolRemaining: number): number {
  return Math.max(0, Math.min(owed, allocatedNow + Math.max(0, poolRemaining)));
}

/** Set one line's allocation, clamped to what is actually assignable. Returns a new Allocation. */
export function setLineAllocation(
  allocation: Allocation,
  draft: ShopAssemblyOpeningDraft,
  item: { hardwareCategory: string; productCode: string; quantity: number },
  requested: number,
  poolRemaining: number,
): Allocation {
  const ceiling = clampCeiling(item.quantity, allocatedFor(allocation, draft, item), poolRemaining);
  const next = new Map(allocation);
  const lines = new Map(next.get(leafKey(draft)) ?? []);
  lines.set(comboKey(item), Math.max(0, Math.min(requested, ceiling)));
  next.set(leafKey(draft), lines);
  return next;
}

/** One row of the combo summary: the whole request's claim on one product, at a glance. */
export interface ComboSummaryRow {
  key: string;
  hardwareCategory: string;
  productCode: string;
  owed: number;
  available: number;
  allocated: number;
  remaining: number;
  short: number;
}

/**
 * Per-combo totals over the included leaves only.
 *
 * `short` is owed minus allocated across *included* leaves - what this request is knowingly sending
 * without. A leaf the user excluded is not short, it is simply not in the request.
 */
export function comboSummary(
  drafts: ShopAssemblyOpeningDraft[],
  allocation: Allocation,
  availableByCombo: Map<string, number>,
  includedLeafKeys: ReadonlySet<string>,
): ComboSummaryRow[] {
  const rows = new Map<string, ComboSummaryRow>();
  for (const draft of drafts) {
    if (!includedLeafKeys.has(leafKey(draft))) continue;
    for (const item of draft.items) {
      const key = comboKey(item);
      let row = rows.get(key);
      if (!row) {
        row = {
          key,
          hardwareCategory: item.hardwareCategory,
          productCode: item.productCode,
          owed: 0,
          available: Math.max(0, availableByCombo.get(key) ?? 0),
          allocated: 0,
          remaining: 0,
          short: 0,
        };
        rows.set(key, row);
      }
      row.owed += item.quantity;
      row.allocated += allocatedFor(allocation, draft, item);
    }
  }
  const result = Array.from(rows.values());
  for (const row of result) {
    row.remaining = Math.max(0, row.available - row.allocated);
    row.short = Math.max(0, row.owed - row.allocated);
  }
  result.sort(
    (a, b) =>
      a.hardwareCategory.localeCompare(b.hardwareCategory) || a.productCode.localeCompare(b.productCode),
  );
  return result;
}

/** A draft plus the allocated quantity per line, exactly as the finalize mutation takes it. */
export interface AllocatedOpeningDraft {
  openingNumber: string;
  leaf: number | null;
  items: Array<{
    hardwareCategory: string;
    productCode: string;
    quantity: number;
    allocatedQuantity: number;
  }>;
}

/**
 * The payload: the included leaves that have something allocated, carrying both numbers per line.
 *
 * Owed is sent unchanged even on a line that got nothing - the checklist is what the leaf takes, and
 * the schedule is the authority on that. Leaves with nothing at all are dropped, because an empty
 * cart is not a work unit; the server refuses one too, as a backstop for a race.
 */
export function buildAllocatedDrafts(
  drafts: ShopAssemblyOpeningDraft[],
  allocation: Allocation,
  includedLeafKeys: ReadonlySet<string>,
): AllocatedOpeningDraft[] {
  return drafts
    .filter((draft) => includedLeafKeys.has(leafKey(draft)) && leafAllocatedTotal(allocation, draft) > 0)
    .map((draft) => ({
      openingNumber: draft.openingNumber,
      leaf: draft.leaf,
      items: draft.items.map((item) => ({
        hardwareCategory: item.hardwareCategory,
        productCode: item.productCode,
        quantity: item.quantity,
        allocatedQuantity: allocatedFor(allocation, draft, item),
      })),
    }));
}
