/**
 * What the selected openings still have coming, as pure functions.
 *
 * The server answers `suggested = max(owed - sent - claimed, 0)` per (opening, category, product);
 * this turns that answer into the lines a request would carry.
 *
 * There is no allocation here any more (#646). Raising a shop-assembly request is pure
 * opening-flagging: it reserves nothing and is gated on nothing, so the wizard sends what the
 * openings are owed and the Shop Assembly Manager decides how much of it actually goes out, per
 * batch, against stock that exists by then. The allocator this file used to hold moved to
 * `modules/shop-assembly/types`, where the decision is.
 *
 * Nothing here touches React or Apollo on purpose - these numbers are the part that has to be
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

/** One line as `finalizeImportSession` takes it on a shop-assembly request. */
export interface RequestLineInput {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

/**
 * The lines the flag carries: every offered row, at what it is still owed.
 *
 * `quantity` is the SUGGESTION, not the schedule's raw owed figure. What the opening is owed is what
 * it was offered - owed minus what has already gone out and what somebody else is holding - so
 * sending the raw owed number would ask the shop for hardware another request is already bringing.
 *
 * Nothing is dropped and nothing is trimmed: the PM is stating what the shop needs, and every
 * decision about whether it can be met belongs to the manager's batch screen (#646).
 */
export function buildFlagLines(rows: CoverageRow[]): RequestLineInput[] {
  return rows.map((row) => ({
    openingNumber: row.openingNumber,
    hardwareCategory: row.hardwareCategory,
    productCode: row.productCode,
    quantity: row.suggestedQuantity,
  }));
}

