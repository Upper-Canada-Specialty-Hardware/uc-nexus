import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import { GET_LOCATION_UTILIZATION, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import theme from '../../../theme';

// #1845: a failed registry read left every occupied bin chipped "Not defined" with a Define button, as if
// the registry were empty.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    if (query === GET_WAREHOUSE_LOCATIONS) {
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
          : {};
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

it('says the registry read failed and calls no bin not defined meanwhile', () => {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <LocationsTab />
      </MemoryRouter>
    </ThemeProvider>,
  );

  expect(screen.getByText(/couldn.t load the defined locations/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  expect(screen.getByText('A-1-1')).toBeInTheDocument();
  expect(screen.queryByText('Not defined')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Define' })).not.toBeInTheDocument();
});
