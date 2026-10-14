import { useEffect, useRef } from 'react';

/**
 * Keeping every open tab on the right side of demo mode (#1633).
 *
 * Demo mode is a flag on the account, and a tab only learns it when it reloads the Clerk user. Without
 * this, a tab left open while demo mode was turned on or off in another one kept asking for the company
 * it last knew - the demo banner over a real company's rows, or a real company's screens over the demo
 * one. Two signals make a tab reload the user, and the acting company's own switch then empties the
 * cache and refetches what is on screen:
 *
 *   - the tab that turns demo mode on or off says so to every other tab, through a storage key;
 *   - the backend refuses a request whose company is on the wrong side of the account's flag with its
 *     own code, which catches a tab the first signal missed (a window on another device, a closed one).
 */

/** The backend's code for a request on the wrong side of demo mode (backend app/errors.py). */
export const DEMO_MODE_CHANGED = 'DEMO_MODE_CHANGED';

/** The storage key one tab writes and every other tab of the same browser hears. */
export const DEMO_MODE_CHANGED_STORAGE_KEY = 'uc-nexus-demo-mode-changed';

const REFRESH_EVENT = 'uc-nexus:refresh-identity';

/** Tell every other open tab that this account's demo mode just changed. */
export function announceDemoModeChange(): void {
  try {
    localStorage.setItem(DEMO_MODE_CHANGED_STORAGE_KEY, String(Date.now()));
  } catch {
    // Storage blocked: the other tabs catch up on the backend's refusal instead.
  }
}

/** Ask this tab to reload its user, from outside React (the Apollo link). */
export function requestIdentityRefresh(): void {
  window.dispatchEvent(new Event(REFRESH_EVENT));
}

interface ReloadableUser {
  reload: () => Promise<unknown>;
}

/** Reload the user on either signal, one reload at a time. */
export function useDemoModeSync(user: ReloadableUser | null | undefined): void {
  const reloading = useRef(false);

  useEffect(() => {
    if (!user) return;
    const reload = () => {
      if (reloading.current) return;
      reloading.current = true;
      void user
        .reload()
        .catch(() => {
          // A failed reload leaves the tab where it was; the next refusal asks again.
        })
        .finally(() => {
          reloading.current = false;
        });
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === DEMO_MODE_CHANGED_STORAGE_KEY) reload();
    };
    window.addEventListener('storage', onStorage);
    window.addEventListener(REFRESH_EVENT, reload);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener(REFRESH_EVENT, reload);
    };
  }, [user]);
}
