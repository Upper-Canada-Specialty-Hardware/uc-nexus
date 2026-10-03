// The pick sheet's shapes and its entry arithmetic (#367), kept out of the components so the
// screen, the PDF and the tests all count the same way.
//
// The one rule that runs through all of it: nothing here ever proposes a quantity. There is no
// suggested split, no autofill, no "remaining" pre-filled into the first row. The warehouse user is
// the only person who can see the rack, and a suggestion is a default in everything but name.

import type { PullRequest } from './PullRequestQueue';

export interface PickSheetOpening {
  /** Null on an unattributed line (#451): the units are owed to the project, not to a door. */
  openingNumber: string | null;
  quantity: number;
}

export interface PickSheetLocation {
  inventoryLocationId: string;
  warehouseId: string | null;
  warehouseCode: string | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  /** On-hand minus condemned: the ceiling the server enforces for this row. */
  available: number;
  /** Shown so the picker can rotate stock themselves - the only thing FIFO was ever for. */
  receivedAt: string;
  draftQuantity: number;
  appliedQuantity: number;
  /**
   * What the vendor calls this part, and the PO it arrived on (#496). Per location, not per
   * section: one product can sit in inventory from several POs with different Order As values, so a
   * section-level value would be wrong for every row but one. Null on a stock-origin row.
   */
  orderAs: string | null;
  poNumber: string | null;
}

export interface PickSheetSection {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  appliedQuantity: number;
  remainingQuantity: number;
  /** What this pull may actually take: on-hand minus condemned minus other requests' claims. The
   *  third ceiling confirmPick enforces, so the picker sees contention before walking the racks. */
  claimableQuantity: number;
  /** How far short of remainingQuantity that leaves this pull. Zero in the ordinary case. */
  claimableShortfall: number;
  openings: PickSheetOpening[];
  locations: PickSheetLocation[];
}

export interface PickSheet {
  /** The pull's project, read off the project itself (#1196) so an archived job is still named. */
  projectNumber: string | null;
  projectDescription: string | null;
  pullRequest: PullRequest;
  sections: PickSheetSection[];
}

/** One line as `confirmPick` / `savePickDraft` take it. */
export interface PickLineInput {
  hardwareCategory: string;
  productCode: string;
  inventoryLocationId: string;
  quantity: number;
}

/** Raw input strings, keyed by section+location. Strings, not numbers: a half-typed "1" on the way
 *  to "12" and a cleared field are different states, and coercing them to 0 fights the typist. */
export type PickEntries = Record<string, string>;

export function entryKey(
  section: Pick<PickSheetSection, 'hardwareCategory' | 'productCode'>,
  inventoryLocationId: string,
): string {
  return `${section.hardwareCategory}|${section.productCode}|${inventoryLocationId}`;
}

/** Whether a box holds something the pick can take: empty, or a non-negative whole number (#1382).
 *  A decimal, a negative or a stray character is a row error the picker must fix, never something
 *  quietly read as a different count. */
export function isValidEntry(raw: string | undefined): boolean {
  if (raw === undefined) return true;
  const trimmed = raw.trim();
  return trimmed === '' || /^\d+$/.test(trimmed);
}

/** A field's numeric value. An empty box is nothing entered. An invalid box also reads as 0 here,
 *  but it is not ignored: sectionTotals flags it, which keeps Confirm and Save draft off until it is
 *  fixed, so no invalid entry is ever sent. */
export function parseEntry(raw: string | undefined): number {
  if (!raw || !isValidEntry(raw)) return 0;
  return Number(raw.trim());
}

/** A location's bin label, or the Unlocated reading. Unlocated stock is real and pickable - it just
 *  has not been put away - so it gets a name rather than an empty cell. */
export function locationLabel(loc: Pick<PickSheetLocation, 'aisle' | 'row' | 'bay'>): string | null {
  const parts = [loc.aisle, loc.row, loc.bay].filter(Boolean);
  return parts.length > 0 ? parts.join('-') : null;
}

