import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApolloClient, ApolloLink, InMemoryCache, Observable, gql } from '@apollo/client/core';
import { authLinks } from '../apollo';
import { publishAuthBridge, onAuthFailure, resetAuthBridge } from '../authBridge';

/**
 * The auth link used to drop the Authorization header whenever Clerk could not produce a token, and
 * nothing downstream noticed (#429). Since #415 gated every resolver, that silent gap answers
 * `Authentication required` to every query on the page at once, so the user sees a blank screen and
 * the only cure is a reload they have to think of themselves.
 *
 * These drive the real link composition (`authLinks`, exported whole so the order under test is the
 * order that ships) against a terminating link standing in for the backend.
 */

const PING = gql`
  query Ping {
    ping
  }
`;

// ErrorLink reads `operation.client` to classify a result, so execution needs a real client. Its own
// link is never reached - `run` supplies the terminating link.
const client = new ApolloClient({ cache: new InMemoryCache(), link: ApolloLink.empty() });

const UNAUTHENTICATED_RESULT: ApolloLink.Result = {
  data: null,
  errors: [{ message: 'Authentication required', extensions: { code: 'UNAUTHENTICATED' } }],
};

const OK_RESULT: ApolloLink.Result = { data: { ping: 'pong' } };

/** A stand-in backend that records the Authorization header of every attempt it is handed. */
function backend(reply: (authorization: string | undefined, attempt: number) => ApolloLink.Result) {
  const attempts: (string | undefined)[] = [];
  const link = new ApolloLink(
    (operation) =>
      new Observable<ApolloLink.Result>((observer) => {
        const headers = (operation.getContext().headers ?? {}) as Record<string, string>;
        attempts.push(headers.Authorization);
        observer.next(reply(headers.Authorization, attempts.length));
        observer.complete();
      }),
  );
  return { link, attempts };
}

function run(terminating: ApolloLink) {
  return new Promise<ApolloLink.Result>((resolve, reject) => {
    ApolloLink.execute(
      ApolloLink.from([...authLinks, terminating]),
      { query: PING },
      { client },
    ).subscribe({ next: resolve, error: reject });
  });
}

let authFailures: number;
let unsubscribe: () => void;

beforeEach(() => {
  authFailures = 0;
  unsubscribe = onAuthFailure(() => {
    authFailures += 1;
  });
});

afterEach(() => {
  unsubscribe();
  resetAuthBridge();
});

describe('auth link', () => {
  it('sends the minted token and asks Clerk for a cached one', async () => {
    const getToken = vi.fn(async () => 'good');
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend(() => OK_RESULT);

    const result = await run(link);

    expect(result.data).toEqual({ ping: 'pong' });
    expect(attempts).toEqual(['Bearer good']);
    expect(getToken).toHaveBeenCalledTimes(1);
    expect(getToken).toHaveBeenCalledWith({ skipCache: false });
    expect(authFailures).toBe(0);
  });

  it('sends no header while Clerk is still loading, so the boot window is not a failure', async () => {
    publishAuthBridge({ isLoaded: false, isSignedIn: false, getToken: null });
    const { link, attempts } = backend(() => OK_RESULT);

    await run(link);

    expect(attempts).toEqual([undefined]);
    expect(authFailures).toBe(0);
  });

  it('sends no header for a signed-out caller rather than refusing the request', async () => {
    // The deadlock guard on failing loudly: the sign-in page itself has no session, so a missing
    // token there has to stay a plain anonymous request.
    publishAuthBridge({ isLoaded: true, isSignedIn: false, getToken: vi.fn(async () => null) });
    const { link, attempts } = backend(() => OK_RESULT);

    const result = await run(link);

    expect(result.data).toEqual({ ping: 'pong' });
    expect(attempts).toEqual([undefined]);
    expect(authFailures).toBe(0);
  });
});

describe('auth retry link', () => {
  it('re-mints past Clerk cache and replays once when the token is rejected', async () => {
    const getToken = vi.fn(async (options?: { skipCache?: boolean }) =>
      options?.skipCache ? 'fresh' : 'stale',
    );
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend((authorization) =>
      authorization === 'Bearer fresh' ? OK_RESULT : UNAUTHENTICATED_RESULT,
    );

    const result = await run(link);

    expect(result.data).toEqual({ ping: 'pong' });
    expect(attempts).toEqual(['Bearer stale', 'Bearer fresh']);
    expect(getToken).toHaveBeenNthCalledWith(2, { skipCache: true });
    expect(authFailures).toBe(0);
  });

  it('replays a throwing getToken, which is the same gap as a null one', async () => {
    const getToken = vi.fn(async (options?: { skipCache?: boolean }) => {
      if (!options?.skipCache) throw new Error('network blip refreshing the session');
      return 'fresh';
    });
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend(() => OK_RESULT);

    const result = await run(link);

    // The throw is caught, but with a live session a headerless request never leaves the client, so
    // the first thing the backend sees is the replay carrying the re-minted token.
    expect(result.data).toEqual({ ping: 'pong' });
    expect(attempts).toEqual(['Bearer fresh']);
    expect(authFailures).toBe(0);
  });

  it('stops after one replay instead of looping', async () => {
    const getToken = vi.fn(async () => 'stale');
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend(() => UNAUTHENTICATED_RESULT);

    const result = await run(link);

    expect(result.errors).toHaveLength(1);
    expect(attempts).toEqual(['Bearer stale', 'Bearer stale']);
    expect(getToken).toHaveBeenCalledTimes(2);
    expect(authFailures).toBe(1);
  });

  it('leaves errors that are not UNAUTHENTICATED alone', async () => {
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken: vi.fn(async () => 'good') });
    const { link, attempts } = backend(() => ({
      data: null,
      errors: [{ message: 'Opening not found', extensions: { code: 'NOT_FOUND' } }],
    }));

    const result = await run(link);

    expect(result.errors?.[0].message).toBe('Opening not found');
    expect(attempts).toHaveLength(1);
    expect(authFailures).toBe(0);
  });
});

describe('missing token with a live session', () => {
  it('never reaches the network and prompts once the re-mint fails too', async () => {
    const getToken = vi.fn(async () => null);
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend(() => OK_RESULT);

    await expect(run(link)).rejects.toThrow(/session token/);

    expect(attempts).toEqual([]);
    expect(getToken).toHaveBeenCalledTimes(2);
    expect(getToken).toHaveBeenNthCalledWith(2, { skipCache: true });
    expect(authFailures).toBe(1);
  });

  it('recovers silently when the re-mint succeeds', async () => {
    const getToken = vi.fn(async (options?: { skipCache?: boolean }) =>
      options?.skipCache ? 'fresh' : null,
    );
    publishAuthBridge({ isLoaded: true, isSignedIn: true, getToken });
    const { link, attempts } = backend(() => OK_RESULT);

    const result = await run(link);

    expect(result.data).toEqual({ ping: 'pong' });
    expect(attempts).toEqual(['Bearer fresh']);
    expect(authFailures).toBe(0);
  });
});
