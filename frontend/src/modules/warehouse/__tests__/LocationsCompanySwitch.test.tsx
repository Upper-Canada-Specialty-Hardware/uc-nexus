import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import LocationsTab from '../LocationsTab';
import { GET_LOCATION_UTILIZATION, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';

// #1469: a UC NEXUS ADMIN's company switch reloads the warehouse list. The previous company's warehouse
// must drop out of the filter the rail and the registry are asked for, not narrow both to nothing.
const warehouse = (id: string, name: string) => ({ id, name, code: id.toUpperCase(), isActive: true });
let warehouses = [warehouse('wa-1', 'A Main'), warehouse('wa-2', 'A Yard')];
const sent: { query: DocumentNode; variables: Record<string, unknown> | undefined }[] = [];

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode, options?: { variables?: Record<string, unknown> }) => {
    sent.push({ query, variables: options?.variables });
    const data =
      query === GET_WAREHOUSES
        ? { warehouses }
        : query === GET_LOCATION_UTILIZATION
          ? { locationUtilization: [] }
          : query === GET_WAREHOUSE_LOCATIONS
            ? { warehouseLocations: [] }
            : undefined;
    return { data, loading: false, error: undefined, refetch: vi.fn() };
  },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: true, hasRole: () => true }),
}));

beforeEach(() => {
  sent.length = 0;
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

const lastVariables = (query: DocumentNode) => [...sent].reverse().find((s) => s.query === query)?.variables;

it("drops the previous company's warehouse filter on a company switch (#1469)", () => {
  // A fresh element each time: the same one again would let React skip the re-render.
  const ui = () => (
    <MemoryRouter>
      <LocationsTab />
    </MemoryRouter>
  );
  const { rerender } = render(ui());

  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'Warehouse' }));
  fireEvent.click(within(screen.getByRole('listbox')).getByRole('option', { name: 'A Yard (WA-2)' }));
  expect(lastVariables(GET_LOCATION_UTILIZATION)).toEqual({ warehouseId: 'wa-2' });

  warehouses = [warehouse('wb-1', 'B Main'), warehouse('wb-2', 'B Yard')];
  rerender(ui());

  expect(lastVariables(GET_LOCATION_UTILIZATION)).toEqual({ warehouseId: null });
  expect(lastVariables(GET_WAREHOUSE_LOCATIONS)).toEqual({ warehouseId: null });
  expect(screen.getByRole('combobox', { name: 'Warehouse' })).not.toHaveTextContent('A Yard');
});
