// The words each inventory audit action is shown in, shared by the item's history drawer and the
// location's recent-activity strip (#1896) so the two never name one event differently.
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  RECEIVE: 'Received',
  ADJUSTMENT: 'Qty Adjusted',
  MOVE: 'Moved',
  UNLOCATE: 'Unlocated',
  PUT_AWAY: 'Put Away',
  PULL_DEDUCTION: 'Pull Deduction',
  SPOT_CHECK: 'Spot Check',
  DESTOCK: 'Destocked',
  ALLOCATE_FROM_STOCK: 'Allocated from Stock',
  RECLASSIFY: 'Reclassified',
  REPORT_DEFICIENT: 'Reported Deficient',
  RESOLVE_DEFICIENT: 'Deficiency Resolved',
  TRANSFER: 'Transferred',
  RETURN: 'Returned',
  PULL_RESTOCK: 'Pull Restocked',
  PULL_CANCELLED: 'Pull Cancelled',
  POOL_KIND_CHANGE: 'Kind Changed',
};

/** An action in its words; one added after this list still reads as words, never as its raw code. */
export function auditActionLabel(action: string): string {
  const known = AUDIT_ACTION_LABELS[action];
  if (known) return known;
  const words = action.toLowerCase().replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
