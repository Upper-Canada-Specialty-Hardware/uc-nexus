import { useCallback, useState } from 'react';
import { useMutation } from '@apollo/client/react';
import { useActingCompany } from '../company/ActingCompanyContext';
import { SET_MY_DEMO_MODE } from '../graphql/demo';
import { userMessage } from '../graphql/userMessage';
import { useIdentity } from '../hooks/useIdentity';
import { mayUseDemoMode } from './demoMode';
import { announceDemoModeChange } from './demoSync';
import { useToast } from '../components/Toast';

/** What the account is in the middle of, for the progress dialog (#1653). */
export type DemoRun = 'enter' | 'leave';

/**
 * Getting into and out of demo mode (#1608).
 *
 * The flag lives on the account, so after it is written the Clerk user is reloaded: that is what moves
 * the acting company to or from the demo one, and the acting company's own switch empties the cache, so
 * no row from the other side is left on screen.
 *
 * The demo is one persistent copy of UBC everybody in it shares (#1657); resetting it is useDemoReset's
 * (#1697), not a side effect of switching on. The first switch-on ever builds it inside the mutation,
 * which takes minutes, so the hook says which run is in flight and the callers show it (#1653).
 */
export function useDemoMode() {
  const { user, demoMode } = useIdentity();
  const { company } = useActingCompany();
  const { showToast } = useToast();
  const [running, setRunning] = useState<DemoRun | null>(null);
  const busy = running !== null;
  const [setMyDemoMode] = useMutation(SET_MY_DEMO_MODE);

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
            ? 'Demo mode is on: a shared copy of UBC, with GP simulated. Nothing you do reaches UBC or GP.'
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

  return {
    demoMode,
    /** Only an account working in a UBC company turns it on (#1658); anybody in it can leave. */
    canEnter: mayUseDemoMode(company),
    busy,
    running,
    enter: () => switchTo(true),
    leave: () => switchTo(false),
  };
}
