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
  vendor: { id: string; name: string; contactName: string | null } | null;
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
 *  status caption, so what the caption calls done is exactly what validatePutAway will accept. */
export function locationIncomplete(d: LocationDraft): boolean {
  return !d.aisle.trim() || !d.row.trim() || !d.bay.trim();
}

/**
 * Put-away is mandatory: every received unit must land in a valid row and each row's deficient count
 * must be within its quantity. Mirrors the backend contract in warehouse_repository.create_receive
 * and gives the GP receipt a non-empty rack location per line.
 */
export function validatePutAway(
  lineItems: PODetailLineItem[],
  receiveQuantities: Record<string, number>,
  lineLocations: Record<string, LocationDraft[]>,
): boolean {
  for (const li of lineItems) {
    const receiveNow = receiveQuantities[li.id] ?? 0;
    let placed = 0;
    for (const d of draftsForLine(lineLocations, li.id, receiveNow)) {
      const q = Number(d.quantity);
      const def = Number(d.deficient || '0');
      if (locationIncomplete(d)) return false;
      if (!Number.isInteger(q) || q < 1) return false;
      if (!Number.isInteger(def) || def < 0 || def > q) return false;
      placed += q;
    }
    if (placed !== receiveNow) return false;
  }
  return true;
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
 *  approval that eventually posts them to GP all speak this one shape. */
export function buildReceiveLineItemsInput(
  lineItems: PODetailLineItem[],
  receiveQuantities: Record<string, number>,
  lineLocations: Record<string, LocationDraft[]>,
): ReceiveLineItemInput[] {
  return lineItems.map((li) => {
    const receiveNow = receiveQuantities[li.id] ?? 0;
    return {
      poLineItemId: li.id,
      quantityReceived: receiveNow,
      locations: draftsForLine(lineLocations, li.id, receiveNow).map((d) => ({
        aisle: d.aisle.trim(),
        row: d.row.trim(),
        bay: d.bay.trim(),
        quantity: Number(d.quantity),
        deficientQuantity: Number(d.deficient || '0'),
      })),
    };
  });
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
