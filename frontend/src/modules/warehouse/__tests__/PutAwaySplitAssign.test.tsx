import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PutAwayTab from '../PutAwayTab';
import { GET_UNLOCATED_INVENTORY, GET_STOCK_ITEMS, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { SPLIT_INVENTORY_LOCATION, ASSIGN_INVENTORY_LOCATION } from '../../../graphql/shared';

// #1378: a partial put-away splits, then assigns the broken-off piece. When the split lands but the
// assign is refused, the queue must redraw and the typed quantity clear, or a retry splits the wrong row.

const RESULTS = new Map<DocumentNode, unknown>([
  [
    GET_UNLOCATED_INVENTORY,
    {
      unlocatedInventory: [
        {
          inventoryLocation: {
            id: 'loc-1',
            projectId: 'p-1',
            warehouseId: 'w-1',
            hardwareCategory: 'HINGE',
            productCode: 'HG-100',
            quantity: 4,
            deficientQuantity: 0,
            receivedAt: '2026-09-01T00:00:00',
          },
          poNumber: 'PO-1',
          classification: null,
          unitCost: 5,
        },
      ],
    },
  ],
  [GET_STOCK_ITEMS, { stockItems: [] }],
  [
    GET_WAREHOUSE_LOCATIONS,
    { warehouseLocations: [{ id: 'l-1', warehouseId: 'w-1', aisle: 'A', row: '1', bay: '1', active: true }] },
  ],
]);

const refetch = vi.fn();
const showToast = vi.fn();
const split = vi.fn();
const assign = vi.fn();

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) => ({ data: RESULTS.get(query), loading: false, error: undefined, refetch }),
  useMutation: (doc: DocumentNode) => {
    if (doc === SPLIT_INVENTORY_LOCATION) return [split, { loading: false }];
    if (doc === ASSIGN_INVENTORY_LOCATION) return [assign, { loading: false }];
    return [vi.fn(), { loading: false }];
  },
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast }) }));

// The registry pickers become plain inputs so the test can fill a defined location directly.
vi.mock('../../../components/LocationAutocomplete', () => ({
  default: ({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) => (
    <input aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} />
  ),
}));

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
      }
      observe() {
        this.cb([{ contentRect: { width: 1200 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    },
  );
  refetch.mockClear();
  showToast.mockClear();
  split.mockReset();
  assign.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('PutAwayTab split then assign (#1378)', () => {
  it('when the assign is refused after the split, redraws the queue, clears the quantity and says so', async () => {
    split.mockResolvedValue({ data: { splitInventoryLocation: [{ id: 'loc-1' }, { id: 'loc-2' }] } });
    assign.mockRejectedValue(new Error('Location A-1-1 is retired'));

    render(
      <MemoryRouter>
        <PutAwayTab />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getAllByLabelText('Aisle')[0], { target: { value: 'A' } });
    fireEvent.change(screen.getAllByLabelText('Row')[0], { target: { value: '1' } });
    fireEvent.change(screen.getAllByLabelText('Bay')[0], { target: { value: '1' } });
    const qty = screen.getByLabelText('Quantity of HG-100 to put away');
    fireEvent.change(qty, { target: { value: '2' } });

    const assignButton = screen.getAllByRole('button', { name: /assign/i }).find((b) => !b.hasAttribute('disabled'));
    expect(assignButton).toBeDefined();
    fireEvent.click(assignButton!);

    await waitFor(() => expect(assign).toHaveBeenCalled());
    await waitFor(() => expect(refetch).toHaveBeenCalled());
    expect(assign.mock.calls[0][0].variables.inventoryLocationId).toBe('loc-2');
    expect(showToast).toHaveBeenCalledWith(
      '2 of HG-100 is now its own row in the queue; assign failed: Location A-1-1 is retired',
      'error',
    );
    expect((screen.getByLabelText('Quantity of HG-100 to put away') as HTMLInputElement).value).toBe('');
  });

  it('a refused split alone keeps the quantity and only reports the error', async () => {
    split.mockRejectedValue(new Error('Split refused'));

    render(
      <MemoryRouter>
        <PutAwayTab />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getAllByLabelText('Aisle')[0], { target: { value: 'A' } });
    fireEvent.change(screen.getAllByLabelText('Row')[0], { target: { value: '1' } });
    fireEvent.change(screen.getAllByLabelText('Bay')[0], { target: { value: '1' } });
    fireEvent.change(screen.getByLabelText('Quantity of HG-100 to put away'), { target: { value: '2' } });
    const assignButton = screen.getAllByRole('button', { name: /assign/i }).find((b) => !b.hasAttribute('disabled'));
    fireEvent.click(assignButton!);

    await waitFor(() => expect(showToast).toHaveBeenCalledWith('Split refused', 'error'));
    expect(assign).not.toHaveBeenCalled();
    expect(refetch).not.toHaveBeenCalled();
    expect((screen.getByLabelText('Quantity of HG-100 to put away') as HTMLInputElement).value).toBe('2');
  });
});
