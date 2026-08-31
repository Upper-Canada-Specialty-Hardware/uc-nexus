/**
 * Where a request sits on the ladder the requests lists draw as columns. Shared verbatim by the
 * shop-assembly and shipping-out boards, which ask the identical question of a different request.
 *
 * Derived server-side from the request's own status and the state of the pull(s) it minted - one for
 * shipping out, one per batch for shop assembly (#646) - so this module is display only: labels,
 * colours, and the one thing a list has to decide for itself.
 *
 * The ladder ends at DONE because that is where v1 stops following the hardware. A completed
 * shop-assembly pull is a terminal exit: the shop takes its cart to the bench, and what happens
 * there is not tracked.
 */
export type RequestStage = 'REQUESTED' | 'ACCEPTED' | 'PULLING' | 'DONE' | 'REJECTED';

export const STAGE_ORDER: RequestStage[] = ['REQUESTED', 'ACCEPTED', 'PULLING', 'DONE'];

export const STAGE_LABEL: Record<RequestStage, string> = {
  REQUESTED: 'Requested',
  ACCEPTED: 'Accepted',
  PULLING: 'Pulling',
  DONE: 'Done',
  REJECTED: 'Rejected',
};

/**
 * One colour per rung, and only one of them is an alert.
 *
 * REQUESTED is amber because it is the only stage anybody has to act on - a request with openings
 * still waiting is the queue this page exists to clear, however many batches are already out. The
 * middle two are informational (the warehouse has it), DONE is a success that needs no attention,
 * and REJECTED is off the ladder.
 */
export const STAGE_COLOR: Record<RequestStage, 'warning' | 'info' | 'success' | 'default'> = {
  REQUESTED: 'warning',
  ACCEPTED: 'info',
  PULLING: 'info',
  DONE: 'success',
  REJECTED: 'default',
};

/**
 * A batch's pull, as a person reads it. Raw enums never reach a human, and `IN_PROGRESS` is the one
 * that would read worst - it is what the warehouse is doing right now.
 */
export const PULL_STATUS_LABEL: Record<string, string> = {
  PENDING: 'Not started',
  IN_PROGRESS: 'Pulling',
  COMPLETED: 'Done',
  CANCELLED: 'Cancelled',
};

/** The status hue a batch's pull earns: warning while it waits on somebody, info while the
 *  warehouse has it, success once it is done, and nothing once it is off the ladder. */
export const PULL_STATUS_COLOR: Record<string, 'warning' | 'info' | 'success' | 'default'> = {
  PENDING: 'warning',
  IN_PROGRESS: 'info',
  COMPLETED: 'success',
  CANCELLED: 'default',
};

/**
 * Reopen undoes an accept by deleting the pull it minted, so it is only possible while the
 * warehouse has not started that pull. Returns the reason it cannot, or null when it can.
 *
 * The shipping-out board's, and only its: a shop-assembly request has no single accept to undo since
 * #646, and its batch-level equivalent decides per batch off `pullStatus` rather than off the
 * request's own rung.
 */
export function reopenBlockedReason(stage: RequestStage): string | null {
  if (stage === 'PULLING') return 'The warehouse has started this pull.';
  if (stage === 'DONE') return 'This pull is complete.';
  return null;
}
