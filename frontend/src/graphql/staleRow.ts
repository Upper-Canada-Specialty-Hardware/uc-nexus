import { CombinedGraphQLErrors } from '@apollo/client/errors';

/** True when the server refused a correction because the row moved since the dialog showed it
 * (#1315, #1316, #1318). The dialog's count comes from its parent's snapshot, so a retry from the
 * same dialog would be refused again: the caller closes it, and reopening reads the fresh row. */
export function isStaleRowRefusal(err: unknown): boolean {
  return (
    CombinedGraphQLErrors.is(err) &&
    err.errors.some((e) => e.extensions?.code === 'CONFLICT' && e.extensions?.field === 'expected_quantity')
  );
}
