import { useCallback, useRef } from 'react';

/**
 * An idempotency key per submission, for a create the server dedupes by key (#1552).
 *
 * Warehouse wifi drops after the server commits but before the reply lands: the dialog shows an error,
 * keeps its input, and the user sends again. Sending the same thing again reuses the key, so the server
 * hands back what the first attempt wrote instead of writing it twice. Changing what is sent mints a new
 * key: that is a new decision, and the server must not answer it with the old one's row.
 */
export function useSubmissionKey(): (payload: unknown) => string {
  const current = useRef<{ payload: string; key: string } | null>(null);
  return useCallback((payload: unknown) => {
    const serialized = JSON.stringify(payload);
    if (current.current?.payload !== serialized) {
      current.current = { payload: serialized, key: crypto.randomUUID() };
    }
    return current.current.key;
  }, []);
}
