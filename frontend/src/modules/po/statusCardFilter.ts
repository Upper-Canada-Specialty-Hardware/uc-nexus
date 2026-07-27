// The pure decision behind the clickable PO stat cards (#316). The counts and the table below them
// describe the same set, so reading a count and then hunting the filter row to see those rows was
// busywork - a click on the card is the shortcut.
//
// Kept out of index.tsx so the toggle rules are pinned by tests rather than by rendering the whole
// list page, which needs the projects / statistics / outbox queries mocked to render at all.

/** Only the fields the card logic touches. The page's FilterState is wider and passes through. */
export interface StatusFilterable {
  statuses: Set<string>;
}

/**
 * Whether a card should read as active.
 *
 * Exactly-one, not "includes": a card is a shortcut to a single status, so it must not light up as a
 * side effect of a broader multi-select made in the filter row - that would claim the table is showing
 * one status when it is showing three. Total is active when nothing is filtered by status.
 */
export function isStatusCardActive<T extends StatusFilterable>(filterState: T, status: string | null): boolean {
  if (status === null) return filterState.statuses.size === 0;
  return filterState.statuses.size === 1 && filterState.statuses.has(status);
}

/**
 * Apply a card click. Sets the status filter to just that status; clicking the already-active card,
 * or Total, clears it - so the cards can never trap you in a filtered view with no way back out.
 *
 * Every other filter dimension is preserved: the card is a status shortcut, not a reset button, and
 * silently dropping someone's project or date filter would be a worse surprise than the click is worth.
 */
export function toggleStatusCard<T extends StatusFilterable>(filterState: T, status: string | null): T {
  const clear = status === null || isStatusCardActive(filterState, status);
  return { ...filterState, statuses: clear ? new Set<string>() : new Set([status]) };
}
