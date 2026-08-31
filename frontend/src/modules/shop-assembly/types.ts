/**
 * The shapes the shop-assembly requests page reads, and the pure allocation arithmetic the batch
 * composer runs on them.
 *
 * The arithmetic is here rather than inside the component for the reason `modules/import/composer`
 * gives: the numbers are the part that has to be exactly right, and they are worth testing without
 * rendering anything.
 */

export type OpeningStatus = 'PENDING' | 'BATCHED' | 'DISMISSED';
export type BatchStatus = 'ACTIVE' | 'CANCELLED';
export type PullStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'CANCELLED';

/** One owed line on the request: what an opening was still owed when the PM raised it. */
export interface RequestItem {
  id: string;
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
}

/** One flagged opening's own state - the unit the manager decides about. */
export interface RequestOpening {
  id: string;
  openingNumber: string;
  status: OpeningStatus;
  batchId: string | null;
  dismissedBy: string | null;
  dismissedAt: string | null;
  dismissalReason: string | null;
}

export interface BatchItem {
  id: string;
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  allocatedQuantity: number;
}

/** One dispatch: a subset of the request's openings, allocated and on a warehouse pull. */
export interface RequestBatch {
  id: string;
  sequence: number;
  batchNumber: string;
  status: BatchStatus;
  createdBy: string;
  createdAt: string;
  pullRequestId: string | null;
  pullStatus: PullStatus | null;
  items: BatchItem[];
}

export interface ShopAssemblyRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  status: 'PENDING' | 'APPROVED' | 'REJECTED';
  stage: string;
  createdBy: string;
  createdAt: string;
  approvedBy: string | null;
  approvedAt: string | null;
  rejectedBy: string | null;
  rejectedAt: string | null;
  rejectionReason: string | null;
  integrityNote: string | null;
  returnNote: string | null;
  items: RequestItem[];
  openings: RequestOpening[];
  batches: RequestBatch[];
}

/** One owed line on a pending opening, with the free stock behind it. */
export interface AllocationLine {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
  /** Project-wide free stock for this product - a pool the openings compete for, not a share. */
  availableQuantity: number;
}

export interface AllocationOpening {
  openingNumber: string;
  lines: AllocationLine[];
}

export interface AllocationReview {
  requestId: string;
  requestNumber: string;
  projectId: string;
  status: string;
  createdBy: string;
  createdAt: string;
  integrityNote: string | null;
  openings: AllocationOpening[];
}

/** Allocated quantity per line, keyed by `lineKey`. */
export type Allocation = Map<string, number>;

export const comboKey = (line: { hardwareCategory: string; productCode: string }) =>
  `${line.hardwareCategory}|${line.productCode}`;

/** Identity of one allocatable line. The opening is part of it: the same product on two doors is two
 *  lines, allocated independently out of one pool. */
export const lineKey = (line: { openingNumber: string; hardwareCategory: string; productCode: string }) =>
  `${line.openingNumber}|${comboKey(line)}`;

export function allLines(review: AllocationReview | null | undefined): AllocationLine[] {
  return review?.openings.flatMap((o) => o.lines) ?? [];
}

/**
 * Seed every line at `min(owed, what is left of its product's pool)`, opening by opening.
 *
 * First-opening-first rather than spreading thinly. Half the hardware for one door gets that door
 * onto the bench; a tenth of it on ten doors gets nothing anywhere, and the manager would have to
 * undo the spread by hand before they could dispatch anything at all. Whoever wants a different
 * split moves the numbers themselves, which is the point of allocating at all.
 */
export function seedAllocation(review: AllocationReview | null | undefined): Allocation {
  const remaining = new Map<string, number>();
  const allocation: Allocation = new Map();
  for (const opening of review?.openings ?? []) {
    for (const line of opening.lines) {
      const combo = comboKey(line);
      if (!remaining.has(combo)) remaining.set(combo, line.availableQuantity);
      const free = remaining.get(combo) ?? 0;
      const take = Math.max(0, Math.min(free, line.requestedQuantity));
      allocation.set(lineKey(line), take);
      remaining.set(combo, free - take);
    }
  }
  return allocation;
}

