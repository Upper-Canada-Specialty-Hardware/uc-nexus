import { CombinedGraphQLErrors } from '@apollo/client/errors';

const STALE_FIELDS = new Set(['expected_quantity', 'expected_deficient_quantity']);

/** True when the server refused a correction because the row moved since the dialog showed it
 * (#1315, #1316, #1318) - its count, or for a deficiency report or resolve its flagged count (#1552).
 * The dialog's count comes from its parent's snapshot, so a retry from the same dialog would be
 * refused again: the caller closes it, and reopening reads the fresh row. A delta move's own first
 * attempt, committed behind a lost reply, is refused this way too, which is what keeps it from
 * landing twice (#1552). */
export function isStaleRowRefusal(err: unknown): boolean {
  return (
    CombinedGraphQLErrors.is(err) &&
    err.errors.some(
      (e) => e.extensions?.code === 'CONFLICT' && STALE_FIELDS.has(String(e.extensions?.field ?? '')),
    )
  );
}
