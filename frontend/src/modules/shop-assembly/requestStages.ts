/**
 * Where a shop-assembly request sits on the ladder the requests list draws as columns.
 *
 * Derived server-side from the request's own status and the state of the pull it minted, so this
 * module is display only: labels, colours, and the two things the list needs to decide - whether the
 * row can still be reopened, and which bucket it belongs in.
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
 * REQUESTED is amber because it is the only stage anybody has to act on - a request waiting for a
 * reviewer is the queue this page exists to clear. The middle two are informational (the warehouse
 * has it), DONE is a success that needs no attention, and REJECTED is off the ladder.
 */
export const STAGE_COLOR: Record<RequestStage, 'warning' | 'info' | 'success' | 'default'> = {
  REQUESTED: 'warning',
  ACCEPTED: 'info',
  PULLING: 'info',
  DONE: 'success',
  REJECTED: 'default',
};

/**
 * Reopen undoes an accept by deleting the pull it minted, so it is only possible while the
 * warehouse has not started that pull. Returns the reason it cannot, or null when it can.
 */
export function reopenBlockedReason(stage: RequestStage): string | null {
  if (stage === 'PULLING') return 'The warehouse has started this pull.';
  if (stage === 'DONE') return 'This pull is complete.';
  return null;
}
