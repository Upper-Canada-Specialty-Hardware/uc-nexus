import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import { GET_INVENTORY_ROWS, GET_LOCATION_UTILIZATION, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import theme from '../../../theme';

// #1503: the product-code half of the search reads inventory rows and stock items. When that read failed,
// the box said "no locations match" - a product that is on the rack read as nowhere.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    if (query === GET_INVENTORY_ROWS) {
      return { data: undefined, loading: false, error: new Error('Network down'), refetch: vi.fn() };
    }
    const data =
      query === GET_WAREHOUSES
        ? { warehouses: [{ id: 'w-1', name: 'Main', code: 'W-1', isActive: true }] }
        : query === GET_LOCATION_UTILIZATION
          ? {
              locationUtilization: [
                { warehouseId: 'w-1', aisle: 'A', row: '1', bay: '1', itemCount: 1, totalQuantity: 4 },
              ],
            }
          : query === GET_WAREHOUSE_LOCATIONS
            ? { warehouseLocations: [] }
            : { stockItems: [] };
    return { data, loading: false, error: undefined, refetch: vi.fn() };
  },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, hasRole: () => true }),
}));

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => vi.unstubAllGlobals());

it('says the product search failed rather than "no locations match" (#1503)', () => {
  // The rack grid's selected-row edge reads the app theme's CSS variables.
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <LocationsTab />
      </MemoryRouter>
    </ThemeProvider>,
  );

  fireEvent.change(screen.getByLabelText('Search locations'), { target: { value: 'HG-100' } });

  expect(screen.getByText(/couldn.t load the product codes to search/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.queryByText(/no locations match/i)).not.toBeInTheDocument();
});
