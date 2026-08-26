/**
 * Composing a request from what the openings still have coming, as pure functions.
 *
 * The server answers `suggested = max(owed - sent - claimed, 0)` per (opening, category, product);
 * this turns that answer into the lines a request would carry, and decides how much of each line the
 * project's free stock can actually cover.
 *
 * A request is deliberately not all-or-nothing. The old creation gate refused the whole thing when
 * the selection did not fit available stock, which meant one line short of one hinge held up every
 * line behind it. The requester decides instead: each line gets an *allocated* quantity out of what
 * is genuinely free, a partly-covered request still goes, and the send/don't-send call is theirs to
 * make with the numbers in front of them.
 *
 * Nothing here touches React or Apollo on purpose - the assignment rules are the part that has to be
 * exactly right, and they are worth testing without rendering anything.
 */

export type HardwareClassification = 'SITE_HARDWARE' | 'SHOP_HARDWARE';

/** One row of the composer query: what this opening still has coming of one product. */
export interface CoverageRow {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  /** Null when the schedule was never classified - shown as its own group, never guessed at. */
  classification: HardwareClassification | null;
  /** What the CURRENT schedule says this opening takes, summed across its leaves. */
  owedQuantity: number;
  /** What has left the building for this opening: completed pulls, and the slips cut from them. */
  sentQuantity: number;
  /** #632: the sent total split by exit - through the shop bench vs out on a truck. */
  assembledQuantity: number;
  shippedQuantity: number;
  /** What somebody else is already holding: pending requests and live pulls. */
  claimedQuantity: number;
  /** `max(owed - sent - claimed, 0)`. Zero when a re-upload lowered owed below what went out. */
  suggestedQuantity: number;
  /** Ordered from a vendor and not yet received, project-wide. Not an allocation to this opening. */
  onOrderQuantity: number;
}

/** Allocated quantity per line, keyed by `lineKey`. */
export type Allocation = Map<string, number>;

export const comboKey = (row: { hardwareCategory: string; productCode: string }) =>
  `${row.hardwareCategory}|${row.productCode}`;

/** Identity of one composable line. The opening is part of it: the same product on two doors is two
 *  lines, and they are allocated independently. */
export const lineKey = (row: { openingNumber: string; hardwareCategory: string; productCode: string }) =>
  `${row.openingNumber}|${comboKey(row)}`;

/**
 * Which bucket a line belongs to on screen.
 *
 * SITE and SHOP are the classification the import step recorded. UNCLASSIFIED is its own group
 * rather than being folded into either: the schedule genuinely never said, and guessing would put
 * hardware on the wrong request without anybody deciding to.
 */
export type CoverageGroup = 'SITE' | 'SHOP' | 'UNCLASSIFIED';

export function coverageGroup(row: { classification: HardwareClassification | null }): CoverageGroup {
  if (row.classification === 'SITE_HARDWARE') return 'SITE';
  if (row.classification === 'SHOP_HARDWARE') return 'SHOP';
  return 'UNCLASSIFIED';
}

/**
 * The lines a composer offers: everything with something still to send, in a stable order.
 *
 * A row whose `suggested` is zero is dropped. It has either been fully sent or is fully spoken for,
 * and offering a zero is noise on a screen whose whole job is "what is left". The one thing that
 * would be lost - a schedule lowered below what shipped - is not actionable here either; it is a
 * discrepancy for a human, not a line to compose.
 */
export function composableRows(rows: CoverageRow[], group?: CoverageGroup): CoverageRow[] {
  return rows
    .filter((row) => row.suggestedQuantity > 0 && (group === undefined || coverageGroup(row) === group))
    .sort(
      (a, b) =>
        a.openingNumber.localeCompare(b.openingNumber) ||
        a.hardwareCategory.localeCompare(b.hardwareCategory) ||
        a.productCode.localeCompare(b.productCode),
    );
}

/**
 * What the offer *is*, as a comparable string: which lines, and what each suggests.
 *
 * The allocator seeds itself once and must not re-seed afterwards, or it would silently discard the
 * user's manual moves. "Once" cannot be a flag inside the step, because the wizard mounts the step
 * only while it is the active one - stepping Back and Next again remounts it and resets the flag.
 * The wizard holds this signature instead: an unchanged offer means the existing allocation still
 * describes it and is left alone; a changed offer (different openings picked, a request accepted
 * elsewhere) means it no longer does, and re-seeding is the correct answer rather than a loss.
 */
export function offerSignature(rows: CoverageRow[]): string {
  return rows
    .map((row) => `${lineKey(row)}=${row.suggestedQuantity}`)
    .sort()
    .join(';');
}

/**
 * Fill lines from the available pool, in schedule order, until each combo's pool runs out.
 *
 * First-line-first rather than spreading thinly across every line. Half the hardware for one door
 * gets that door onto the bench; a tenth of it on ten doors gets nothing anywhere, and the requester
 * would have to undo the spread by hand before they could send anything at all. Whoever wants a
 * different split moves the numbers themselves, which is the point of allocating at all.
 */
