import { fireEvent, render, screen } from '@testing-library/react';
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
    // #1907: two shelves the source list names - one defined in the warehouse, one not.
    shelvesSnapshot: {
      data: {
        sharepointInventorySnapshot: {
          alreadyMigrated: false,
          items: ['A-62R', 'Q-99Z', 'F-37'].map((locations, i) => ({
            spItemId: String(i + 1),
            partNumber: `PART-${i + 1}`,
            scheduledPartNumber: '',
            partCategory: 'Hinge',
            inventoryType: 'Door Hardware',
            locations,
            stockQty: 2,
            nonStockQty: 0,
            projectInventoryQty: 0,
            projectNumber: '',
            projectName: '',
            unitCost: 0,
          })),
        },
      },
      loading: false,
      error: undefined,
      refetch,
    },
    registry: {
      data: { warehouseLocations: [{ id: 'l1', warehouseId: 'w1', aisle: 'A', row: '62', bay: 'R', active: true }] },
      loading: false,
      error: undefined,
      refetch,
    },
    // #1909: one row naming a purchase order, so the wizard has a PO lookup to wait on.
    poSnapshot: {
      data: {
        sharepointInventorySnapshot: {
          alreadyMigrated: false,
          items: [
            {
              spItemId: '1',
              partNumber: 'PART-1',
              scheduledPartNumber: '',
              partCategory: 'Hinge',
              inventoryType: 'Door Hardware',
              locations: 'A-62R',
              stockQty: 2,
              nonStockQty: 0,
              projectInventoryQty: 0,
              projectNumber: '',
              projectName: '',
              unitCost: 0,
              poNumber: 'PO501788',
            },
          ],
        },
      },
      loading: false,
      error: undefined,
      refetch,
    },
    currentSnapshot: null as unknown,
    client: { query: (): Promise<unknown> => Promise.resolve({ data: {} }) },
  };
});

vi.mock('@apollo/client/react', async () => {
  const admin = await import('../../../graphql/admin');
  const shared = await import('../../../graphql/shared');
  const warehouse = await import('../../../graphql/warehouse');
  return {
    useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
      if (options?.skip) return results.idle;
      if (query === admin.GET_SHAREPOINT_INVENTORY_SNAPSHOT) return results.currentSnapshot ?? results.snapshot;
      if (query === warehouse.GET_WAREHOUSE_LOCATIONS) return results.registry;
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

it('leaves a bay-less location for the user and flags a shelf the warehouse has not defined (#1907)', () => {
  results.projects = results.projectsLoaded;
  results.currentSnapshot = results.shelvesSnapshot;
  try {
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    // F-37 has no bay, so it is not read on its own; Q-99Z is read but is no defined shelf.
    expect(screen.getByText(/2 of 3 location\s+values were read automatically/)).toBeInTheDocument();
    expect(screen.getByText(/1 location values are still unset/)).toBeInTheDocument();
    expect(screen.getAllByText('not a defined shelf')).toHaveLength(1);
    expect(screen.getByText('Q-99Z').closest('tr')).toHaveTextContent('not a defined shelf');
    expect(screen.getByText(/1 included location value names a\s+shelf/)).toBeInTheDocument();
  } finally {
    results.currentSnapshot = null;
  }
});

describe('the purchase-order lookup (#1909)', () => {
  const defaultQuery = results.client.query;
  afterEach(() => {
    results.currentSnapshot = null;
    results.client.query = defaultQuery;
  });

  /** Next up to the Reconcile GP PO link step - the seventh, index 6. */
  const toPoLinkStep = () => {
    for (let i = 0; i < 6; i += 1) fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  };

  it('says a failed lookup failed, offers it again, and holds Next on the link step', async () => {
    results.projects = results.projectsLoaded;
    results.currentSnapshot = results.poSnapshot;
    results.client.query = () => Promise.reject(new Error('Network down'));
    renderPage();

    expect(await screen.findByText(/couldn.t load the purchase orders the list names/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    toPoLinkStep();
    expect(screen.getByText('Could not read the purchase orders')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('holds Next on the link step while the lookup is still reading', () => {
    results.projects = results.projectsLoaded;
    results.currentSnapshot = results.poSnapshot;
    results.client.query = () => new Promise(() => undefined);
    renderPage();

    toPoLinkStep();
    expect(screen.getByText('Reading the purchase orders…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('lets the wizard on once the lookup has answered', async () => {
    results.projects = results.projectsLoaded;
    results.currentSnapshot = results.poSnapshot;
    results.client.query = () => Promise.resolve({ data: { mirroredPosByNumber: [] } });
    renderPage();

    toPoLinkStep();
    expect(await screen.findByText('Rows naming a PO')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });
});
