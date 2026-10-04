/**
 * The bridge between Clerk's `useAuth()` hook and the module-scope Apollo client (#429).
 *
 * `apollo.ts` builds one client when the module is first imported, long before React renders, so the
 * auth link cannot call a hook. Reading `window.Clerk.session.getToken()` instead - which is what it
 * used to do - works only while Clerk happens to have a live session object on the global, and
 * returns null the moment it does not: on a tab waking from sleep, during a token refresh, or after
 * the session expires with the tab still open. The link then sent a request with no Authorization
 * header at all, and since #415 gated every resolver, the backend answered `Authentication required`
 * to every query on the page and the user got a blank screen whose only cure was a manual reload.
 *
 * So the token getter goes the other way: `AuthRecoveryProvider` publishes Clerk's own `getToken`
 * here on mount, and the link reads it at request time. That keeps the link inside Clerk's refresh
 * machinery (`getToken({ skipCache: true })` re-mints rather than handing back a dead cached token)
 * without turning the client into a React value or rebuilding it per render, which would throw away
 * the cache on every auth state change.
 *
 * The failure listener runs the same way in reverse: the link cannot render a dialog, so it announces
 * an unrecoverable auth failure here and the provider - which can - subscribes.
 */

/** Clerk's `getToken`, narrowed to the shape the Apollo auth link depends on. */
export type TokenGetter = (options?: { skipCache?: boolean }) => Promise<string | null>;

export interface AuthBridgeState {
  /** Clerk has finished booting, so `isSignedIn` is trustworthy. False during the first paint. */
  isLoaded: boolean;
  isSignedIn: boolean;
  /** Null until the provider mounts. */
  getToken: TokenGetter | null;
}

const EMPTY: AuthBridgeState = { isLoaded: false, isSignedIn: false, getToken: null };

let state: AuthBridgeState = EMPTY;

export function publishAuthBridge(next: AuthBridgeState): void {
  state = next;
}

export function readAuthBridge(): Readonly<AuthBridgeState> {
  return state;
}

/** Back to the pre-mount state. Only the provider's teardown and tests should need this. */
export function resetAuthBridge(): void {
  state = EMPTY;
  authFailed = false;
  lastProbeAt = 0;
}

/**
 * True when Clerk says there is a live session, so a request without an Authorization header is a
 * bug rather than an anonymous caller. Deliberately false while Clerk is still loading and while the
 * user is signed out: those are the legitimate no-token windows, and treating them as failures would
 * stop the sign-in page itself from making a request.
 */
export function isSessionExpected(): boolean {
  return state.isLoaded && state.isSignedIn;
}

type AuthFailureListener = () => void;

const listeners = new Set<AuthFailureListener>();

/** Subscribe to "the token could not be repaired". Returns the unsubscribe. */
export function onAuthFailure(listener: AuthFailureListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/**
 * The lapsed-session state (#1329). Before it, a session that could not be repaired was announced
 * once per failing request, and the page's polls (relay status every 10s, the outbox every 15s, the
 * bell every 30s) each failed, replayed and announced again: "Not now" on the prompt held for about
 * ten seconds, and every poll kept costing two backend calls and a fresh token mint for as long as
 * the tab stayed open.
 *
 * Now the first unrecoverable failure marks the session lapsed. While it is, the auth link stops
 * background queries before they mint or reach the network (one probe a minute still goes through,
 * so a session Clerk repairs on its own is noticed), further failures stay quiet, and the first
 * request that succeeds clears it. A mutation is the user acting, so it is always attempted and its
 * failure raises the prompt again even while lapsed.
 */
let authFailed = false;
let lastProbeAt = 0;

/** How often a lapsed session still lets one background query through to see if it recovered. */
export const AUTH_PROBE_INTERVAL_MS = 60_000;

/** True once a failure could not be repaired, until a request succeeds again. */
export function isAuthLapsed(): boolean {
  return authFailed;
}

/**
 * Whether a background query should be stopped before it mints or reaches the network. False while
 * the session is healthy, and false once a minute while it is lapsed: that request is the probe.
 */
export function shouldSuspendQuery(now: number = Date.now()): boolean {
  if (!authFailed) return false;
  if (now - lastProbeAt >= AUTH_PROBE_INTERVAL_MS) {
    lastProbeAt = now;
    return false;
  }
  return true;
}

type AuthRecoveredListener = () => void;

const recoveredListeners = new Set<AuthRecoveredListener>();

/**
 * Subscribe to "a lapsed session is back" (#1400). Fires once per recovery - only on the change from
 * lapsed to healthy - however the lapse ended: a probe that got through, a new Clerk session, or the
 * prompt's in-place renewal. Returns the unsubscribe.
 */
export function onAuthRecovered(listener: AuthRecoveredListener): () => void {
  recoveredListeners.add(listener);
  return () => {
    recoveredListeners.delete(listener);
  };
}

/** A request got through: the session is back, so background queries resume. */
export function markAuthRecovered(): void {
  const wasLapsed = authFailed;
  authFailed = false;
  lastProbeAt = 0;
  if (wasLapsed) recoveredListeners.forEach((listener) => listener());
}

/**
 * Announce that the token could not be repaired. Only the first failure of a lapse reaches the
 * listeners; the rest are the same news. `userAction` is a failure the user caused (a mutation),
 * which re-raises the prompt even mid-lapse, because they are waiting on the answer.
 */
export function notifyAuthFailure(options: { userAction?: boolean } = {}): void {
  const alreadyLapsed = authFailed;
  if (!alreadyLapsed) {
    authFailed = true;
    lastProbeAt = Date.now();
  }
  if (alreadyLapsed && !options.userAction) return;
  listeners.forEach((listener) => listener());
}
