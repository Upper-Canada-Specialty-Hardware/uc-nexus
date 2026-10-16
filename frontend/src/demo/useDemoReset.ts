import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { ACKNOWLEDGE_DEMO_RESET, GET_DEMO_RESET_STATUS, RESET_DEMO } from '../graphql/demo';
import { userMessage } from '../graphql/userMessage';
import { useToast } from '../components/Toast';

export interface DemoResetStatus {
  building: boolean;
  buildStartedAt: string | null;
  buildStartedBy: string | null;
  notice: { resetAt: string; resetBy: string | null } | null;
}

// Asked often while a reset runs, so the tab reloads soon after it ends; otherwise once a minute, which is
// how a tab left open learns somebody else has started one.
const POLL_WHILE_BUILDING_MS = 4000;
const POLL_IDLE_MS = 60000;

/** The reload a finished reset ends in. A seam for the tests. */
export const reloadPage = {
  run: () => window.location.reload(),
};

/**
 * Resetting the demo, and hearing about resets (#1697).
 *
 * Anybody in demo mode can reset it, which rebuilds it from UBC for everybody in the background. While it
 * runs every demo read is refused, so the tab waits on this status read - which is answered throughout -
 * and reloads when the reset it saw running has finished, landing everybody in the rebuilt demo with
 * nothing of the old one left in the cache. The notice is the last reset this person has not been told
 * of; acknowledging it means it is not shown again.
 */
export function useDemoReset(demoMode: boolean) {
  const { showToast } = useToast();
  const { data, refetch, startPolling } = useQuery<{ demoResetStatus: DemoResetStatus }>(GET_DEMO_RESET_STATUS, {
    skip: !demoMode,
    fetchPolicy: 'network-only',
    pollInterval: POLL_IDLE_MS,
  });
  const status = demoMode ? (data?.demoResetStatus ?? null) : null;
  const building = !!status?.building;

  const [resetDemo, { loading: resetting }] = useMutation<{ resetDemo: DemoResetStatus }>(RESET_DEMO);
  const [acknowledge, { loading: acknowledging }] = useMutation(ACKNOWLEDGE_DEMO_RESET);

  // A reset this tab watched running has finished: start afresh in the rebuilt demo.
  const sawBuilding = useRef(false);
  useEffect(() => {
    if (!demoMode) return;
    if (building) {
      sawBuilding.current = true;
      startPolling(POLL_WHILE_BUILDING_MS);
    } else {
      startPolling(POLL_IDLE_MS);
      if (sawBuilding.current && data) {
        sawBuilding.current = false;
        reloadPage.run();
      }
    }
  }, [demoMode, building, data, startPolling]);

  const reset = useCallback(async () => {
    try {
      await resetDemo();
      await refetch();
    } catch (err) {
      showToast(userMessage(err), 'error');
    }
  }, [resetDemo, refetch, showToast]);

  const dismissNotice = useCallback(async () => {
    try {
      await acknowledge();
      await refetch();
    } catch (err) {
      showToast(userMessage(err), 'error');
    }
  }, [acknowledge, refetch, showToast]);

  return { status, building, resetting, acknowledging, reset, dismissNotice };
}
