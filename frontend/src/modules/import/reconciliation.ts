/**
 * The per-product reconciliation rollup, as pure functions.
 *
 * Split out of ReconciliationStep because the wizard gates Next on the same numbers the step
 * renders (#483). A second, parallel calculation there is a bug waiting to diverge, and what the
 * user is blocked by has to be what they are shown. Nothing here touches React.
 */

import type { HardwareStatusRow, ImportPurpose, ReconciliationRow } from './types';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';
import { aggregationKey, itemGroupKey } from './types';

export interface ProductReconRow {
  id: string; // itemGroupKey: `${hardwareCategory}|${productCode}`
  hardwareCategory: string;
  productCode: string;
  quantityNeeded: number; // sum of HS qty across selected openings
  quantityRequiredByProject: number; // sum of HS qty across ALL openings in schedule
  qtyAvailable: number; // for assembly eligibility
  statusBreakdown: Map<string, number>; // bucket totals across openings (recon PO-chain; drives qtyAvailable)
  // What the Lifecycle Breakdown chips render. Project-wide, sourced from `hardwareStatusByProduct`
  // so it matches the admin Hardware Status dashboard exactly. Falls back to `statusBreakdown` when
  // no dashboard row is available (still loading, an excluded By-Others product, or a product the
  // persisted schedule has never seen).
  lifecycleBreakdown: Map<string, number>;
  underlyingOpeningKeys: string[]; // (opening, product, category) keys
  existingCommitted: number; // sum of all non-NOT_COVERED, non-BY_OTHERS bucket qty
  selectedNewPOQty: number; // HS qty for selected (opening, product, category) keys
  // Everything the project has actually placed on a PO: ORDERED and every state past it. Shown as
  // its own column (#483) - "how much of this has the project already bought" is the question the
  // buyer is answering, and it was only derivable by adding up status chips.
  projectTotalOrdered: number;
  // Everything that reached the warehouse and beyond. Can never exceed projectTotalOrdered: you
  // cannot receive what was never ordered.
  projectTotalReceived: number;
  // #483: measured against quantityRequiredByProject, never against the selected openings. Opening
  // identity is not a thing at this step - the selection is a quality-of-life way to decide what to
  // buy, and the hardware lands in fungible project inventory rather than against the openings that
  // were ticked. So there is no such thing as over-committing an opening, only the project.
  overCommitAmount: number;
  // #567: ordering this selection would take the project past what its hardware schedule says it
  // needs. A warning now, not a refusal - the buyer is asked to confirm at Next and may proceed
  // anyway. True only when the CURRENT selection is what pushes past the total: a product whose
  // EXISTING commitments already exceed it (with nothing newly selected here) is not flagged, since
  // nothing on this screen changes history.
  overOrdersProject: boolean;
}

// Chip/row ordering, read left-to-right as the hardware pipeline (schedule -> shipped), so the
// reconciliation chips line up with the admin Hardware Status columns. The dashboard-sourced keys and
// the legacy recon keys are never mixed in one row, so sharing a scale is only about consistent
// ordering, not about the two vocabularies coexisting.
export const STATUS_PRIORITY: Record<string, number> = {
  // Dashboard-sourced (the default now).
  NOT_PURCHASED: 0,
  PO_DRAFTED: 1,
  ON_ORDER: 2,
  IN_INVENTORY: 3,
  SENT_TO_SHOP: 4,
  STAGED: 5,
  SHIPPED_OUT: 6,
  // Legacy recon fallback keys, aligned to the same pipeline positions.
  NOT_COVERED: 0,
  ORDERED: 2,
  RECEIVED: 3,
  ASSEMBLING: 4,
  ASSEMBLED: 5,
  SHIPPING_OUT: 5,
  BY_OTHERS: 7,
};

// Placed on a PO, in every sense that counts against the project's need. PO_DRAFTED is in here
// because a draft becomes an order: letting a second draft push past the total would only move the
// over-order one step later, to a registration nobody is watching.
const COMMITTED_STATUSES = [
  'PO_DRAFTED',
  'ORDERED',
  'RECEIVED',
  'ASSEMBLING',
  'ASSEMBLED',
  'SHIPPING_OUT',
  'SHIPPED_OUT',
] as const;

// Actually on a GP PO. PO_DRAFTED is deliberately absent - a draft has not been ordered.
const ORDERED_STATUSES = ['ORDERED', 'RECEIVED', 'ASSEMBLING', 'ASSEMBLED', 'SHIPPING_OUT', 'SHIPPED_OUT'] as const;

