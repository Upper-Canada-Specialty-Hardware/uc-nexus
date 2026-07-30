import { ApolloClient, ApolloLink, InMemoryCache, HttpLink, Observable, from } from '@apollo/client/core';
import { ErrorLink } from '@apollo/client/link/error';
import { CombinedGraphQLErrors } from '@apollo/client/errors';
import { isSessionExpected, notifyAuthFailure, readAuthBridge } from './authBridge';

const httpLink = new HttpLink({
  uri: import.meta.env.VITE_GRAPHQL_URL || '/graphql',
});

/** The backend's code for a rejected or absent session token (backend app/auth.py AuthError). */
const UNAUTHENTICATED = 'UNAUTHENTICATED';

/**
 * Raised by the auth link when Clerk reports a live session but hands back no token, so the request
 * is stopped here instead of going out with no Authorization header. Since #415 gated every resolver,
 * a headerless request is a guaranteed `Authentication required` - a round trip whose only outcome is
 * an error, and one that reads in the backend logs as an anonymous caller rather than as the token
 * gap it is. Carrying the same meaning as the server's UNAUTHENTICATED lets it take the same recovery
 * path: re-mint past Clerk's cache and replay.
 */
class MissingAuthTokenError extends Error {
  constructor() {
    super('Could not obtain a session token for this request');
    this.name = 'MissingAuthTokenError';
  }
}

/** Context keys this file writes onto an in-flight operation while recovering from a token gap. */
interface AuthRetryContext {
  /** Set by the retry link so the replay's mint skips Clerk's cache. */
  authTokenRefresh?: boolean;
  /** Set once an operation has been replayed. The loop guard: a replay is never itself replayed. */
  authRetryAttempted?: boolean;
}

function isUnauthenticated(error: unknown): boolean {
  if (error instanceof MissingAuthTokenError) return true;
  if (CombinedGraphQLErrors.is(error)) {
    return error.errors.some((e) => e.extensions?.code === UNAUTHENTICATED);
  }
  return false;
}

/**
 * Mint the Clerk session token and hang it off the request as `Authorization: Bearer ...`.
 *
 * Written as a plain link rather than the `SetContextLink` it replaces because it has to be able to
 * *refuse*: a context setter can only ever add headers, and the point of the missing-token case is
 * not forwarding at all.
 */
const authLink = new ApolloLink((operation, forward) => {
  const { authTokenRefresh } = operation.getContext() as AuthRetryContext;
  return new Observable<ApolloLink.Result>((observer) => {
    let inner: { unsubscribe: () => void } | undefined;
    let cancelled = false;
    void (async () => {
      const { getToken } = readAuthBridge();
      let token: string | null = null;
      try {
        token = (await getToken?.({ skipCache: authTokenRefresh === true })) ?? null;
      } catch {
        // A throwing getToken is the same situation as a null one: Clerk could not produce a token.
        token = null;
      }
      if (cancelled) return;
      if (!token && isSessionExpected()) {
        observer.error(new MissingAuthTokenError());
        return;
      }
      operation.setContext((prev) => {
        const headers = { ...((prev.headers ?? {}) as Record<string, string>) };
        // Drop before re-adding: on a replay `prev` still carries the header that was just rejected,
        // and if this pass has no token to offer, sending the stale one again is worse than sending
        // none.
        delete headers.Authorization;
        if (token) headers.Authorization = `Bearer ${token}`;
        return { ...prev, headers };
      });
      inner = forward(operation).subscribe(observer);
    })();
    return () => {
      cancelled = true;
      inner?.unsubscribe();
    };
  });
});

/**
 * Re-mint and replay ONCE on an UNAUTHENTICATED rejection (#429).
 *
 * Sits upstream of `authLink`, so `forward(operation)` re-enters it and the replay is built with a
 * freshly minted token rather than the one that was just refused. `authTokenRefresh` is what makes
 * that mint bypass Clerk's cache - without it the replay would present the same dead token and fail
 * identically.
 *
 * Two things stop it looping. `authRetryAttempted` on the operation context survives the replay,
 * because `ErrorLink` hands the same operation object to `forward`. And `ErrorLink` subscribes the
 * replay's observable straight to the outer observer, so a replay that fails again never re-enters
 * this handler - it surfaces past it, which is what `authFailureLink` is watching for.
 */
const authRetryLink = new ErrorLink(({ error, operation, forward }) => {
  if (!isUnauthenticated(error)) return;
  if ((operation.getContext() as AuthRetryContext).authRetryAttempted) return;
  operation.setContext((prev) => ({ ...prev, authRetryAttempted: true, authTokenRefresh: true }));
  return forward(operation);
});

/**
 * The end of the line: an UNAUTHENTICATED error that got past the replay means the token could not be
 * repaired, so tell the user rather than leave them on a page whose every query errored with no way
 * back but a reload they have to think of themselves. `authRetryAttempted` is the proof a replay
 * happened, so a first failure can never reach here and raise the prompt prematurely.
 */
const authFailureLink = new ErrorLink(({ error, operation }) => {
  if (!isUnauthenticated(error)) return;
  if (!(operation.getContext() as AuthRetryContext).authRetryAttempted) return;
  notifyAuthFailure();
});

/**
 * The auth half of the chain, in order. Exported whole so the tests exercise the real composition
 * rather than a re-declared copy of it that can drift from it.
 */
export const authLinks: ApolloLink[] = [authFailureLink, authRetryLink, authLink];

const errorLink = new ErrorLink(({ error }) => {
  if (CombinedGraphQLErrors.is(error)) {
    error.errors.forEach((err) => {
      console.error(`[GraphQL error]: ${err.message}`, err.extensions);
    });
  } else {
    console.error(`[Network error]: ${error}`);
  }
});

const client = new ApolloClient({
  // errorLink is outermost so it only logs what actually reached the caller: a token gap the replay
  // repaired is not an error anyone needs in the console.
  link: from([errorLink, ...authLinks, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});

export default client;
