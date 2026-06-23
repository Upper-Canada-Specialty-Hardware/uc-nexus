import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client/core';
import { ErrorLink } from '@apollo/client/link/error';
import { SetContextLink } from '@apollo/client/link/context';
import { CombinedGraphQLErrors } from '@apollo/client/errors';

interface ClerkGlobal {
  session?: { getToken: () => Promise<string | null> };
}

const httpLink = new HttpLink({
  uri: import.meta.env.VITE_GRAPHQL_URL || '/graphql',
});

// Attach the Clerk session token so the backend can verify the caller (used by
// admin-gated resolvers). Clerk exposes the active session on window.Clerk once loaded;
// before it loads, or for signed-out users, we simply send no Authorization header.
const authLink = new SetContextLink(async (prevContext) => {
  const clerk = (window as unknown as { Clerk?: ClerkGlobal }).Clerk;
  let token: string | null = null;
  try {
    token = (await clerk?.session?.getToken()) ?? null;
  } catch {
    token = null;
  }
  const prevHeaders = (prevContext.headers ?? {}) as Record<string, string>;
  return {
    headers: {
      ...prevHeaders,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  };
});

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
  link: from([authLink, errorLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});

export default client;
