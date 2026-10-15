import { useCallback, useState } from 'react';
import { useApolloClient, useMutation } from '@apollo/client/react';
import { RESET_DEMO_DATA, SET_MY_DEMO_MODE } from '../graphql/demo';
import { userMessage } from '../graphql/userMessage';
import { useIdentity } from '../hooks/useIdentity';
import { announceDemoModeChange } from './demoSync';
import { useToast } from '../components/Toast';

/** What the account is in the middle of, for the progress dialog (#1653). */
export type DemoRun = 'enter' | 'leave' | 'reset';

/**
 * Getting into, out of and back to the start of demo mode (#1608).
 *
 * The flag lives on the account, so after it is written the Clerk user is reloaded: that is what moves
 * the acting company to or from the demo one, and the acting company's own switch empties the cache, so
 * no row from the other side is left on screen. A reset changes rows under the same company, so it
 * empties the cache itself.
 *
 * A reset, and the first switch-on, reseed the demo company inside one mutation - with a legacy
 * inventory export loaded that is the better part of a minute - so the hook says which run is in
 * flight and the callers show it (#1653).
 */
export function useDemoMode() {
  const { user, demoMode, ownsTenant } = useIdentity();
  const client = useApolloClient();
  const { showToast } = useToast();
  const [running, setRunning] = useState<DemoRun | null>(null);
  const busy = running !== null;
  const [setMyDemoMode] = useMutation(SET_MY_DEMO_MODE);
  const [resetDemoData] = useMutation(RESET_DEMO_DATA);

  const switchTo = useCallback(
    async (enabled: boolean) => {
      if (busy) return;
      setRunning(enabled ? 'enter' : 'leave');
      try {
        await setMyDemoMode({ variables: { enabled } });
        await user?.reload();
        // #1633: every other open tab reloads too, rather than stay on the side this one just left.
        announceDemoModeChange();
        showToast(
          enabled
            ? 'Demo mode is on. Everything you see is made up, and GP is simulated.'
            : 'Demo mode is off. You are back in your own company.',
          'success',
        );
      } catch (err) {
        showToast(userMessage(err), 'error');
      } finally {
        setRunning(null);
      }
    },
    [busy, setMyDemoMode, user, showToast],
  );

  const reset = useCallback(async () => {
    if (busy) return;
    setRunning('reset');
    try {
      await resetDemoData();
      await client.resetStore().catch(() => {
        // A query the reset cancelled rejects here; the refetch that follows is what counts.
      });
      showToast('The demo data is back at its starting state.', 'success');
    } catch (err) {
      showToast(userMessage(err), 'error');
    } finally {
      setRunning(null);
    }
  }, [busy, resetDemoData, client, showToast]);

  return {
    demoMode,
    /** A Tenant Owner or UC Nexus Admin resets the demo data. Turning demo mode on and off is anybody's (#1629). */
    canReset: ownsTenant && demoMode,
    busy,
    running,
    enter: () => switchTo(true),
    leave: () => switchTo(false),
    reset,
  };
}
