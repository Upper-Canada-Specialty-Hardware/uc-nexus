import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import { GET_LOCATION_CONTENTS, GET_LOCATION_UTILIZATION, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import theme from '../../../theme';

// #1879: a failed contents read showed "No items at this location." under its own error, as if the bin
// were empty.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    if (query === GET_LOCATION_CONTENTS) {
      return { data: undefined, loading: false, error: new Error('Network down'), refetch: vi.fn() };
    }
    const data =
      query === GET_WAREHOUSES
        ? { warehouses: [{ id: 'w-1', name: 'Main', code: 'W-1', isActive: true }] }
        : query === GET_WAREHOUSE_LOCATIONS
          ? { warehouseLocations: [] }
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

it('says the contents read failed and does not call the bin empty', () => {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <LocationsTab />
      </MemoryRouter>
    </ThemeProvider>,
  );

  fireEvent.click(screen.getByText('A-1-1'));

  expect(screen.getByRole('button', { name: 'Close location contents' })).toBeInTheDocument();
  expect(screen.getByText(/network down|connection/i)).toBeInTheDocument();
  expect(screen.queryByText('No items at this location.')).not.toBeInTheDocument();
});
