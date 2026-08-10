// Shared readings of where a pull has got to, so the queue column, the detail header and the tests
// cannot drift apart. Change the wording here, not in each view.

/** What the queue's phase cell reads off a pull (#367). */
export interface PullPhaseFields {
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
 * moment picking became its own phase: a pull can be In Progress and have moved no stock, or be In
 * Progress holding a short pick, or be picked and waiting to be handed over. All three read as
 * "In Progress" and mean entirely different things to whoever picks up the row next.
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

  return { label: 'Picked', color: 'info', detail: 'Ready to hand over' };
}

/**
 * Whether a pull can still be cancelled from the UI's point of view.
 *
 * A pull that has not been started has moved no inventory (reopen or reject the source request
 * instead), and a completed one has handed its hardware over - to the bench or to a shipping desk -
 * which v1 does not follow, so there is nothing left to reverse. The backend enforces the same rule;
 * a control that cannot succeed is worse than an absent one.
 */
export function isCancellable(pr: { status: string }): boolean {
  return pr.status === 'IN_PROGRESS';
}
