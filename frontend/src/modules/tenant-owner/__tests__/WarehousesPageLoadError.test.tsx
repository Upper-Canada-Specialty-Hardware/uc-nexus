import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import WarehousesPage from '../WarehousesPage';
import { GET_WAREHOUSES } from '../../../graphql/shared';

// #1558: a failed warehouses read showed an empty grid - "No rows", as if the company had no buildings -
// with nothing to retry.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) =>
    query === GET_WAREHOUSES
      ? { data: undefined, loading: false, error: new TypeError('Failed to fetch'), refetch: vi.fn() }
      : { data: undefined, loading: false, error: undefined, refetch: vi.fn() },
  useMutation: () => [vi.fn(), { loading: false }],
  useApolloClient: () => ({ query: vi.fn(), refetchQueries: vi.fn() }),
}));
vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, isNexusAdmin: true, hasRole: () => true, company: 'TUBC', roles: [] }),
}));

it('says the warehouses could not be loaded and offers a retry, instead of an empty grid', () => {
  render(
    <MemoryRouter>
      <WarehousesPage />
    </MemoryRouter>,
  );

  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText(/no rows/i)).not.toBeInTheDocument();
});
