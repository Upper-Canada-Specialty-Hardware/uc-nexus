import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import { GET_LOCATION_UTILIZATION, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import theme from '../../../theme';

// #1587: Define on an occupied variant of a defined location was refused as "already defined"; Define on a
// row with no row or bay silently did nothing. The first wants a merge, the second says why it can't.
vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean }) => {
    if (options?.skip) return { data: undefined, loading: false, error: undefined, refetch: vi.fn() };
    const data =
      query === GET_WAREHOUSES
        ? { warehouses: [{ id: 'w-1', name: 'Main', code: 'W-1', isActive: true }] }
        : query === GET_LOCATION_UTILIZATION
          ? {
              locationUtilization: [
                { warehouseId: 'w-1', aisle: 'a', row: '1', bay: '1', itemCount: 1, totalQuantity: 4 },
                { warehouseId: 'w-1', aisle: 'C', row: null, bay: null, itemCount: 1, totalQuantity: 2 },
              ],
            }
          : query === GET_WAREHOUSE_LOCATIONS
            ? { warehouseLocations: [{ id: 'd-1', warehouseId: 'w-1', aisle: 'A', row: '1', bay: '1', active: true }] }
            : {};
    return { data, loading: false, error: undefined, refetch: vi.fn() };
  },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
// A Warehouse Manager manages locations but cannot open Location Cleanup (a Tenant Owner's page).
let ownsTenant = true;
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant, hasRole: () => true }),
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

it('points a variant of a defined location to cleanup, and says why a partial one cannot be defined', () => {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <LocationsTab />
      </MemoryRouter>
    </ThemeProvider>,
  );

  expect(screen.getByText('Variant of A-1-1')).toBeInTheDocument();
  // The tooltip names the link: the place it is a variant of, and where to merge it.
  const merge = screen.getByRole('link', { name: /variant of A-1-1 - merge it on Location Cleanup/i });
  expect(merge).toHaveAttribute('href', '/app/tenant-owner/location-cleanup');

  const defines = screen.getAllByRole('button', { name: 'Define' });
  expect(defines).toHaveLength(1);
  expect(defines[0]).toBeDisabled();
});

it('does not send a Warehouse Manager to a cleanup page they cannot open - it says who can merge', () => {
  ownsTenant = false;
  try {
    render(
      <ThemeProvider theme={theme}>
        <MemoryRouter>
          <LocationsTab />
        </MemoryRouter>
      </ThemeProvider>,
    );

    expect(screen.queryByRole('link', { name: /merge it on Location Cleanup/i })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/ask a Tenant Owner to merge it/i)).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Define' }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  } finally {
    ownsTenant = true;
  }
});
