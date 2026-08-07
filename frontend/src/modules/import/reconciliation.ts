/**
 * The per-product reconciliation rollup, as pure functions.
 *
 * Split out of ReconciliationStep because the wizard gates Next on the same numbers the step
 * renders (#483). A second, parallel calculation there is a bug waiting to diverge, and what the
 * user is blocked by has to be what they are shown. Nothing here touches React.
 */

import type { ImportPurpose, ReconciliationRow } from './types';
import type { ParsedHardwareItem } from '../../types/hardwareSchedule';
import { aggregationKey, itemGroupKey } from './types';

export interface ProductReconRow {
  id: string; // itemGroupKey: `${hardwareCategory}|${productCode}`
  hardwareCategory: string;
  productCode: string;
  quantityNeeded: number; // sum of HS qty across selected openings
  quantityRequiredByProject: number; // sum of HS qty across ALL openings in schedule
  qtyAvailable: number; // for assembly/shipping eligibility
  statusBreakdown: Map<string, number>; // bucket totals across openings
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
  // The one refusal: ordering this selection would take the project past what its hardware schedule
  // says it needs. A product whose EXISTING commitments already exceed the total is flagged but
  // never blocks - nothing on this screen fixes history, and refusing would strand the user.
  blocksProceed: boolean;
}

export const STATUS_PRIORITY: Record<string, number> = {
  RECEIVED: 0,
  ASSEMBLED: 1,
  SHIPPED_OUT: 2,
  SHIPPING_OUT: 3,
  ASSEMBLING: 4,
  ORDERED: 5,
  PO_DRAFTED: 6,
  NOT_COVERED: 7,
  BY_OTHERS: 8,
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
  if (purpose === 'shipping') {
    return (breakdown.get('RECEIVED') ?? 0) + (breakdown.get('ASSEMBLED') ?? 0);
  }
  return 0;
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
}): ProductReconRow[] {
  const { purpose, reconciliationRows, selectedHardwareItems, allHardwareItems, selectedReconItems } = args;

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
        underlyingOpeningKeys: [],
        existingCommitted: 0,
        selectedNewPOQty: 0,
        projectTotalOrdered: 0,
        projectTotalReceived: 0,
        overCommitAmount: 0,
        blocksProceed: false,
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
    row.qtyAvailable = computeAvailableQty(purpose, row.statusBreakdown);
    row.existingCommitted = COMMITTED_STATUSES.reduce(
      (sum, s) => sum + (row.statusBreakdown.get(s) ?? 0),
      0,
    );
    row.projectTotalOrdered = ORDERED_STATUSES.reduce((sum, s) => sum + (row.statusBreakdown.get(s) ?? 0), 0);
    row.projectTotalReceived = RECEIVED_STATUSES.reduce((sum, s) => sum + (row.statusBreakdown.get(s) ?? 0), 0);
    row.selectedNewPOQty = row.underlyingOpeningKeys
      .filter((k) => selectedReconItems.has(k))
      .reduce((sum, k) => sum + (hsQtyByOpeningKey.get(k) ?? 0), 0);
    const futureCommitted = row.existingCommitted + row.selectedNewPOQty;
    row.overCommitAmount = Math.max(0, futureCommitted - row.quantityRequiredByProject);
    // A re-uploaded schedule with reduced scope can push existing commitments past the new project
    // total on their own. Those rows show the badge but must not block: nothing selectable here
    // fixes them, and refusing to advance would strand the user.
    row.blocksProceed = row.selectedNewPOQty > 0 && futureCommitted > row.quantityRequiredByProject;
  }
  rows.sort((a, b) => {
    const bestA = Math.min(...Array.from(a.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
    const bestB = Math.min(...Array.from(b.statusBreakdown.keys()).map((s) => STATUS_PRIORITY[s] ?? 99));
    return bestA - bestB;
  });
  return rows;
}

