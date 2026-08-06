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

/**
 * One shipping-out request the wizard will create on finalize. There is deliberately no requester
 * field: the import path stamps every request it creates as "Hardware Schedule Import", so the
 * "Requested By" box the step used to show was never read (#438).
 */
export interface ShippingPRDraft {
  requestNumber: string;
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

// ---- Shipping-out coverage (#451) ----------------------------------------------------------
//
// The shipping request is created off the hardware schedule, so Nexus can tell the user what
// belongs with the leaves they picked rather than making them remember. `shippingCoverage` answers
// that per leaf; these types shape it for the builder.

export type HardwareClassification = 'SITE_HARDWARE' | 'SHOP_HARDWARE';
export type CoverageLeafStatus = 'NOT_ASSEMBLED' | 'IN_INVENTORY' | 'SHIP_READY' | 'SHIPPED_OUT';

export interface ShippingCoverageLine {
  hardwareCategory: string;
  productCode: string;
  /** Null when the schedule was never classified - shown as its own group, never guessed at. */
  classification: HardwareClassification | null;
  /** What the schedule says this leaf takes. */
  owedQuantity: number;
  /** What is bolted onto the assembled leaf. Always 0 for site hardware and unassembled leaves. */
  installedQuantity: number;
  /** Already sent or on its way out for this opening: shipped, staged, or on a live request. */
  spokenForQuantity: number;
  /** `owed - installed - spoken for`: what still has to travel loose beside the leaf. */
  suggestedQuantity: number;
  /** Ordered from a vendor and not yet received, project-wide. Not an allocation to this leaf. */
  onOrderQuantity: number;
}

export interface ShippingCoverageLeaf {
  openingNumber: string;
  leaf: number | null;
  status: CoverageLeafStatus;
  openingItemId: string | null;
  /** A live shipping request already holds this leaf - one physical leaf ships once. */
  claimedByRequestNumber: string | null;
  lines: ShippingCoverageLine[];
}

/**
 * One loose line the builder offers, which is a coverage line summed over an opening's leaves.
 *
 * The aggregation is not cosmetic: a LOOSE request line is keyed by (opening, category, product)
 * and carries no leaf, because loose stock is fungible and only a pull tags it onto one
 * (docs/HARDWARE_IDENTITY_LIFECYCLE.md). Two leaves of a pair each owed two hinges are therefore
 * one request line for four, not two lines that would collide on the same key. `perLeaf` keeps the
 * breakdown for display so the user can still see where the four came from.
 */
export interface LooseCoverageRow {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  classification: HardwareClassification | null;
  suggestedQuantity: number;
  /**
   * Units of this row the opening has already been sent, or is in the middle of being sent. Only
   * ever a caption: it is why the offer is smaller than the schedule, so a user who counts the
   * schedule and counts the offer is not left with an unexplained gap.
   */
  spokenForQuantity: number;
  onOrderQuantity: number;
  perLeaf: Array<{ leaf: number | null; quantity: number }>;
}

/** Group heading a loose row belongs under, which is what tells the user *why* it is being offered. */
export type CoverageGroup = 'SITE' | 'SHOP_SKIPPED' | 'UNCLASSIFIED';

export function coverageGroup(row: { classification: HardwareClassification | null }): CoverageGroup {
  if (row.classification === 'SITE_HARDWARE') return 'SITE';
  if (row.classification === 'SHOP_HARDWARE') return 'SHOP_SKIPPED';
  return 'UNCLASSIFIED';
}

export const COVERAGE_GROUP_LABEL: Record<CoverageGroup, string> = {
  SITE: 'Site hardware',
  SHOP_SKIPPED: 'Shop hardware not assembled onto the leaf',
  UNCLASSIFIED: 'Unclassified hardware',
};

export const COVERAGE_GROUP_HINT: Record<CoverageGroup, string> = {
  SITE: 'Installed at site, so it never went through shop assembly and always travels loose.',
  SHOP_SKIPPED:
    'Should have been fitted at the bench. Assembly skipped these units, so they still have to go loose.',
  UNCLASSIFIED:
    'The schedule never said whether these are site or shop hardware. Shown so nothing owed goes unnoticed.',
};

export const COVERAGE_GROUP_ORDER: CoverageGroup[] = ['SITE', 'SHOP_SKIPPED', 'UNCLASSIFIED'];

/**
 * Turn per-leaf coverage into the loose lines the builder can offer, one per
 * (opening, category, product). Lines with nothing left to send are dropped - a leaf whose shop
 * hardware was fully fitted owes nothing loose, and offering it a zero would be noise.
 */
export function buildLooseCoverageRows(leaves: ShippingCoverageLeaf[]): LooseCoverageRow[] {
  const rows = new Map<string, LooseCoverageRow>();
  for (const leaf of leaves) {
    for (const line of leaf.lines) {
      if (line.suggestedQuantity <= 0) continue;
      const key = `${leaf.openingNumber}|${line.hardwareCategory}|${line.productCode}`;
      const existing = rows.get(key);
      if (existing) {
        existing.suggestedQuantity += line.suggestedQuantity;
        existing.spokenForQuantity += line.spokenForQuantity;
        existing.perLeaf.push({ leaf: leaf.leaf, quantity: line.suggestedQuantity });
        // A product that reads site on one leaf and shop on the other is a schedule inconsistency,
        // not something to average. Keep the first non-null so the row still lands in a real group.
        existing.classification = existing.classification ?? line.classification;
      } else {
        rows.set(key, {
          openingNumber: leaf.openingNumber,
          hardwareCategory: line.hardwareCategory,
          productCode: line.productCode,
          classification: line.classification,
          suggestedQuantity: line.suggestedQuantity,
          spokenForQuantity: line.spokenForQuantity,
          onOrderQuantity: line.onOrderQuantity,
          perLeaf: [{ leaf: leaf.leaf, quantity: line.suggestedQuantity }],
        });
      }
    }
  }
  return Array.from(rows.values()).sort(
    (a, b) =>
      a.openingNumber.localeCompare(b.openingNumber) ||
      a.hardwareCategory.localeCompare(b.hardwareCategory) ||
      a.productCode.localeCompare(b.productCode),
  );
}

/** The draft line a loose coverage row becomes when it is added at `quantity`. */
export function looseCoverageItem(row: LooseCoverageRow, quantity: number): ShippingPRItem {
  return {
    itemType: 'LOOSE',
    openingNumber: row.openingNumber,
    hardwareCategory: row.hardwareCategory,
    productCode: row.productCode,
    requestedQuantity: quantity,
  };
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
