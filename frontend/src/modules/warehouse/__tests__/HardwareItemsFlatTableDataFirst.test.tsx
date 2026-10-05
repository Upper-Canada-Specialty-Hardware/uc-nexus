import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import HardwareItemsFlatTable from '../HardwareItemsFlatTable';

// #1584: Apollo sets `loading` on every refetch and keeps the last rows beside a failed one. The table used to
// swap itself for a spinner on each refetch (page, sort and filter lost after every row action) and hide loaded
// rows behind a bare error when a refresh failed.

vi.setConfig({ testTimeout: 30_000 });

type QueryState = { data?: unknown; loading: boolean; error?: Error };
let state: QueryState;
const refetch = vi.fn(() => Promise.resolve());

vi.mock('@apollo/client/react', () => ({
  useQuery: () => ({ ...state, refetch }),
  useMutation: () => [vi.fn(), { loading: false }],
  useApolloClient: () => ({ query: vi.fn(), refetchQueries: vi.fn() }),
}));
const noCatalog = { byKey: new Map() };
vi.mock('../../../hooks/useCustomItems', () => ({
  useCustomInventoryItems: () => noCatalog,
  catalogKey: (c: string, p: string) => `${c}|${p}`,
}));
vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

function row(id: string, productCode: string, quantity: number, lineValue: number) {
  return {
    inventoryLocation: {
      id,
      projectId: 'p-1',
      poLineItemId: null,
      receiveLineItemId: null,
      stockItemId: null,
      warehouseId: 'w-1',
      hardwareCategory: 'HINGE',
      productCode,
      quantity,
      deficientQuantity: 0,
      available: quantity,
      aisle: 'A',
      row: '1',
      bay: '1',
      receivedAt: '2026-09-01T12:00:00Z',
      createdAt: '2026-09-01T12:00:00Z',
      updatedAt: '2026-09-01T12:00:00Z',
    },
    unitCost: lineValue / quantity,
    lineValue,
    poNumber: 'PO-1',
    vendorName: 'Vendor',
    warehouseCode: 'W1',
    warehouseName: 'Main',
    projectNumber: 'J-1',
    projectName: 'Job',
    matchesSchedule: true,
  };
}

const loaded = { inventoryRows: [row('r-1', 'HG-100', 4, 40), row('r-2', 'LK-200', 6, 120)] };

beforeEach(() => {
  refetch.mockClear();
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

it('keeps the grid on screen while a refetch runs', () => {
  state = { data: loaded, loading: true };
  render(<HardwareItemsFlatTable projectId="p-1" />);

  expect(screen.getByRole('grid')).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});

it('keeps loaded rows when a refresh fails, with a warning above them', () => {
  state = { data: loaded, loading: false, error: new TypeError('Failed to fetch') };
  render(<HardwareItemsFlatTable projectId="p-1" />);

  expect(screen.getByRole('grid')).toBeInTheDocument();
  expect(screen.getByText(/Couldn.t refresh the inventory/)).toBeInTheDocument();
});

it('says the inventory could not be loaded, with a retry, when nothing loaded', () => {
  state = { loading: false, error: new TypeError('Failed to fetch') };
  render(<HardwareItemsFlatTable projectId="p-1" />);

  fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(refetch).toHaveBeenCalled();
});

it('totals the rows the filter leaves, and drops a filtered-out row from the selection', async () => {
  state = { data: loaded, loading: false };
  render(<HardwareItemsFlatTable projectId="p-1" />);

  const units = () => screen.getByText('Total units').nextElementSibling as HTMLElement;
  expect(units()).toHaveTextContent('10');

  // Select the LK-200 row, then filter to HG-100 only.
  const lk = await screen.findByRole('row', { name: /LK-200/ });
  fireEvent.click(within(lk).getByRole('checkbox'));
  expect(await screen.findByText('1 selected')).toBeInTheDocument();

  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'HG-100' } });
  await act(() => new Promise((resolve) => setTimeout(resolve, 600)));

  await waitFor(() => expect(units()).toHaveTextContent('4'));
  expect(screen.queryByText('1 selected')).not.toBeInTheDocument();
});
