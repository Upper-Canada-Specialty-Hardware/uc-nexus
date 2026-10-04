import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@mui/material';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import {
  GET_INVENTORY_ROWS,
  GET_LOCATION_UTILIZATION,
  GET_STOCK_ITEMS,
  GET_WAREHOUSE_LOCATIONS,
} from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import theme from '../../../theme';

// #1519: the product-code search's two reads are keyed by warehouse only, not by the search text. Read
// cache-first, the first search of a session answered every later one, so hardware put away or moved
// since never showed where it now sits.
const policies = new Map<DocumentNode, string | undefined>();

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { skip?: boolean; fetchPolicy?: string }) => {
    if (!options?.skip) policies.set(query, options?.fetchPolicy);
    const data =
      query === GET_WAREHOUSES
        ? { warehouses: [{ id: 'w-1', name: 'Main', code: 'W-1', isActive: true }] }
        : query === GET_LOCATION_UTILIZATION
          ? { locationUtilization: [] }
          : query === GET_WAREHOUSE_LOCATIONS
            ? { warehouseLocations: [] }
            : query === GET_INVENTORY_ROWS
              ? { inventoryRows: [] }
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
  policies.clear();
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

it('reads the product search from the server each time, not from the first search of the session', () => {
  render(
    <ThemeProvider theme={theme}>
      <MemoryRouter>
        <LocationsTab />
      </MemoryRouter>
    </ThemeProvider>,
  );

  fireEvent.change(screen.getByLabelText('Search locations'), { target: { value: 'HG-100' } });

  expect(policies.get(GET_INVENTORY_ROWS)).toBe('cache-and-network');
  expect(policies.get(GET_STOCK_ITEMS)).toBe('cache-and-network');
});
