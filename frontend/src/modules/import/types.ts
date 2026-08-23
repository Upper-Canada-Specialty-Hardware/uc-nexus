import type { ParsedHardwareItem } from '../../types/hardwareSchedule';

export type AggregatedHardwareItem = Omit<ParsedHardwareItem, 'material_id'>;

export function aggregationKey(hi: { opening_number: string; product_code: string; hardware_category: string }) {
  return `${hi.opening_number}|${hi.product_code}|${hi.hardware_category}`;
}

// 'schedule' (#608 follow-up) replaces a project's persisted hardware schedule from a newer XML -
// replace-only, no PO drafting and no request composition. 'shipping' is gone: that composer moved
// to the request workspace, and the fossil /app/import?purpose=shipping redirect matches the raw URL
// param, not this type.
export type ImportPurpose = 'po' | 'assembly' | 'schedule';

// #565: how a PO import picks what to order. 'openings' walks the door schedule and selects openings;
// 'hardware' selects products directly and takes quantities from the schedule. Both feed the same PO
// drafts output - the only difference is which axis of the same opening-level items gets filtered.
export type SelectionMode = 'openings' | 'hardware';

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
  /** The dominant SITE/SHOP classification of this product on the schedule (#610), or null when the
   *  schedule never named it - lets a loose extras line carry the same chip/framing as catalog rows. */
  classification: HardwareClassification | null;
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

// One (category, product) row of `hardwareStatusByProduct`, project-wide. The reconciliation step
// reads it so its Lifecycle Breakdown is the SAME computation the admin Hardware Status page renders
// (see backend get_hardware_status_by_product) - the two can never disagree because there is one
// source. onHand is current inventory with completed pulls already deducted; receivedQuantity is the
// cumulative PO receipt count, which is not shown as its own chip since it overlaps onHand +
// sentToShop + stagedForShipping + shippedOut.
export interface HardwareStatusRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  notPurchased: number;
  poDrafted: number;
  onOrder: number;
  receivedQuantity: number;
  onHand: number;
  /** RETURN_TO_PROJECT shipment-return units: back inside onHand while still counted in the gross
   *  shippedOut, so "where the units are" sums must subtract this once. */
  returnedToProject: number;
  sentToShop: number;
  stagedForShipping: number;
  shippedOut: number;
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

// #588: the document types the buyer can attach while still composing the draft. Only the two that
// can exist before the PO does - vendor acknowledgement / generated PO / packing slip are produced
// downstream and stay PO-detail-only.
export type DraftAttachmentType = 'PO_DOCUMENT' | 'MISCELLANEOUS';

// #588: a file the buyer attached to a draft before the PO exists. Held client-side with the raw
// File; uploaded onto the created PO after finalize mints it. `id` is a local key for the list, not
// a server id.
export interface DraftAttachment {
  id: string;
  file: File;
  documentType: DraftAttachmentType;
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
  // #588: documents the buyer pre-attached; land on the PO this draft creates. Optional so the pure
  // reducers and their tests can build a draft without them.
  attachments?: DraftAttachment[];
}

// #627: per-product seed quantity for the hardware pathway's Order Qty column. The override is keyed
// by itemGroupKey (`category|product`) while the draft line is keyed by productKey (`product|category`),
// so the translation happens here at the seed boundary. Default (no override) is the product's full
// schedule total; an override caps it at min(override, total). openings-mode passes an empty/undefined
// map, so the seed is the full total exactly as before.
function seededLineQty(
  total: number,
  representativeItem: AggregatedHardwareItem,
  orderQtyOverrides?: Map<string, number>,
): number {
  const override = orderQtyOverrides?.get(itemGroupKey(representativeItem));
  return override === undefined ? total : Math.min(override, total);
}

// Raw per-product totals for one vendor group, plus a representative item per product so the seed can
// translate productKey -> itemGroupKey for the Order Qty override lookup. Insertion order follows first
// occurrence, which is the order products appeared in the selection.
function productTotals(
  items: AggregatedHardwareItem[],
): { totals: Map<string, number>; repByPk: Map<string, AggregatedHardwareItem> } {
  const totals = new Map<string, number>();
  const repByPk = new Map<string, AggregatedHardwareItem>();
  for (const hi of items) {
    const pk = productKey(hi);
    totals.set(pk, (totals.get(pk) ?? 0) + hi.item_quantity);
    if (!repByPk.has(pk)) repByPk.set(pk, hi);
  }
  return { totals, repByPk };
}

// Seed one draft per manufacturer group at full quantity - the starting point the buyer then slices.
// Unchecked by default (nothing is ordered until the buyer says so), same as the old vendor selection.
// #627: orderQtyOverrides caps a product's seeded line at the buyer's Order Qty (hardware pathway only).
export function seedDraftGroups(
  vendorGroups: Map<string, AggregatedHardwareItem[]>,
  orderQtyOverrides?: Map<string, number>,
): DraftGroup[] {
  const groups: DraftGroup[] = [];
  for (const [vendor, items] of vendorGroups) {
    const { totals, repByPk } = productTotals(items);
    const lines = new Map<string, number>();
    for (const [pk, total] of totals) {
      lines.set(pk, seededLineQty(total, repByPk.get(pk)!, orderQtyOverrides));
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
// request composer uses with its offer signature. #627: the seeded (override-capped) quantities are
// folded in, so changing an Order Qty re-seeds the drafts rather than leaving them at the old total.
export function draftSeedSignature(
  vendorGroups: Map<string, AggregatedHardwareItem[]>,
  orderQtyOverrides?: Map<string, number>,
): string {
  const parts: string[] = [];
  for (const [vendor, items] of vendorGroups) {
    const { totals, repByPk } = productTotals(items);
    const byProduct = new Map<string, number>();
    for (const [pk, total] of totals) {
      byProduct.set(pk, seededLineQty(total, repByPk.get(pk)!, orderQtyOverrides));
    }
    const sorted = Array.from(byProduct.entries()).sort(([a], [b]) => a.localeCompare(b));
    parts.push(`${vendor}::${sorted.map(([k, q]) => `${k}=${q}`).join(',')}`);
  }
  return parts.join('||');
}

// One aggregated hardware line the classification step works on. Keyed by classificationKey
// (category|product|cost) - the grain both classification axes are set at - and carrying the opening
// attributes (#486) so the classifier sees the door each item belongs to.
export interface ClassificationRow {
  id: string;
  openingNumber: string;
  hand: string;
  doorQuantity: number | null;
  doorMaterial: string;
  frameType: string;
  productCode: string;
  hardwareCategory: string;
  vendorNo: string;
  listPrice: number | null;
  vendorDiscount: number | null;
  unitCost: number;
  itemQuantity: number;
  classificationKey: string;
  classification: string;
  // Issue #216: second axis (Site/Shop) for PO-purpose imports; '' = not yet classified.
  siteShop?: string;
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