export interface SectionTotals {
  entered: number;
  /** required - already applied - entered, floored at 0. */
  remaining: number;
  /** Entered more than this product still needs. */
  over: boolean;
  /** At least one row asks for more than that row has. */
  anyRowOver: boolean;
  /** At least one row holds something that is not a whole number of units (#1382). */
  anyRowInvalid: boolean;
  /** Entered more than another request has left free for this pull - the server's third ceiling.
   *  Without this the screen calls a sheet balanced and `confirmPick` rejects the whole submission,
   *  discarding every entry in every section and making the picker re-key the lot. */
  beyondClaimable: boolean;
}

export function sectionTotals(section: PickSheetSection, entries: PickEntries): SectionTotals {
  let entered = 0;
  let anyRowOver = false;
  let anyRowInvalid = false;
  for (const loc of section.locations) {
    const raw = entries[entryKey(section, loc.inventoryLocationId)];
    if (!isValidEntry(raw)) anyRowInvalid = true;
    const value = parseEntry(raw);
    entered += value;
    if (value > loc.available) anyRowOver = true;
  }
  const covered = section.appliedQuantity + entered;
  return {
    entered,
    remaining: Math.max(0, section.requiredQuantity - covered),
    over: covered > section.requiredQuantity,
    anyRowOver,
    anyRowInvalid,
    beyondClaimable: entered > section.claimableQuantity,
  };
}

export interface PickTotals {
  codeCount: number;
  required: number;
  applied: number;
  entered: number;
  remaining: number;
  /** Any of the three ceilings has been crossed - the row, the request, or what other requests have
   *  left free. Confirming is refused, and the server would refuse it too. */
  over: boolean;
  /** Some box holds something that is not a whole number (#1382). Counted into `over` too, and
   *  the one thing that also keeps Save draft off: a draft is saved as numbers. */
  invalid: boolean;
  /** Every product code is fully covered once this entry is applied. */
  balanced: boolean;
}

export function pickTotals(sections: PickSheetSection[], entries: PickEntries): PickTotals {
  let required = 0;
  let applied = 0;
  let entered = 0;
  let remaining = 0;
  let over = false;
  let invalid = false;
  for (const section of sections) {
    const totals = sectionTotals(section, entries);
    required += section.requiredQuantity;
    applied += section.appliedQuantity;
    entered += totals.entered;
    remaining += totals.remaining;
    if (totals.anyRowInvalid) invalid = true;
    if (totals.over || totals.anyRowOver || totals.beyondClaimable || totals.anyRowInvalid) over = true;
  }
  return {
    codeCount: sections.length,
    required,
    applied,
    entered,
    remaining,
    over,
    invalid,
    balanced: remaining === 0 && !over,
  };
}

/** The entered rows, as the mutation takes them. Zeroes are dropped: a blank box is not a claim
 *  that nothing came off that bin, it is simply a box nobody wrote in. */
export function toPickLines(sections: PickSheetSection[], entries: PickEntries): PickLineInput[] {
  const lines: PickLineInput[] = [];
  for (const section of sections) {
    for (const loc of section.locations) {
      const quantity = parseEntry(entries[entryKey(section, loc.inventoryLocationId)]);
      if (quantity <= 0) continue;
      lines.push({
        hardwareCategory: section.hardwareCategory,
        productCode: section.productCode,
        inventoryLocationId: loc.inventoryLocationId,
        quantity,
      });
    }
  }
  return lines;
}

/** Seed the fields from the saved draft, so reopening the page resumes the transcription rather
 *  than restarting it. Rows with no draft stay empty - never pre-filled with what is remaining. */
export function entriesFromDraft(sections: PickSheetSection[]): PickEntries {
  const entries: PickEntries = {};
  for (const section of sections) {
    for (const loc of section.locations) {
      if (loc.draftQuantity > 0) {
        entries[entryKey(section, loc.inventoryLocationId)] = String(loc.draftQuantity);
      }
    }
  }
  return entries;
}
