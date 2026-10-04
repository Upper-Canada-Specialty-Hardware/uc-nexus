import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { DocumentNode } from 'graphql';
import PutAwayTab from '../PutAwayTab';
import { GET_UNLOCATED_INVENTORY, GET_STOCK_ITEMS } from '../../../graphql/warehouse';

// The tab reads five queries; only the two queues matter here, so each query document answers with a
// canned result instead of a MockedProvider mock per exact variable set.
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
            receivedAt: '2026-09-01T00:00:00',
          },
          poNumber: 'PO-1',
          classification: null,
          unitCost: 5,
        },
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
]);

// A query listed here fails instead: no data, its error set (#1503).
const FAILED = new Set<DocumentNode>();

vi.mock('@apollo/client/react', () => ({
  useQuery: (query: DocumentNode) =>
    FAILED.has(query)
      ? { data: undefined, loading: false, error: new Error('Network down'), refetch: vi.fn() }
      : { data: RESULTS.get(query), loading: false, error: undefined, refetch: vi.fn() },
  useMutation: () => [vi.fn(), { loading: false }],
}));

vi.mock('../../../components/Toast', () => ({ useToast: () => ({ showToast: vi.fn() }) }));

// jsdom has no layout: every table reports the ~770 px a Put Away table gets in an 850 px window.
beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
      }
      observe() {
        this.cb([{ contentRect: { width: 770 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  FAILED.clear();
});

function renderTab() {
  return render(
    <MemoryRouter>
      <PutAwayTab />
    </MemoryRouter>,
  );
}

describe('PutAwayTab at a narrow width (#856)', () => {
  it('fits both tables to their width, so Assign is in view without any sideways scroll', () => {
    const { container } = renderTab();

    const tables = Array.from(container.querySelectorAll('[data-fit-table]')) as HTMLElement[];
    expect(tables.map((t) => t.getAttribute('data-fit-table'))).toEqual(['put-away-project', 'put-away-stock-pool']);
    for (const box of tables) {
      expect(['auto', 'scroll']).not.toContain(getComputedStyle(box).overflowX);
      const cols = Array.from(box.querySelectorAll('col')).map((c) => parseFloat(c.style.width));
      expect(cols.reduce((a, b) => a + b, 0)).toBeCloseTo(770, 0);
      // Assign's column is last and keeps its full width.
      expect(cols[cols.length - 1]).toBe(96);
    }

    const assigns = screen.getAllByRole('button', { name: 'Assign' });
    expect(assigns).toHaveLength(2);
    for (const button of assigns) {
      const cell = button.closest('td') as HTMLElement;
      // No pinning: it is an ordinary last cell, so keyboard order through the row is unchanged.
      expect(getComputedStyle(cell).position).not.toBe('sticky');
      expect(cell.nextElementSibling).toBeNull();
    }
  });

  it('lets each table column be resized from the keyboard, with the column named', () => {
    renderTab();

    for (const name of ['Description', 'PO#', 'Received', 'Destination', 'Qty to put away', 'Item Number']) {
      expect(screen.getAllByRole('separator', { name: `Resize ${name} column` }).length).toBeGreaterThan(0);
    }
    // Assign is a fixed column: no handle.
    expect(screen.queryByRole('separator', { name: 'Resize Assign column' })).not.toBeInTheDocument();
  });

  it('keeps the destination pickers whole at their minimum', () => {
    renderTab();

    const destination = screen.getAllByRole('separator', { name: 'Resize Destination column' })[0];
    expect(Number(destination.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(248);
  });
});

describe('PutAwayTab failed stock read (#1503)', () => {
  it('says the stock pool read failed instead of dropping the section', () => {
    FAILED.add(GET_STOCK_ITEMS);
    renderTab();

    expect(screen.getByText(/couldn.t load the unlocated stock pool/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    // The project queue still renders; only the stock section is replaced by the banner.
    expect(screen.queryByText('Stock Pool')).not.toBeInTheDocument();
  });
});
