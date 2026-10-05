import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import ProjectsPage from '../ProjectsPage';
import { GET_ADMIN_PROJECTS } from '../../../graphql/admin';

// #1543: a failed projects read showed an empty grid - "No rows", as if the company had no projects - with
// nothing to retry.
const refetch = vi.fn();
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) =>
    query === GET_ADMIN_PROJECTS
      ? { data: undefined, loading: false, error: new Error('Network down'), refetch }
      : { data: undefined, loading: false, error: undefined, refetch: vi.fn() },
  useMutation: () => [vi.fn(), { loading: false }],
  useApolloClient: () => ({ query: vi.fn(), refetchQueries: vi.fn() }),
}));
vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, isAdmin: false, hasRole: () => true, company: 'TUBC' }),
}));

it('says the projects could not be loaded and offers a retry, instead of an empty list', () => {
  render(
    <MemoryRouter>
      <ProjectsPage />
    </MemoryRouter>,
  );

  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText(/no rows/i)).not.toBeInTheDocument();
});
