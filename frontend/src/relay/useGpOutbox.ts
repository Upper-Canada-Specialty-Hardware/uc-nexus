import { useQuery } from '@apollo/client/react';
import { GET_GP_OUTBOX_SUMMARY } from '../graphql/shared';

export interface GpOutboxSummary {
  pending: number;
  inFlight: number;
  failed: number;
  oldestPendingAt: string | null;
  // Advances every time the worker drains something. The browser's only signal that a background
  // drain changed data underneath whatever route it happens to be on.
  lastDrainedAt: string | null;
  // Advances every time a queued write reaches an end state - succeeded, failed or cancelled (#1410).
  // A failed receipt hands its draft back for review, which changes data an open page shows too.
  lastSettledAt: string | null;
}

export interface GpOutboxState extends GpOutboxSummary {
  // False until the first response arrives, so a reader can tell the placeholder nulls below from a
  // company whose queue has genuinely never settled anything.
  loaded: boolean;
}

const EMPTY: GpOutboxState = {
  pending: 0,
  inFlight: 0,
  failed: 0,
  oldestPendingAt: null,
  lastDrainedAt: null,
  lastSettledAt: null,
  loaded: false,
};

// Single definition of the GP write-queue poll (#353 PR E), mirroring useRelayStatus. 15s rather
// than the relay chip's 10s: a queued write is not a live status, it is a background job, and this
// is polled by every open browser - the resolver is scalar aggregates only for the same reason.
export function useGpOutbox(options?: { skip?: boolean }): GpOutboxState {
  const { data } = useQuery<{ gpOutboxSummary: GpOutboxSummary }>(GET_GP_OUTBOX_SUMMARY, {
    pollInterval: 15_000,
    fetchPolicy: 'cache-and-network',
    skip: options?.skip,
  });
  return data?.gpOutboxSummary ? { ...data.gpOutboxSummary, loaded: true } : EMPTY;
}
