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

export function notifyAuthFailure(): void {
  listeners.forEach((listener) => listener());
}
