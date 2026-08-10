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
