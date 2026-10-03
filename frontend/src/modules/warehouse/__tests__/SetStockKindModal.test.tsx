import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import SetStockKindModal from '../stock/SetStockKindModal';
import { SET_STOCK_ITEM_KIND } from '../../../graphql/warehouse';
import type { StockItem } from '../StockPoolView';

// The modal renders inside a MUI Dialog; under the full parallel suite jsdom rendering is slow.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const baseItem: StockItem = {
  id: 'si-1',
  warehouseId: 'wh-1',
  hardwareCategory: 'HINGE',
  productCode: 'HG-100',
  quantity: 10,
  deficientQuantity: 2,
  available: 8,
  unitCost: null,
  kind: 'STOCK',
  aisle: 'A',
  row: '1',
  bay: '1',
  receivedAt: '2026-09-01T12:00:00',
  createdAt: '2026-09-01T12:00:00',
  updatedAt: '2026-09-01T12:00:00',
};

function renderModal(item: Partial<StockItem> = {}, mocks: MockedResponse[] = []) {
  const onSuccess = vi.fn();
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <SetStockKindModal item={{ ...baseItem, ...item }} onClose={vi.fn()} onSuccess={onSuccess} />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onSuccess };
}

const quantityInput = () => screen.getByLabelText(/Quantity/) as HTMLInputElement;

describe('SetStockKindModal (#832)', () => {
  it('turns a Stock row into Overhead, capped at its available units', () => {
    renderModal();
    expect(screen.getByRole('button', { name: 'Mark as Overhead' })).toBeEnabled();
    expect(screen.getByLabelText(/Quantity \(max 8\)/)).toBeInTheDocument();
    // The deficient units are named as staying behind.
    expect(screen.getByText(/2 deficient unit\(s\) stay Stock/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '9' } });
    expect(screen.getByRole('button', { name: 'Mark as Overhead' })).toBeDisabled();
    fireEvent.change(quantityInput(), { target: { value: '0' } });
    expect(screen.getByRole('button', { name: 'Mark as Overhead' })).toBeDisabled();
    fireEvent.change(quantityInput(), { target: { value: '3' } });
    expect(screen.getByRole('button', { name: 'Mark as Overhead' })).toBeEnabled();
    expect(screen.getByText('7 stay Stock on this shelf')).toBeInTheDocument();
  });

  it('turns an Overhead row into Stock', () => {
    renderModal({ kind: 'OVERHEAD', deficientQuantity: 0, available: 10 });
    expect(screen.getByRole('button', { name: 'Mark as Stock' })).toBeEnabled();
    expect(screen.getByText('The whole row becomes Stock')).toBeInTheDocument();
  });

  it('sends the row, the other kind and the quantity', async () => {
    const calls: Record<string, unknown>[] = [];
    const mock: MockedResponse = {
      request: { query: SET_STOCK_ITEM_KIND, variables: () => true },
      result: (vars) => {
        calls.push(vars as Record<string, unknown>);
        return {
          data: {
            setStockItemKind: {
              __typename: 'SetStockItemKindResult',
              stockItem: {
                __typename: 'StockItem',
                id: 'si-2',
                kind: 'OVERHEAD',
                quantity: 4,
                deficientQuantity: 0,
                available: 4,
              },
              originalStockItem: {
                __typename: 'StockItem',
                id: 'si-1',
                kind: 'STOCK',
                quantity: 6,
                deficientQuantity: 2,
                available: 4,
              },
            },
          },
        };
      },
    };
    const { onSuccess } = renderModal({}, [mock]);

    fireEvent.change(quantityInput(), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Mark as Overhead' }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls[0]).toEqual({ input: { stockItemId: 'si-1', kind: 'OVERHEAD', quantity: 4 } });
  });
});
