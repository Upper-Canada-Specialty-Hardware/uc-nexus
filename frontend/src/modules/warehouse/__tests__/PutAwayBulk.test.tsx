import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PutAwayTab from '../PutAwayTab';
import {
  GET_UNLOCATED_INVENTORY,
  GET_STOCK_ITEMS,
  GET_WAREHOUSE_LOCATIONS,
  ASSIGN_STOCK_ITEM_LOCATION,
} from '../../../graphql/warehouse';
import { GET_WAREHOUSES, ASSIGN_INVENTORY_LOCATION } from '../../../graphql/shared';

// #857: ticking several Put Away rows and sending them all to one bin from the selection bar.

// Every row carries three pickers, so the role queries over the page are slow in jsdom.
vi.setConfig({ testTimeout: 30_000 });

function inventoryRow(id: string, warehouseId: string, productCode: string, quantity: number) {
  return {
    inventoryLocation: {
      id,
      projectId: 'p-1',
      warehouseId,
      hardwareCategory: 'HINGE',
      productCode,
      quantity,
      receivedAt: '2026-09-01T00:00:00',
    },
    poNumber: 'PO-1',
    classification: null,
    unitCost: 5,
  };
}

// Three project rows (two in MAIN, one in EAST) and one MAIN stock-pool row. Only MAIN has a
// defined bin, A-1-2.
const RESULTS = new Map<DocumentNode, unknown>([
  [
    GET_UNLOCATED_INVENTORY,
    {
      unlocatedInventory: [
        inventoryRow('loc-1', 'w-1', 'HG-100', 4),
        inventoryRow('loc-2', 'w-1', 'HG-200', 6),
        inventoryRow('loc-3', 'w-2', 'HG-300', 3),
      ],
    },
  ],
  [
    GET_STOCK_ITEMS,
    {
      stockItems: [
        {
          id: 'stock-1',
          warehouseId: 'w-1',
          hardwareCategory: 'LOCK',
          productCode: 'LK-9',
          quantity: 2,
          receivedAt: '2026-09-01T00:00:00',
        },
      ],
    },
  ],
  [
    GET_WAREHOUSES,
    {
      warehouses: [
        { id: 'w-1', name: 'Main', code: 'MAIN' },
        { id: 'w-2', name: 'East', code: 'EAST' },
      ],
    },
  ],
  [GET_WAREHOUSE_LOCATIONS, { warehouseLocations: [{ id: 'wl-1', warehouseId: 'w-1', aisle: 'A', row: '1', bay: '2' }] }],
]);

const assignInventory = vi.fn();
const assignStock = vi.fn();
const otherMutation = vi.fn();
const showToast = vi.fn();

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) => ({ data: RESULTS.get(query), loading: false, error: undefined, refetch: vi.fn() }),
  useMutation: (doc: DocumentNode) => [
    doc === ASSIGN_INVENTORY_LOCATION ? assignInventory : doc === ASSIGN_STOCK_ITEM_LOCATION ? assignStock : otherMutation,
    { loading: false },
  ],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast }) }));

