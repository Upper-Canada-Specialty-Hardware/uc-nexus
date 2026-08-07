/**
 * The shape of a counted receive, and the rules it has to satisfy - shared by everything that edits
 * one.
 *
 * A receive is entered in three places now: the warehouse user counting a delivery, the manager
 * reviewing their draft before approving it, and the author correcting a rejected one. All three
 * edit the same thing, so the validation and the input-building live here rather than in whichever
 * dialog happened to have them first.
 */

export const MAX_LOC_LEN = 20;

export interface PODetailLineItem {
  id: string;
  poId: string;
  hardwareCategory: string;
  productCode: string;
  classification: string | null;
  orderedQuantity: number;
  receivedQuantity: number;
  unitCost: number;
  orderAs: string | null;
  // GP POP10110.ORD this line maps to; needed to target the GP line on a relay /receipt.
  gpLineOrd: number | null;
}

export interface PODetails {
  id: string;
  poNumber: string | null;
  // #425: which project (and therefore which GP job) this PO belongs to, so a dialog can say the
  // receipt will be refused before the user finishes counting. Null for a stock PO.
  projectId: string | null;
  // The GP company this PO was registered in. A receive posts to GP, so it can only run against a PO
  // that was registered there (has a gpCompany + poNumber). See isPoGpRegistered.
  gpCompany: string | null;
  vendorNameSnapshot: string | null;
  notes: string | null;
  status: string;
  lineItems: PODetailLineItem[];
}

/** One destination row for a received line, plus how many of those units arrived deficient.
 *  Fields are strings because they are bound to text inputs; parsed at validate/submit time. */
export interface LocationDraft {
  aisle: string;
  row: string;
  bay: string;
  quantity: string;
  deficient: string;
}

export function emptyDraft(quantity: number): LocationDraft {
  return { aisle: '', row: '', bay: '', quantity: String(quantity), deficient: '0' };
}

/**
 * A receive must post the GP receipt to count (issue #177), so the PO has to be a real GP PO:
 * created through the relay, which records its gpCompany + poNumber (the same step that advances it
 * to GP-Registered). Those two being present is exactly "registered in GP".
 */
export function isPoGpRegistered(d: PODetails | undefined): boolean {
  return !!d && !!d.gpCompany && !!d.poNumber;
}

/** The location rows for a line, defaulting to one row holding the whole received quantity. */
export function draftsForLine(
  lineLocations: Record<string, LocationDraft[]>,
  lineId: string,
  receiveNow: number,
): LocationDraft[] {
  return lineLocations[lineId] ?? [emptyDraft(receiveNow)];
}

/** A row without all three rack coordinates cannot be put away. Shared with the editor's per-line
 *  status caption. Only drafts counted before #501 carry rack rows at all. */
export function locationIncomplete(d: LocationDraft): boolean {
  return !d.aisle.trim() || !d.row.trim() || !d.bay.trim();
}

export interface ReceiveLineItemInput {
  poLineItemId: string;
  quantityReceived: number;
  locations: {
    aisle: string;
    row: string;
    bay: string;
    quantity: number;
    deficientQuantity: number;
  }[];
}

/** The `lineItems` payload every receive mutation takes - draft create, draft update, and the
 *  approval that eventually posts them to GP all speak this one shape.
 *
 *  `locations` is always empty since #501. A draft is a count, not a put-away: the warehouse
 *  manager approves the numbers, the receipt books one unlocated row per line, and the shelf is
 *  chosen afterwards on the Put Away queue. The field stays on the input because drafts counted
 *  before that change still carry theirs and the backend still reads them. */
export function buildReceiveLineItemsInput(
  lineItems: PODetailLineItem[],
  receiveQuantities: Record<string, number>,
): ReceiveLineItemInput[] {
  return lineItems.map((li) => ({
    poLineItemId: li.id,
    quantityReceived: receiveQuantities[li.id] ?? 0,
    locations: [],
  }));
}

/** A persisted draft's line, as the backend returns it. */
export interface ReceiveDraftLineItem {
  id: string;
  poLineItemId: string;
  hardwareCategory: string;
  productCode: string;
  quantityReceived: number;
  locations: {
    aisle: string;
    row: string;
    bay: string;
    quantity: number;
    deficientQuantity: number;
  }[];
}

/**
 * Load a persisted draft back into the editor's state - the inverse of
 * `buildReceiveLineItemsInput`, so a manager reviewing a draft sees exactly what was submitted
 * rather than a re-derived approximation of it.
 */
export function draftToEditorState(lineItems: ReceiveDraftLineItem[]): {
  receiveQuantities: Record<string, number>;
  lineLocations: Record<string, LocationDraft[]>;
} {
  const receiveQuantities: Record<string, number> = {};
  const lineLocations: Record<string, LocationDraft[]> = {};
  for (const li of lineItems) {
    receiveQuantities[li.poLineItemId] = li.quantityReceived;
    lineLocations[li.poLineItemId] =
      li.locations.length > 0
        ? li.locations.map((loc) => ({
            aisle: loc.aisle,
            row: loc.row,
            bay: loc.bay,
            quantity: String(loc.quantity),
            deficient: String(loc.deficientQuantity),
          }))
        : [emptyDraft(li.quantityReceived)];
  }
  return { receiveQuantities, lineLocations };
}