// In the warehouse or past it. Can never exceed the ordered total.
const RECEIVED_STATUSES = ['RECEIVED', 'ASSEMBLING', 'ASSEMBLED', 'SHIPPING_OUT', 'SHIPPED_OUT'] as const;

function computeAvailableQty(purpose: ImportPurpose, breakdown: Map<string, number>): number {
  if (purpose === 'assembly') {
    return breakdown.get('RECEIVED') ?? 0;
  }
  return 0;
}

// The chips, from the project-wide dashboard row. receivedQuantity is deliberately absent - it is the
// cumulative PO-receipt count and would double-count against onHand + sentToShop + staged + shipped,
// which is where those received units actually are now. A pull that has not been picked yet is still
// on the shelf, so it sits in onHand until it completes - the same rule the dashboard uses.
function buildLifecycleBreakdown(ds: HardwareStatusRow): Map<string, number> {
  const m = new Map<string, number>();
  const put = (key: string, qty: number) => {
    if (qty > 0) m.set(key, qty);
  };
  put('NOT_PURCHASED', ds.notPurchased);
  put('PO_DRAFTED', ds.poDrafted);
  put('ON_ORDER', ds.onOrder);
  put('IN_INVENTORY', ds.onHand);
  put('SENT_TO_SHOP', ds.sentToShop);
  put('STAGED', ds.stagedForShipping);
  put('SHIPPED_OUT', ds.shippedOut);
  return m;
}

/**
 * The per-product reconciliation rollup (#483).
 *
 * Pure and exported because the step renders it and the wizard gates Next on it. A second,
 * parallel calculation in the wizard is a bug waiting to diverge, and the numbers the user is
 * blocked by have to be the numbers they are shown.
 */
