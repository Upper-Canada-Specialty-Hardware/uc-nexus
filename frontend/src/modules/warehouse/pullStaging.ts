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

export interface PullStagingOpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
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
