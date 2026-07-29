// The pick sheet's shapes and its entry arithmetic (#367), kept out of the components so the
// screen, the PDF and the tests all count the same way.
//
// The one rule that runs through all of it: nothing here ever proposes a quantity. There is no
// suggested split, no autofill, no "remaining" pre-filled into the first row. The warehouse user is
// the only person who can see the rack, and a suggestion is a default in everything but name.

import type { PullRequest } from './PullRequestQueue';

export interface PickSheetLeaf {
  openingNumber: string;
  leaf: number | null;
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
  leaves: PickSheetLeaf[];
  locations: PickSheetLocation[];
}

export interface PickSheetFetchItem {
  pullRequestItemId: string;
  openingItemId: string | null;
  openingNumber: string;
  leaf: number | null;
  aisle: string | null;
  row: string | null;
  bay: string | null;
  state: string | null;
  fetchedAt: string | null;
  fetchedBy: string | null;
}

export interface PickSheet {
  pullRequest: PullRequest;
  sections: PickSheetSection[];
  fetchItems: PickSheetFetchItem[];
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

/** A field's numeric value. Anything that is not a non-negative integer reads as nothing entered,
 *  which is what an empty box means and what a stray character should mean too. */
export function parseEntry(raw: string | undefined): number {
  if (!raw) return 0;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return 0;
  return Math.floor(value);
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
  /** Entered more than another request has left free for this pull - the server's third ceiling.
   *  Without this the screen calls a sheet balanced and `confirmPick` rejects the whole submission,
   *  discarding every entry in every section and making the picker re-key the lot. */
  beyondClaimable: boolean;
}

export function sectionTotals(section: PickSheetSection, entries: PickEntries): SectionTotals {
  let entered = 0;
  let anyRowOver = false;
  for (const loc of section.locations) {
    const value = parseEntry(entries[entryKey(section, loc.inventoryLocationId)]);
    entered += value;
    if (value > loc.available) anyRowOver = true;
  }
  const covered = section.appliedQuantity + entered;
  return {
    entered,
    remaining: Math.max(0, section.requiredQuantity - covered),
    over: covered > section.requiredQuantity,
    anyRowOver,
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
  /** Every product code is fully covered once this entry is applied. */
  balanced: boolean;
}

export function pickTotals(sections: PickSheetSection[], entries: PickEntries): PickTotals {
  let required = 0;
  let applied = 0;
  let entered = 0;
  let remaining = 0;
  let over = false;
  for (const section of sections) {
    const totals = sectionTotals(section, entries);
    required += section.requiredQuantity;
    applied += section.appliedQuantity;
    entered += totals.entered;
    remaining += totals.remaining;
    if (totals.over || totals.anyRowOver || totals.beyondClaimable) over = true;
  }
  return {
    codeCount: sections.length,
    required,
    applied,
    entered,
    remaining,
    over,
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
