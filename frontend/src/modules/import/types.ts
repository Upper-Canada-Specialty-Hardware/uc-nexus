import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

export type AggregatedHardwareItem = Omit<ParsedHardwareItem, 'material_id'>;

export function aggregationKey(hi: { opening_number: string; product_code: string; hardware_category: string }) {
  return `${hi.opening_number}|${hi.product_code}|${hi.hardware_category}`;
}

export type ImportPurpose = 'po' | 'assembly' | 'shipping';

/**
 * One (hardware_category, product_code) row of `projectInventoryAvailability` (#342):
 * `availableQuantity = onHandQuantity - deficientQuantity - reservedQuantity`, the number the
 * server's creation gate applies.
 */
export interface InventoryAvailabilityRow {
  hardwareCategory: string;
  productCode: string;
  onHandQuantity: number;
  deficientQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
}

/** How the schedule says a product gets fitted, or null when it was never classified. */
export type HardwareClassification = 'SITE_HARDWARE' | 'SHOP_HARDWARE';

export function hardwareItemKey(hi: ParsedHardwareItem) {
  return `${hi.opening_number}|${hi.product_code}|${hi.material_id}`;
}

export interface ReconciliationRow {
  id: string;
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  status: string;
}

export function classificationKey(hi: { hardware_category: string; product_code: string; unit_cost: number | null }) {
  return `${hi.hardware_category}|${hi.product_code}|${hi.unit_cost ?? 0}`;
}

export function itemGroupKey(hi: { hardware_category: string; product_code: string }) {
  return `${hi.hardware_category}|${hi.product_code}`;
}

// #570: a line's identity inside a PO draft. Product-first to match the order-as / unit-cost keys the
// wizard already uses (`${product_code}|${hardware_category}`). Cost and alias are properties of the
// product, so they are keyed on this and shared across whichever drafts the product lands in.
export function productKey(hi: { product_code: string; hardware_category: string }) {
  return `${hi.product_code}|${hi.hardware_category}`;
}

export interface DraftGroupInfo {
  notes: string;
  preferredDeliveryDate: string;
  costCode: string;
}

// #570: one PO draft the buyer is composing. Manufacturer slicing is only the seed - lines move
// between drafts, drafts merge/split/rename, so a draft is no longer tied to a manufacturer. `lines`
// maps productKey -> quantity; the invariant, held by construction, is that the quantities of a
// productKey summed across every draft equal that product's total in the aggregated selection.
export interface DraftGroup {
  id: string;
  label: string;
  included: boolean;
  info: DraftGroupInfo;
  lines: Map<string, number>;
}

// Seed one draft per manufacturer group at full quantity - the starting point the buyer then slices.
// Unchecked by default (nothing is ordered until the buyer says so), same as the old vendor selection.
export function seedDraftGroups(vendorGroups: Map<string, AggregatedHardwareItem[]>): DraftGroup[] {
  const groups: DraftGroup[] = [];
  for (const [vendor, items] of vendorGroups) {
    const lines = new Map<string, number>();
    for (const hi of items) {
      const pk = productKey(hi);
      lines.set(pk, (lines.get(pk) ?? 0) + hi.item_quantity);
    }
    groups.push({
      id: `seed:${vendor}`,
      label: vendor,
      included: false,
      info: { notes: '', preferredDeliveryDate: '', costCode: '' },
      lines,
    });
  }
  return groups;
}

// A signature of the aggregated selection the drafts are seeded from. Re-seed only when this changes
// (a different selection, or a reclassification that moved items in or out), so walking Back and
// forward without changing the selection does not clobber the buyer's slicing - the same guard the
// request composer uses with its offer signature.
export function draftSeedSignature(vendorGroups: Map<string, AggregatedHardwareItem[]>): string {
  const parts: string[] = [];
  for (const [vendor, items] of vendorGroups) {
    const byProduct = new Map<string, number>();
    for (const hi of items) {
      const pk = productKey(hi);
      byProduct.set(pk, (byProduct.get(pk) ?? 0) + hi.item_quantity);
    }
    const sorted = Array.from(byProduct.entries()).sort(([a], [b]) => a.localeCompare(b));
    parts.push(`${vendor}::${sorted.map(([k, q]) => `${k}=${q}`).join(',')}`);
  }
  return parts.join('||');
}

export interface ClassificationOption {
  value: string;
  label: string;
  color: 'success' | 'info' | 'warning';
}

export const SCOPE_OPTIONS: ClassificationOption[] = [
  // Internal value stays BY_UCSH; only the label follows the UC Hardware Inc. rename (#484).
  { value: 'BY_UCSH', label: 'By UCH', color: 'success' },
  { value: 'BY_OTHERS', label: 'By Others', color: 'warning' },
];

export const ASSEMBLY_OPTIONS: ClassificationOption[] = [
  { value: 'SITE_HARDWARE', label: 'Site', color: 'success' },
  { value: 'SHOP_HARDWARE', label: 'Shop', color: 'info' },
];

export interface ClassificationInputEntry {
  hardwareCategory: string;
  productCode: string;
  unitCost: number;
  classification: string;
}

// #568: a single definition of "this row is fully classified", shared by the guided flow, the review
// grid's unclassified filter, and the step's phase choice so the three cannot drift. A row needs its
// primary axis; a two-axis (PO) row also needs Site/Shop unless its primary is the exempt value
// (By Others), which is out of scope and carries none.
export function isRowClassified(
  row: { classification: string; siteShop?: string },
  opts: { hasSiteShop: boolean; siteShopExemptValue?: string },
): boolean {
  if (row.classification === '') return false;
  if (!opts.hasSiteShop) return true;
  if (opts.siteShopExemptValue && row.classification === opts.siteShopExemptValue) return true;
  return (row.siteShop ?? '') !== '';
}

// #321: project the shared classifications Map into finalize ClassificationInput entries, keeping
// only real Site/Shop values. Re-imports seed the Map with BY_OTHERS (an ownership value, not a
// Site/Shop one) from the exclusion table; those items are out of scope for shop assembly and the
// Classification GraphQL enum only accepts SITE_HARDWARE/SHOP_HARDWARE, so they are dropped here.
// Allow-listing the two valid values also drops any empty/unexpected value.
export function toClassificationInputs(classifications: Map<string, string>): ClassificationInputEntry[] {
  return Array.from(classifications.entries())
    .filter(([, cls]) => cls === 'SITE_HARDWARE' || cls === 'SHOP_HARDWARE')
    .map(([key, cls]) => {
      const [hardwareCategory, productCode, unitCost] = key.split('|');
      return { hardwareCategory, productCode, unitCost: parseFloat(unitCost), classification: cls };
    });
}

// #486: picking Site or Shop on a row says the item is in scope, so the scope axis fills itself
// rather than asking for a second click that can only have one answer. One direction only: a scope
// pick never sets Site/Shop, and an item already carrying a scope - By Others most of all - is left
// exactly as it is. A By Others row renders an em-dash Site/Shop toggle anyway, so the only way to
// reach this with one is a bulk action spanning it.
//
// Returns the same Map when nothing changed, so the caller can skip a re-render.
export function backfillScopeFromSiteShop(
  classifications: Map<string, string>,
  keys: string[],
): Map<string, string> {
  const next = new Map(classifications);
  let changed = false;
  for (const key of keys) {
    if (!next.get(key)) {
      next.set(key, 'BY_UCSH');
      changed = true;
    }
  }
  return changed ? next : classifications;
}