export function autoAllocate(rows: CoverageRow[], availableByCombo: Map<string, number>): Allocation {
  const remaining = new Map(availableByCombo);
  const allocation: Allocation = new Map();
  for (const row of rows) {
    const combo = comboKey(row);
    const free = remaining.get(combo) ?? 0;
    const take = Math.max(0, Math.min(free, row.suggestedQuantity));
    allocation.set(lineKey(row), take);
    remaining.set(combo, free - take);
  }
  return allocation;
}

/** How much of a line's suggestion it actually got. */
export type LineCoverage = 'FULL' | 'PARTIAL' | 'NONE';

export function lineCoverage(row: CoverageRow, allocated: number): LineCoverage {
  if (allocated <= 0) return 'NONE';
  return allocated >= row.suggestedQuantity ? 'FULL' : 'PARTIAL';
}

/** Per-combo totals across the whole offer: what it wants, and what it managed to claim. */
export function comboSummary(
  rows: CoverageRow[],
  allocation: Allocation,
  included: Set<string>,
): Map<string, { hardwareCategory: string; productCode: string; suggested: number; allocated: number }> {
  const summary = new Map<
    string,
    { hardwareCategory: string; productCode: string; suggested: number; allocated: number }
  >();
  for (const row of rows) {
    if (!included.has(lineKey(row))) continue;
    const key = comboKey(row);
    const entry = summary.get(key) ?? {
      hardwareCategory: row.hardwareCategory,
      productCode: row.productCode,
      suggested: 0,
      allocated: 0,
    };
    entry.suggested += row.suggestedQuantity;
    entry.allocated += allocation.get(lineKey(row)) ?? 0;
    summary.set(key, entry);
  }
  return summary;
}

/** One line as `finalizeImportSession` takes it, for either request type. */
export interface RequestLineInput {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  allocatedQuantity: number;
}

/**
 * The exact payload a finalize sends: the included lines, each carrying both numbers.
 *
 * `quantity` is the SUGGESTION, not the schedule's raw owed figure. What the request is owed is what
 * it was offered - owed minus what has already gone out and what somebody else is holding - so
 * sending the raw owed number would make every line look short by everything the opening had ever
 * received.
 *
 * A line with nothing allocated is dropped rather than sent as a zero: it would reserve nothing,
 * mint no pull line, and read on the request as a promise nobody can keep.
 */
export function buildRequestLines(
  rows: CoverageRow[],
  allocation: Allocation,
  included: Set<string>,
): RequestLineInput[] {
  const lines: RequestLineInput[] = [];
  for (const row of rows) {
    const key = lineKey(row);
    if (!included.has(key)) continue;
    const allocated = allocation.get(key) ?? 0;
    if (allocated <= 0) continue;
    lines.push({
      openingNumber: row.openingNumber,
      hardwareCategory: row.hardwareCategory,
      productCode: row.productCode,
      quantity: row.suggestedQuantity,
      allocatedQuantity: allocated,
    });
  }
  return lines;
}

// ---- Compose-step Next gate (#566) ----

/** What deciding whether a compose request can be sent needs. */
export interface ComposeGateInput {
  /** The lines on offer for this purpose. */
  rows: CoverageRow[];
  /** Allocated quantity per line. */
  allocation: Allocation;
  /** Lines the user has kept in the request. */
  includedKeys: Set<string>;
  coverageLoading: boolean;
  coverageError: boolean;
  availabilityLoading: boolean;
  availabilityError: boolean;
}

export interface ComposeGate {
  /** Lines both ticked and carrying a quantity - what the request would actually reserve. */
  includedCount: number;
  /** A read the counts depend on is still in flight. */
  busy: boolean;
  /** A read the counts depend on failed; the numbers are unknown rather than zero. */
  loadFailed: boolean;
  /** May the request be sent from here. */
  canProceed: boolean;
  /** Why Next is refused, or null when it is allowed. */
  blockedReason: string | null;
}

/**
 * The Next gate for a compose step, as one pure function so the wizard's AppBar Next and the step it
 * sits above cannot diverge (#566). A shortfall does not block: sending short is a decision the user
 * is allowed to make. What has to be true is that there is a request to make - at least one line
 * carrying something - and that the availability numbers are real rather than unknown.
 */
export function composeRequestGate({
  rows,
  allocation,
  includedKeys,
  coverageLoading,
  coverageError,
  availabilityLoading,
  availabilityError,
}: ComposeGateInput): ComposeGate {
  const includedCount = rows.filter(
    (row) => includedKeys.has(lineKey(row)) && (allocation.get(lineKey(row)) ?? 0) > 0,
  ).length;
  const loadFailed = coverageError || availabilityError;
  const busy = (coverageLoading || availabilityLoading) && !loadFailed;
  const canProceed = includedCount > 0 && !busy && !loadFailed;
  // A disabled Next with nothing beside it reads as a broken button. Each of these is recoverable
  // from this screen or the one behind it, so the reason says which.
  const blockedReason = loadFailed
    ? 'The numbers above could not be read. Go back and retry.'
    : busy
      ? 'Still working out what is owed and what is free.'
      : includedCount > 0
        ? null
        : rows.length === 0
          ? 'There is nothing to request for these openings.'
          : 'Tick at least one line and give it a quantity.';
  return { includedCount, busy, loadFailed, canProceed, blockedReason };
}