beforeEach(() => {
  assignInventory.mockReset().mockResolvedValue({ data: {} });
  assignStock.mockReset().mockResolvedValue({ data: {} });
  showToast.mockReset();
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
      }
      observe() {
        this.cb([{ contentRect: { width: 1000 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderTab() {
  return render(
    <MemoryRouter>
      <PutAwayTab />
    </MemoryRouter>,
  );
}

const tick = (productCode: string) => fireEvent.click(screen.getByRole('checkbox', { name: `Select ${productCode}` }));

/** The bar's pickers are the last Aisle / Row / Bay on the page: every row has its own set above. */
function pickBulkBin(aisle: string, row: string, bay: string) {
  for (const [label, value] of [
    ['Aisle', aisle],
    ['Row', row],
    ['Bay', bay],
  ] as const) {
    const boxes = screen.getAllByRole('combobox', { name: label });
    fireEvent.change(boxes[boxes.length - 1], { target: { value } });
  }
}

describe('Put Away, several rows at once (#857)', () => {
  it('puts each ticked row away whole, in the chosen bin, one call per row', async () => {
    renderTab();

    tick('HG-100');
    tick('HG-200');
    tick('LK-9');
    pickBulkBin('A', '1', '2');
    fireEvent.click(screen.getByRole('button', { name: 'Put away 3 rows here' }));

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('3 rows put away in A-1-2', 'success'));
    // No quantity is passed: the assign mutation moves the whole row, which is the full quantity.
    expect(assignInventory.mock.calls.map((c) => c[0].variables)).toEqual([
      { inventoryLocationId: 'loc-1', aisle: 'A', row: '1', bay: '2' },
      { inventoryLocationId: 'loc-2', aisle: 'A', row: '1', bay: '2' },
    ]);
    expect(assignStock.mock.calls.map((c) => c[0].variables)).toEqual([
      { stockItemId: 'stock-1', aisle: 'A', row: '1', bay: '2' },
    ]);
    expect(otherMutation).not.toHaveBeenCalled();
    // Everything went, so nothing stays ticked and the bar goes away.
    expect(screen.queryByRole('button', { name: /Put away \d+ rows? here/ })).toBeNull();
  });

  it('holds the put-away until the bin is a defined one', () => {
    renderTab();

    tick('HG-100');
    // Re-read each time: the disabled button sits inside a tooltip wrapper the enabled one drops.
    const button = () => screen.getByRole('button', { name: 'Put away 1 row here' });
    expect(button()).toBeDisabled();

    pickBulkBin('Z', '9', '9');
    expect(button()).toBeDisabled();

    pickBulkBin('A', '1', '2');
    expect(button()).toBeEnabled();
  });

  it("disables other warehouses' rows once one is ticked, and says why", async () => {
    renderTab();

    tick('HG-100');

    const east = screen.getByRole('checkbox', { name: 'Select HG-300' });
    expect(east).toBeDisabled();
    fireEvent.mouseOver(east);
    expect(
      await screen.findByText(
        'Only rows from the same warehouse can be put away together. This row is in EAST; the ticked rows are in MAIN.',
      ),
    ).toBeInTheDocument();
    // Rows from the same warehouse stay open.
    expect(screen.getByRole('checkbox', { name: 'Select HG-200' })).toBeEnabled();

    // Unticked again, every row can be picked.
    tick('HG-100');
    expect(screen.getByRole('checkbox', { name: 'Select HG-300' })).toBeEnabled();
  });

  it("the header box ticks only the first warehouse's rows", () => {
    renderTab();

    const [projectAll] = screen.getAllByRole('checkbox', { name: 'Select all rows in this table' });
    fireEvent.click(projectAll);

    expect(screen.getByRole('checkbox', { name: 'Select HG-100' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select HG-200' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select HG-300' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Put away 2 rows here' })).toBeInTheDocument();
  });

  it('keeps the rows that failed ticked, names them with the reason, and clears the rest', async () => {
    assignInventory.mockImplementation(({ variables }: { variables: { inventoryLocationId: string } }) =>
      variables.inventoryLocationId === 'loc-2'
        ? Promise.reject(new Error('Bin A-1-2 is full'))
        : Promise.resolve({ data: {} }),
    );
    renderTab();

    tick('HG-100');
    tick('HG-200');
    tick('LK-9');
    pickBulkBin('A', '1', '2');
    fireEvent.click(screen.getByRole('button', { name: 'Put away 3 rows here' }));

    expect(await screen.findByText(/1 row was not put away/)).toBeInTheDocument();
    expect(screen.getByText(': Bin A-1-2 is full')).toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith(expect.stringContaining('2 of 3 rows put away in A-1-2'), 'error');
    // The failed row is still ticked, ready to try again; the two that went are not.
    expect(screen.getByRole('checkbox', { name: 'Select HG-200' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select HG-100' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Select LK-9' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Put away 1 row here' })).toBeInTheDocument();
  });
});
