import { useCallback, useState } from 'react';
import { useApolloClient } from '@apollo/client/react';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { GET_RECEIVE_DRAFT } from '../../graphql/warehouse';
import { RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import type { ReceiveDraft } from './receiveDraftTypes';

/**
 * #1497: edits and approvals send the draft's updatedAt as it was loaded, and the server refuses one
 * made over a newer change - naming this field, so the refusal can be told from other conflicts
 * ("someone is approving this", "already approved") without matching its text.
 */
export const COUNT_CHANGED_FIELD = 'expected_updated_at';

export function isCountChangedError(err: unknown): boolean {
  return CombinedGraphQLErrors.is(err) && err.errors.some((e) => e.extensions?.field === COUNT_CHANGED_FIELD);
}

/** The server's own wording for the refusal, or a fallback if it carried none. */
export function countChangedMessage(err: unknown): string {
  if (CombinedGraphQLErrors.is(err)) {
    const hit = err.errors.find((e) => e.extensions?.field === COUNT_CHANGED_FIELD);
    if (hit?.message) return hit.message;
  }
  return 'This count changed since you opened it - review the new numbers before going on.';
}

/**
 * The draft a modal shows, with a way to re-read it from the server after a count-changed refusal.
 *
 * The pages that open these modals hand over a snapshot held in their own state, which a list refetch
 * never replaces, so the modal reads the draft itself and shows that instead. The re-read copy is tied
 * to the snapshot it replaced: once the page opens a different object (another draft, or the same one
 * from a newer list), that wins.
 */
export function useReloadableDraft(draftProp: ReceiveDraft | null) {
  const client = useApolloClient();
  const [reloaded, setReloaded] = useState<{ base: ReceiveDraft; fresh: ReceiveDraft } | null>(null);
  const draft = reloaded && reloaded.base === draftProp ? reloaded.fresh : draftProp;

  // Resolves to the draft as it now stands (#1582: a refused approval reads whether its claim was kept).
  const reload = useCallback(async (): Promise<ReceiveDraft | undefined> => {
    if (!draftProp) return undefined;
    const [res] = await Promise.all([
      client.query<{ receiveDraft: ReceiveDraft }>({
        query: GET_RECEIVE_DRAFT,
        variables: { id: draftProp.id },
        fetchPolicy: 'network-only',
      }),
      client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES }),
    ]);
    const fresh = res.data?.receiveDraft;
    if (fresh) setReloaded({ base: draftProp, fresh });
    return fresh;
  }, [client, draftProp]);

  return { draft, reload };
}
