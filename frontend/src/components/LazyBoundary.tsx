import { Component, Suspense, type ReactNode } from 'react';

const RELOAD_KEY = 'uc-nexus:lazy-chunk-reload-at';
const RELOAD_COOLDOWN_MS = 60_000;

function isChunkLoadError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  if (error.name === 'ChunkLoadError') return true;
  const message = error.message || '';
  return (
    /Loading chunk \d+ failed/.test(message) ||
    /Failed to fetch dynamically imported module/.test(message) ||
    /Importing a module script failed/.test(message) ||
    /error loading dynamically imported module/i.test(message)
  );
}

interface LazyBoundaryProps {
  children: ReactNode;
  fallback: ReactNode;
}

interface LazyBoundaryState {
  errored: boolean;
}

// Triggered when a stale tab tries to load a module chunk whose hashed
// filename no longer exists after a redeploy. Reloads the page so the
// browser fetches a fresh index.html (and the current chunk hashes).
export class LazyBoundary extends Component<LazyBoundaryProps, LazyBoundaryState> {
  state: LazyBoundaryState = { errored: false };

  static getDerivedStateFromError(): LazyBoundaryState {
    return { errored: true };
  }

  componentDidCatch(error: unknown): void {
    if (!isChunkLoadError(error)) return;
    const lastReloadAt = Number(window.sessionStorage.getItem(RELOAD_KEY) ?? 0);
    if (Date.now() - lastReloadAt > RELOAD_COOLDOWN_MS) {
      window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
      window.location.reload();
    }
  }

  render(): ReactNode {
    if (this.state.errored) return this.props.fallback;
    return this.props.children;
  }
}

interface LazyRouteProps {
  children: ReactNode;
  fallback: ReactNode;
}

export function LazyRoute({ children, fallback }: LazyRouteProps) {
  return (
    <LazyBoundary fallback={fallback}>
      <Suspense fallback={fallback}>{children}</Suspense>
    </LazyBoundary>
  );
}