export function buildProductReconRows(args: {
  purpose: ImportPurpose;
  reconciliationRows: ReconciliationRow[];
  selectedHardwareItems: ParsedHardwareItem[];
  allHardwareItems: ParsedHardwareItem[];
  selectedReconItems: Set<string>;
  // Project-wide lifecycle state keyed by `${hardware_category}|${product_code}`. Optional: when it
  // is not supplied (unit tests, or a render before the query resolves) the row falls back to the
  // recon PO-chain breakdown, which is exactly the pre-dashboard behaviour.
  hardwareStatusByProduct?: Map<string, HardwareStatusRow>;
  // Real reservation-aware availability per `${hardware_category}|${product_code}` (on_hand -
  // deficient - reserved), from projectInventoryAvailability - the same number the request creation
  // gate applies. When supplied it drives qtyAvailable for the assembly eligibility, instead
  // of the recon RECEIVED bucket, which is blind to inventory that arrived off-PO. Absent for the PO
  // purpose (qtyAvailable is unused there) and in unit tests.
  availableByProduct?: Map<string, number>;
}): ProductReconRow[] {
  const {
    purpose,
    reconciliationRows,
    selectedHardwareItems,
    allHardwareItems,
    selectedReconItems,
    hardwareStatusByProduct,
    availableByProduct,
  } = args;

  const qtyNeededByProduct = new Map<string, number>();
  const hsQtyByOpeningKey = new Map<string, number>();
  for (const hi of selectedHardwareItems) {
    const key = itemGroupKey(hi);
    qtyNeededByProduct.set(key, (qtyNeededByProduct.get(key) ?? 0) + hi.item_quantity);
    const ak = aggregationKey(hi);
    hsQtyByOpeningKey.set(ak, (hsQtyByOpeningKey.get(ak) ?? 0) + hi.item_quantity);
  }
  const qtyRequiredByProjectByProduct = new Map<string, number>();
  for (const hi of allHardwareItems) {
    const key = itemGroupKey(hi);
    qtyRequiredByProjectByProduct.set(key, (qtyRequiredByProjectByProduct.get(key) ?? 0) + hi.item_quantity);
  }

  const map = new Map<string, ProductReconRow>();
  // Deduped alongside the rows rather than with `underlyingOpeningKeys.includes`, which is a scan
  // of every key already collected for that product on every row. A schedule-wide selection puts
  // thousands of openings behind one product, and the scan turns quadratic there - enough to hang
  // the tab for the whole aggregation.
  const openingKeysByProduct = new Map<string, Set<string>>();
  for (const row of reconciliationRows) {
    const productKey = `${row.hardwareCategory}|${row.productCode}`;
    const openingKey = `${row.openingNumber}|${row.productCode}|${row.hardwareCategory}`;
    let entry = map.get(productKey);
    if (!entry) {
      entry = {
        id: productKey,
        hardwareCategory: row.hardwareCategory,
        productCode: row.productCode,
        quantityNeeded: qtyNeededByProduct.get(productKey) ?? 0,
        quantityRequiredByProject: qtyRequiredByProjectByProduct.get(productKey) ?? 0,
        qtyAvailable: 0,
        statusBreakdown: new Map(),
        lifecycleBreakdown: new Map(),
        underlyingOpeningKeys: [],
        existingCommitted: 0,
        selectedNewPOQty: 0,
        projectTotalOrdered: 0,
        projectTotalReceived: 0,
        overCommitAmount: 0,
        overOrdersProject: false,
      };
      map.set(productKey, entry);
      openingKeysByProduct.set(productKey, new Set());
    }
    openingKeysByProduct.get(productKey)!.add(openingKey);
    entry.statusBreakdown.set(row.status, (entry.statusBreakdown.get(row.status) ?? 0) + row.quantity);
  }

  const rows = Array.from(map.values());
  for (const row of rows) {
    row.underlyingOpeningKeys = Array.from(openingKeysByProduct.get(row.id) ?? []);
    // qtyAvailable is the assembly "available to pull" number, a genuinely different
    // question from the lifecycle chips. It reads real reservation-aware inventory when supplied -
    // what is physically on the shelf and unclaimed - and only falls back to the recon RECEIVED
    // bucket (loading, or the PO purpose where it is unused) when it is not.
    row.qtyAvailable = availableByProduct
      ? (availableByProduct.get(row.id) ?? 0)
      : computeAvailableQty(purpose, row.statusBreakdown);
    row.selectedNewPOQty = row.underlyingOpeningKeys
      .filter((k) => selectedReconItems.has(k))
      .reduce((sum, k) => sum + (hsQtyByOpeningKey.get(k) ?? 0), 0);

    // An excluded (By Others) product is short-circuited by reconcile to a single BY_OTHERS bucket;
    // it is not UC Hardware's to order or track, so it keeps that chip rather than borrowing the
    // dashboard's real lifecycle.
    const isExcluded = row.statusBreakdown.has('BY_OTHERS');
    const ds = isExcluded ? undefined : hardwareStatusByProduct?.get(row.id);

    if (ds) {
      // received = ordered - onOrder, so onOrder + received is everything placed on a PO, and
      // poDrafted + that is everything committed toward the project's need.
      row.lifecycleBreakdown = buildLifecycleBreakdown(ds);
      row.projectTotalOrdered = ds.onOrder + ds.receivedQuantity;
      row.projectTotalReceived = ds.receivedQuantity;
      // Count units that EXIST, whatever their origin, not just PO receipts. receivedQuantity is the
      // cumulative PO-receipt count and misses off-PO stock (the SharePoint migration, shipment
      // returns, stock allocations); onHand + sentToShop + staged + shipped is where units actually
      // are now and picks that up. For pure-PO stock the two are equal, so max() leaves it unchanged;
      // for migrated stock the max is the real figure, which is what stops the buyer re-buying units
      // that already exist. projectTotalReceived above stays PO receipts - that column is about receipts.
      const existingReceived = Math.max(
        ds.receivedQuantity,
        ds.onHand + ds.sentToShop + ds.stagedForShipping + ds.shippedOut,
      );
      row.existingCommitted = ds.poDrafted + ds.onOrder + existingReceived;
    } else {
      // Fallback (no dashboard row yet, or an excluded product): the pre-dashboard recon numbers.
      row.lifecycleBreakdown = row.statusBreakdown;
      row.existingCommitted = COMMITTED_STATUSES.reduce((sum, s) => sum + (row.statusBreakdown.get(s) ?? 0), 0);
      row.projectTotalOrdered = ORDERED_STATUSES.reduce((sum, s) => sum + (row.statusBreakdown.get(s) ?? 0), 0);
      row.projectTotalReceived = RECEIVED_STATUSES.reduce((sum, s) => sum + (row.statusBreakdown.get(s) ?? 0), 0);
    }

    const futureCommitted = row.existingCommitted + row.selectedNewPOQty;
    row.overCommitAmount = Math.max(0, futureCommitted - row.quantityRequiredByProject);
    // A re-uploaded schedule with reduced scope can push existing commitments past the new project
    // total on their own. Those rows show the badge but do not warn: nothing selectable here fixes
    // them, so gating the Next confirm on them would strand the user.
    row.overOrdersProject = row.selectedNewPOQty > 0 && futureCommitted > row.quantityRequiredByProject;
  }
  rows.sort((a, b) => {
    const bestA = Math.min(...Array.from(a.lifecycleBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
    const bestB = Math.min(...Array.from(b.lifecycleBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
    return bestA - bestB;
  });
  return rows;
}

