import { useEffect, useRef } from 'react';
import { useApolloClient } from '@apollo/client/react';
import { useGpOutbox } from './useGpOutbox';
import { GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS } from '../graphql/refetch';

// Mounted once, in AppLayout (#353 PR E).
//
// A queued GP write drains in the background - minutes or hours after the user submitted it, while
// the browser is sitting on whatever route it happens to be on. `lastSettledAt` advancing is the
// only signal the browser gets that data changed underneath it; without this, a receive that posted
// itself while the user was on the warehouse page would stay invisible until a manual refresh. It
// moves when a write fails or is cancelled too (#1410): a failed receipt hands its draft back for
// review, and a page still showing it approved and syncing is as stale as one missing a drain.
//
// Eviction only. Evicting a root field makes every mounted watcher with an incomplete cache diff
// repair itself, which reaches the unmounted case that refetchQueries cannot - and pairing an evict
// with a refetch by name is the concurrent double-run that graphql/refetch.ts exists to prevent.
export default function GpOutboxWatcher() {
  const client = useApolloClient();
  const { lastSettledAt, loaded } = useGpOutbox();
  // Whether the first response has been seen, kept apart from its value (#1410): a company whose
  // queue has never settled anything answers null, and that null is the baseline - its first settle
  // must evict. The placeholder before any response is not an observation, so `loaded` gates it.
  const observed = useRef(false);
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (!loaded) return;
    // First observation is the baseline, not a settle: on a fresh page load lastSettledAt is whatever
    // the last settle ever was, and evicting on it would fire a wave of refetches on every mount.
    if (!observed.current) {
      observed.current = true;
      seen.current = lastSettledAt;
      return;
    }
    if (seen.current === lastSettledAt) return;
    seen.current = lastSettledAt;
    for (const fieldName of GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS) {
      client.cache.evict({ id: 'ROOT_QUERY', fieldName });
    }
    client.cache.gc();
  }, [loaded, lastSettledAt, client]);

  return null;
}