/**
 * What is left of a product's pool once every OTHER included line has taken its share.
 *
 * This is the ceiling one input may be raised to, and it is why the review shows a project-wide
 * number rather than a pre-split one: raising opening A's hinges lowers what opening B may take, and
 * the manager has to see that happen rather than discover it when the batch is refused.
 */
export function ceilingFor(
  line: AllocationLine,
  allocation: Allocation,
  included: Set<string>,
  lines: AllocationLine[],
): number {
  const combo = comboKey(line);
  const key = lineKey(line);
  let takenElsewhere = 0;
  for (const other of lines) {
    const otherKey = lineKey(other);
    if (otherKey === key || comboKey(other) !== combo) continue;
    if (!included.has(other.openingNumber)) continue;
    takenElsewhere += allocation.get(otherKey) ?? 0;
  }
  return Math.max(0, Math.min(line.requestedQuantity, line.availableQuantity - takenElsewhere));
}

export type OpeningCoverage = 'FULL' | 'PARTIAL' | 'NONE';

/** How much of what an opening is owed this batch would actually send it. */
export function openingCoverage(lines: AllocationLine[], allocation: Allocation): OpeningCoverage {
  let owed = 0;
  let allocated = 0;
  for (const line of lines) {
    owed += line.requestedQuantity;
    allocated += allocation.get(lineKey(line)) ?? 0;
  }
  if (allocated <= 0) return 'NONE';
  return allocated >= owed ? 'FULL' : 'PARTIAL';
}

/** Per-product totals across the whole batch: owed, free, and what it would take (#644). */
export interface ProductSummaryRow {
  hardwareCategory: string;
  productCode: string;
  owed: number;
  available: number;
  allocated: number;
}

export function productSummary(
  review: AllocationReview | null | undefined,
  allocation: Allocation,
  included: Set<string>,
): ProductSummaryRow[] {
  const rows = new Map<string, ProductSummaryRow>();
  for (const line of allLines(review)) {
    if (!included.has(line.openingNumber)) continue;
    const key = comboKey(line);
    const row = rows.get(key) ?? {
      hardwareCategory: line.hardwareCategory,
      productCode: line.productCode,
      owed: 0,
      // Availability is a property of the product, not of the line, so it is set rather than summed -
      // adding it per line would multiply one pool by however many openings want it.
      available: line.availableQuantity,
      allocated: 0,
    };
    row.owed += line.requestedQuantity;
    row.allocated += allocation.get(lineKey(line)) ?? 0;
    rows.set(key, row);
  }
  return [...rows.values()].sort(
    (a, b) => a.hardwareCategory.localeCompare(b.hardwareCategory) || a.productCode.localeCompare(b.productCode),
  );
}

/** One line as `createShopAssemblyBatch` takes it. */
export interface BatchLineInput {
  openingNumber: string;
  hardwareCategory: string;
  productCode: string;
  allocatedQuantity: number;
}

/**
 * The exact payload the batch sends: every included opening's lines that carry a quantity.
 *
 * A line allocated nothing is dropped rather than sent as a zero - it would reserve nothing and put
 * a pick on the sheet the warehouse cannot fill. An opening whose lines are ALL zero therefore names
 * itself nowhere in the payload, and so is not batched at all: it stays pending for a later batch,
 * which is exactly what should happen to an opening whose hardware has not arrived.
 */
export function buildBatchLines(
  review: AllocationReview | null | undefined,
  allocation: Allocation,
  included: Set<string>,
): BatchLineInput[] {
  const lines: BatchLineInput[] = [];
  for (const line of allLines(review)) {
    if (!included.has(line.openingNumber)) continue;
    const quantity = allocation.get(lineKey(line)) ?? 0;
    if (quantity <= 0) continue;
    lines.push({
      openingNumber: line.openingNumber,
      hardwareCategory: line.hardwareCategory,
      productCode: line.productCode,
      allocatedQuantity: quantity,
    });
  }
  return lines;
}

/** Openings the batch would actually dispatch - those with at least one line carrying a quantity. */
export function batchedOpeningNumbers(
  review: AllocationReview | null | undefined,
  allocation: Allocation,
  included: Set<string>,
): string[] {
  return [...new Set(buildBatchLines(review, allocation, included).map((l) => l.openingNumber))];
}
