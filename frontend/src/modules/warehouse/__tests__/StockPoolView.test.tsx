import { render, screen, fireEvent, waitFor, within, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import StockPoolView, { type StockItem } from '../StockPoolView';
import { GET_STOCK_ITEMS } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import { GET_INVENTORY_ITEM_TYPES } from '../../../graphql/customItems';

// The page clears its filter on an acting-company switch (#1537); outside the app shell there is no company
// provider, so the acting company is stood in for.
vi.mock('../../../company/ActingCompanyContext', () => ({ useActingCompany: () => ({ company: 'TUBC' }) }));

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const INFINITE = Number.POSITIVE_INFINITY;

const item = (over: Partial<StockItem>): StockItem => ({
  id: 'si',
  warehouseId: 'wh-1',
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 5,
  deficientQuantity: 0,
  available: 5,
  unitCost: null,
  kind: 'STOCK',
  aisle: 'A',
  row: '1',
  bay: '1',
  receivedAt: '2026-09-01T12:00:00',
  createdAt: '2026-09-01T12:00:00',
  updatedAt: '2026-09-01T12:00:00',
  ...over,
});

const ROWS = [
  item({ id: 'si-stock', productCode: 'HG-STOCK' }),
  item({ id: 'si-oh', productCode: 'HG-OVERHEAD', kind: 'OVERHEAD' }),
];

function renderView(stockVariables: Record<string, unknown>[]) {
  const mocks: MockedResponse[] = [
    {
      request: { query: GET_STOCK_ITEMS, variables: () => true },
      maxUsageCount: INFINITE,
      result: (vars) => {
        stockVariables.push(vars as Record<string, unknown>);
        const kind = (vars as { kind?: string | null }).kind;
        const rows = kind ? ROWS.filter((r) => r.kind === kind) : ROWS;
        return { data: { stockItems: rows.map((r) => ({ ...r, __typename: 'StockItem' })) } };
      },
    },
    {
      request: { query: GET_WAREHOUSES, variables: () => true },
      maxUsageCount: INFINITE,
      result: {
        data: { warehouses: [{ __typename: 'Warehouse', id: 'wh-1', name: 'Main', code: 'MAIN' }] },
      },
    },
    {
      request: { query: GET_INVENTORY_ITEM_TYPES, variables: () => true },
      maxUsageCount: INFINITE,
      result: { data: { inventoryItemTypes: [] } },
    },
  ];
  return render(
    <MockedProvider mocks={mocks}>
      <MemoryRouter>
        <ToastProvider>
          <StockPoolView />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

describe('StockPoolView Stock and Overhead (#832)', () => {
  it('shows each row’s kind as a chip and filters by kind', async () => {
    const calls: Record<string, unknown>[] = [];
    renderView(calls);

    const overheadRow = (await screen.findByText('HG-OVERHEAD')).closest('[role="row"]') as HTMLElement;
    expect(within(overheadRow).getByText('Overhead')).toBeInTheDocument();
    const stockRow = screen.getByText('HG-STOCK').closest('[role="row"]') as HTMLElement;
    expect(within(stockRow).getByText('Stock')).toBeInTheDocument();
    // "All" sends no kind at all.
    expect(calls[0]).toMatchObject({ kind: null });

    fireEvent.click(screen.getByRole('button', { name: 'Overhead' }));
    await waitFor(() => expect(calls.some((v) => v.kind === 'OVERHEAD')).toBe(true));
    await waitFor(() => expect(screen.queryByText('HG-STOCK')).toBeNull());
  });

  it('names the mark action after the kind the selected row becomes', async () => {
    renderView([]);

    const overheadRow = (await screen.findByText('HG-OVERHEAD')).closest('[role="row"]') as HTMLElement;
    fireEvent.click(within(overheadRow).getByRole('checkbox'));
    expect(await screen.findByRole('button', { name: 'Mark as Stock' })).toBeInTheDocument();
  });
});
