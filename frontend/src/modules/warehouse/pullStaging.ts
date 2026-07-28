// Shared readings of a pull's derived per-opening staging rollup (#343), so the queue column, the
// detail header and the tests cannot drift apart. Change the wording here, not in each view.

/** Fields the backend derives for a pull (`stagingStatus` is null on pulls that have no openings -
 * shipping-out, PR-REPL, legacy - which is "not applicable", never "nothing staged"). */
export interface PullStagingFields {
  stagingStatus?: string | null;
  stagedOpeningCount?: number | null;
  totalOpeningCount?: number | null;
}

/** "4 of 8 staged", or null when staging does not apply to this pull.
 *
 * Deliberately returns null rather than an empty string so a caller has to decide what to render in
 * the not-applicable case instead of drawing an empty chip. */
export function stagingChipLabel(pr: PullStagingFields): string | null {
  if (!pr.stagingStatus || pr.totalOpeningCount == null || pr.totalOpeningCount === 0) return null;
  return `${pr.stagedOpeningCount ?? 0} of ${pr.totalOpeningCount} staged`;
}

/** Chip colour for the staging rollup. Only real system state gets colour (DESIGN.md): nothing
 * staged is neutral, part-staged is the amber "in flight" reading, fully staged is success. */
export function stagingChipColor(pr: PullStagingFields): 'default' | 'warning' | 'success' {
  if (pr.stagingStatus === 'PULLED') return 'success';
  if (pr.stagingStatus === 'PARTIAL') return 'warning';
  return 'default';
}

/** What the queue's phase cell reads off a pull (#367). */
export interface PullPhaseFields extends PullStagingFields {
  status: string;
  pickedAt?: string | null;
  partiallyPicked?: boolean | null;
}

export interface PullPhase {
  label: string;
  color: 'default' | 'warning' | 'info' | 'success' | 'error';
  /** One line under the tag, or null when the label already says everything. */
  detail: string | null;
}

/**
 * Where a pull has got to, as one reading (#367).
 *
 * The queue used to show status and staging as two separate columns, which stopped being enough the
 * moment picking became its own phase: a pull can now be In Progress and have moved no stock, or be
 * In Progress holding a short pick, or be picked and part-staged. All three read as "In Progress"
 * and mean entirely different things to whoever picks up the row next.
 *
 * Short is deliberately its own phase rather than a variant of Picking. It is the one state that
 * needs a person: stock has come off the shelf, purchasing has been told, and somebody has to key
 * the remainder in when it lands.
 */
export function pullPhase(pr: PullPhaseFields): PullPhase {
  if (pr.status === 'CANCELLED') return { label: 'Cancelled', color: 'error', detail: null };
  if (pr.status === 'COMPLETED') return { label: 'Completed', color: 'success', detail: null };
  if (pr.status === 'PENDING') return { label: 'Pending', color: 'warning', detail: 'Not started' };

  if (!pr.pickedAt) {
    return pr.partiallyPicked
      ? { label: 'Short', color: 'error', detail: 'Part-picked - remainder outstanding' }
      : { label: 'Picking', color: 'info', detail: 'Nothing off the shelf yet' };
  }

  const staged = stagingChipLabel(pr);
  return staged
    ? { label: 'Staging', color: 'info', detail: staged }
    : { label: 'Picked', color: 'info', detail: 'Ready to mark pulled' };
}

export interface PullStagingOpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  /** Owed by the schedule. Context only - the warehouse does not pick against this number. */
  quantity: number;
  /** The pick count: what was reserved, what the pull line asks for, what goes on the cart. */
  allocatedQuantity: number;
}

export interface PullStagingOpening {
  id: string;
  pullRequestId: string | null;
  openingId: string;
  openingNumber: string | null;
  leaf: number | null;
  building: string | null;
  floor: string | null;
  pullStatus: string;
  assemblyStatus: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  stagedAt: string | null;
  stagedBy: string | null;
  items: PullStagingOpeningItem[];
}

/** An opening the warehouse can still confirm: its cart is not built yet.
 *
 * One definition shared by the panel's gate and its tests. Deliberately keyed on `pullStatus`
 * alone - the backend enforces the same rule, so a stale client cannot widen it. */
export function isStageable(opening: PullStagingOpening): boolean {
  return opening.pullStatus !== 'PULLED';
}

/** Whether a pull can still be cancelled from the UI's point of view.
 *
 * A pull that has not been approved has moved no inventory (reopen or reject the source request
 * instead), and a cancelled one is terminal. A COMPLETED shop-assembly pull *is* cancellable, since
 * per-opening staging means "completed" there is no more than "every cart is built" - the backend
 * still refuses if assembly has started on any opening, and names which ones.
 *
 * The completed case additionally requires the pull to *have* openings, because that is the whole
 * reason it is allowed: the backend's rule is `SHOP_ASSEMBLY and bool(openings)`, so on a completed
 * PR-REPL or otherwise opening-less pull the button was offered and the server always said no. A
 * control that cannot succeed is worse than an absent one. */
export function isCancellable(pr: {
  status: string;
  source: string;
  totalOpeningCount?: number | null;
}): boolean {
  if (pr.status === 'IN_PROGRESS') return true;
  return (
    pr.status === 'COMPLETED' && pr.source === 'SHOP_ASSEMBLY' && (pr.totalOpeningCount ?? 0) > 0
  );
}
