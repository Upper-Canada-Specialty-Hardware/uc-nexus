import { ApolloClient, InMemoryCache, HttpLink, from } from '@apollo/client/core';
import { ErrorLink } from '@apollo/client/link/error';
import { CombinedGraphQLErrors } from '@apollo/client/errors';

const httpLink = new HttpLink({
  uri: import.meta.env.VITE_GRAPHQL_URL || '/graphql',
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
  link: from([errorLink, httpLink]),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
  },
});

export default client;
