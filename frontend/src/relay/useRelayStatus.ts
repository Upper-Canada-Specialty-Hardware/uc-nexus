import { useCallback, useEffect, useRef, useState } from 'react';
import { checkRelayHealth, prefetchRelaySecret, type RelayHealth } from './relayClient';

// How often to re-probe the relay so the indicator flips when it's stopped/restarted.
const POLL_MS = 10_000;

interface UseRelayStatus {
  // null while the first check is in flight (renders as "checking…").
  health: RelayHealth | null;
  refresh: () => void;
}

// Page-level relay presence: probe /health on mount, poll on an interval, and re-check when the tab
// regains focus, so an indicator stays current without a page reload. The first successful check
// also warms the relay credential cache. Single source of truth a page can pass down to its dialogs.
export function useRelayStatus(): UseRelayStatus {
  const [health, setHealth] = useState<RelayHealth | null>(null);
  const prefetchedRef = useRef(false);
  const refreshRef = useRef<() => void>(() => {});

  useEffect(() => {
    let active = true;

    // Local async fn (React-docs effect pattern): setHealth runs after the awaited probe, not
    // synchronously in the effect body.
    const probe = async () => {
      const h = await checkRelayHealth();
      if (!active) return;
      setHealth(h);
      if (h.ok && !prefetchedRef.current) {
        prefetchedRef.current = true;
        void prefetchRelaySecret();
      }
    };
    refreshRef.current = () => void probe();

    void probe();
    const interval = setInterval(() => void probe(), POLL_MS);
    const onFocus = () => void probe();
    const onVisibility = () => {
      if (document.visibilityState === 'visible') void probe();
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      active = false;
      clearInterval(interval);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  const refresh = useCallback(() => refreshRef.current(), []);
  return { health, refresh };
}
