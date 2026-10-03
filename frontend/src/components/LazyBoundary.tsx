import { Component, Suspense, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { Box, Button, Typography } from '@mui/material';
import { RotateCw, XCircle } from 'lucide-react';
import { monoSx } from '../theme';

const RELOAD_KEY = 'uc-nexus:lazy-chunk-reload-at';
const RELOAD_COOLDOWN_MS = 60_000;

// eslint-disable-next-line react-refresh/only-export-components
export function isChunkLoadError(error: unknown): boolean {
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
  /** When this changes, a boundary showing an error tries its children again (#1135). Every route
   *  renders a LazyRoute in the same tree position, so React keeps one boundary across navigation; a
   *  crash on one page must not leave the next one showing the error. */
  resetKey?: string;
}

interface LazyBoundaryState {
  error: unknown;
  /** True while a chunk-load reload is under way: the skeleton holds until the page goes. */
  reloading: boolean;
}

/** Reloads the page once (per cooldown) when a stale tab asks for a chunk the latest deploy removed.
 *  Returns false when the cooldown says a reload just happened and did not help. */
function reloadForStaleChunk(): boolean {
  let lastReloadAt = 0;
  try {
    lastReloadAt = Number(window.sessionStorage.getItem(RELOAD_KEY) ?? 0);
  } catch {
    // No session storage: reload anyway; the browser itself stops a true loop.
  }
  if (Date.now() - lastReloadAt <= RELOAD_COOLDOWN_MS) return false;
  try {
    window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    // As above.
  }
  window.location.reload();
  return true;
}

// Triggered when a stale tab tries to load a module chunk whose hashed filename no longer exists after
// a redeploy: reloads the page so the browser fetches a fresh index.html (and the current chunk hashes).
// #1135: it is also the app's only error boundary, so any other render error lands here too. That used
// to show the loading skeleton forever with nothing logged; now it says what went wrong and offers a
// reload, and only a chunk-load error reloads on its own.
export class LazyBoundary extends Component<LazyBoundaryProps, LazyBoundaryState> {
  state: LazyBoundaryState = { error: null, reloading: false };

  static getDerivedStateFromError(error: unknown): Partial<LazyBoundaryState> {
    return { error: error ?? new Error('Unknown error') };
  }

  componentDidCatch(error: unknown): void {
    if (isChunkLoadError(error)) {
      if (reloadForStaleChunk()) this.setState({ reloading: true });
      return;
    }
    console.error('A page failed to render:', error);
  }

  componentDidUpdate(prev: LazyBoundaryProps): void {
    if (this.state.error && !this.state.reloading && prev.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  render(): ReactNode {
    const { error, reloading } = this.state;
    if (!error) return this.props.children;
    if (reloading) return this.props.fallback;
    return <PageError error={error} />;
  }
}

function PageError({ error }: { error: unknown }) {
  const stale = isChunkLoadError(error);
  const message = error instanceof Error ? error.message : String(error);
  return (
    <Box role="alert" sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, p: 3, maxWidth: 720 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, color: 'error.main' }}>
        <XCircle size={20} strokeWidth={1.75} />
        <Typography variant="h6" component="h2" sx={{ color: 'text.primary' }}>
          {stale ? 'This page is out of date' : 'This page hit an error'}
        </Typography>
      </Box>
      <Typography variant="body2" color="text.secondary">
        {stale
          ? 'A new version of UC Nexus was deployed. Reload to get it.'
          : 'Reload to try again. If it keeps happening, send this message along with what you were doing.'}
      </Typography>
      {!stale && message && (
        <Typography
          variant="body2"
          sx={{ ...monoSx, p: 1.25, borderRadius: 1, bgcolor: 'action.hover', overflowWrap: 'anywhere' }}
        >
          {message}
        </Typography>
      )}
      <Box>
        <Button
          variant="contained"
          startIcon={<RotateCw size={16} strokeWidth={1.75} />}
          onClick={() => window.location.reload()}
        >
          Reload
        </Button>
      </Box>
    </Box>
  );
}

interface LazyRouteProps {
  children: ReactNode;
  fallback: ReactNode;
}

export function LazyRoute({ children, fallback }: LazyRouteProps) {
  const { pathname } = useLocation();
  return (
    <LazyBoundary fallback={fallback} resetKey={pathname}>
      <Suspense fallback={fallback}>{children}</Suspense>
    </LazyBoundary>
  );
}
