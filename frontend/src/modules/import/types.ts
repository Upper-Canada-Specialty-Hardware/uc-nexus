import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

export type AggregatedHardwareItem = Omit<ParsedHardwareItem, 'material_id'>;

export function aggregationKey(hi: { opening_number: string; product_code: string; hardware_category: string }) {
  return `${hi.opening_number}|${hi.product_code}|${hi.hardware_category}`;
}

export type ImportPurpose = 'po' | 'assembly' | 'shipping';

// A line on a shipping pull request draft. The two item types are not variants of the same thing
// (#335): OPENING_ITEM moves an assembled door leaf that hardware was already tagged onto at shop
// assembly, so it names an OpeningItem and never touches loose stock. LOOSE tags fungible inventory
// onto an opening for the first time. See docs/HARDWARE_IDENTITY_LIFECYCLE.md.
export interface ShippingPRItem {
  itemType: 'OPENING_ITEM' | 'LOOSE';
  openingNumber: string;
  openingItemId?: string;
  /** Door leaf (#311): set on OPENING_ITEM lines from the assembled unit. Null/absent on LOOSE. */
  leaf?: number | null;
  hardwareCategory?: string;
  productCode?: string;
  requestedQuantity: number;
}

/**
 * Identity of a draft line, for add/remove toggling and checkbox state. An assembled leaf is its
 * OpeningItem; a loose line is its (opening, category, product) triple, which is leaf-agnostic
 * because loose stock is fungible.
 */
export function shippingPRItemKey(item: ShippingPRItem): string {
  return item.itemType === 'OPENING_ITEM'
    ? `OI|${item.openingItemId}`
    : `LOOSE|${item.openingNumber}|${item.hardwareCategory}|${item.productCode}`;
}

export interface ShippingPRDraft {
  requestNumber: string;
  requestedBy: string;
  items: ShippingPRItem[];
}

/** An assembled door leaf (or legacy whole-opening unit) offered for shipping selection (#335). */
export interface AssembledLeafCandidate {
  id: string;
  openingNumber: string;
  leaf: number | null;
  installedHardware: Array<{ productCode: string; quantity: number }>;
  /**
   * Units of this leaf's hardware still owed to it (#341): condemned and not yet replaced, plus
   * replacements that have arrived but are not fitted. > 0 means the leaf is physically short of the
   * hardware list it would ship under, so it is flagged and takes an explicit confirm.
   */
  awaitingReplacementQuantity: number;
  /**
   * Units the schedule owed this leaf that its shop-assembly request never pulled - they were not
   * available to claim when it was sent. The other half of the same "this leaf is short" decision,
   * and counted apart because the remedies differ: an awaiting-replacement unit has a pull in
   * flight and waiting fixes it, while one of these needs purchasing and then reallocation.
   */
  neverPulledQuantity: number;
}

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

/**
 * One combo the current selection would claim more of than is available (#342). Computed in the
 * browser from the same numbers the server gates on, so the wizard can refuse to submit a selection
 * that cannot fit - the creator refines it here rather than having the whole finalize bounce.
 */
export interface AvailabilityShortfall {
  hardwareCategory: string;
  productCode: string;
  requested: number;
  available: number;
  reserved: number;
  short: number;
}

/**
 * Compare a per-combo demand against a per-combo availability lookup. `demand` is keyed by
 * `itemGroupKey` (category|product); combos with no availability row at all count as zero
 * available, which is exactly how the server treats a product the project has never received.
 */
export function computeAvailabilityShortfalls(
  demand: Map<string, number>,
  availability: Map<string, InventoryAvailabilityRow>,
): AvailabilityShortfall[] {
  const rows: AvailabilityShortfall[] = [];
  for (const [key, requested] of demand) {
    if (requested <= 0) continue;
    const row = availability.get(key);
    const available = row?.availableQuantity ?? 0;
    if (requested > available) {
      const [hardwareCategory, productCode] = key.split('|');
      rows.push({
        hardwareCategory,
        productCode,
        requested,
        available,
        reserved: row?.reservedQuantity ?? 0,
        short: requested - available,
      });
    }
  }
  rows.sort(
    (a, b) =>
      a.hardwareCategory.localeCompare(b.hardwareCategory) || a.productCode.localeCompare(b.productCode),
  );
  return rows;
}

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
  { value: 'BY_UCSH', label: 'By UCSH', color: 'success' },
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
