import { render, screen } from '@testing-library/react';
import { ThemeProvider } from '@mui/material';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import SharePointMigrationPage from '../SharePointMigrationPage';
import theme from '../../../theme';

// #1842: a failed projects read left every SharePoint project unset - "rows will be skipped" - and
// Migrate stayed enabled, so the run landed only the stock rows.
// Each result is one object across renders, as Apollo's are: a fresh one per render would re-run every
// effect the page keys off the snapshot, forever.
const results = vi.hoisted(() => {
  const refetch = () => Promise.resolve();
  return {
    idle: { data: undefined, loading: false, error: undefined, refetch },
    snapshot: {
      data: { sharepointInventorySnapshot: { alreadyMigrated: false, items: [] } },
      loading: false,
      error: undefined,
      refetch,
    },
    warehouses: {
      data: { warehouses: [{ id: 'w1', name: 'Main', code: 'MAIN', isPrimary: true, isActive: true }] },
      loading: false,
      error: undefined,
      refetch,
    },
    projectsFailed: { data: undefined, loading: false, error: new Error('Network down'), refetch },
    projectsLoaded: { data: { projects: [] }, loading: false, error: undefined, refetch },
    projects: null as unknown,
    client: { query: () => Promise.resolve({ data: {} }) },
  };
});

vi.mock('@apollo/client/react', async () => {
  const admin = await import('../../../graphql/admin');
  const shared = await import('../../../graphql/shared');
  return {
    useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
      if (options?.skip) return results.idle;
      if (query === admin.GET_SHAREPOINT_INVENTORY_SNAPSHOT) return results.snapshot;
      if (query === shared.GET_WAREHOUSES) return results.warehouses;
      if (query === shared.GET_PROJECTS) return results.projects;
      return results.idle;
    },
    useMutation: () => [() => Promise.resolve(), { loading: false }],
    useApolloClient: () => results.client,
  };
});

vi.mock('../../../components/Toast', () => {
  const toast = { showToast: () => undefined };
  return { useToast: () => toast };
});
vi.mock('../../../hooks/useCustomItems', () => {
  const types: never[] = [];
  return { useInventoryItemTypes: () => ({ types }) };
});

function renderPage() {
  return render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <SharePointMigrationPage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

it('says the projects read failed and holds the wizard until it loads (#1842)', () => {
  results.projects = results.projectsFailed;
  renderPage();

  expect(screen.getByText(/couldn.t load the nexus projects/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
});

it('lets the wizard go on once both reads have loaded (#1842)', () => {
  results.projects = results.projectsLoaded;
  renderPage();

  expect(screen.queryByText(/couldn.t load the nexus projects/i)).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
});
