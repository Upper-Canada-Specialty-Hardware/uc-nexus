import { useEffect, useRef } from 'react';
import { useApolloClient } from '@apollo/client/react';
import { useGpOutbox } from './useGpOutbox';
import { GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS } from '../graphql/refetch';

// Mounted once, in AppLayout (#353 PR E).
//
// A queued GP write drains in the background - minutes or hours after the user submitted it, while
// the browser is sitting on whatever route it happens to be on. `lastDrainedAt` advancing is the
// only signal the browser gets that data changed underneath it; without this, a receive that posted
// itself while the user was on the warehouse page would stay invisible until a manual refresh.
//
// Eviction only. Evicting a root field makes every mounted watcher with an incomplete cache diff
// repair itself, which reaches the unmounted case that refetchQueries cannot - and pairing an evict
// with a refetch by name is the concurrent double-run that graphql/refetch.ts exists to prevent.
export default function GpOutboxWatcher() {
  const client = useApolloClient();
  const { lastDrainedAt } = useGpOutbox();
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (!lastDrainedAt) return;
    // First observation is the baseline, not a drain: on a fresh page load lastDrainedAt is whatever
    // the last drain ever was, and evicting on it would fire a wave of refetches on every mount.
    if (seen.current === null) {
      seen.current = lastDrainedAt;
      return;
    }
    if (seen.current === lastDrainedAt) return;
    seen.current = lastDrainedAt;
    for (const fieldName of GP_OUTBOX_DRAINED_STALE_ROOT_FIELDS) {
      client.cache.evict({ id: 'ROOT_QUERY', fieldName });
    }
    client.cache.gc();
  }, [lastDrainedAt, client]);

  return null;
}
