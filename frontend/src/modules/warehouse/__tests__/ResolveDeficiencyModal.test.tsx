import { render, screen, fireEvent, within, configure, waitFor } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import { RESOLVE_DEFICIENCY } from '../../../graphql/warehouse';
import ResolveDeficiencyModal, { type DeficientRow } from '../stock/ResolveDeficiencyModal';

// Renders inside a MUI Dialog; lift the budgets like the other modal tests do.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const projectRow: DeficientRow = {
  source: 'PROJECT_INVENTORY',
  inventoryLocationId: 'inv-1',
  stockItemId: null,
  hardwareCategory: 'Hinges',
  productCode: 'HG-100',
  deficientQuantity: 3,
};

const poolRow: DeficientRow = {
  source: 'STOCK_POOL',
  inventoryLocationId: null,
  stockItemId: 'si-1',
  hardwareCategory: 'Hinges',
  productCode: 'HG-100',
  deficientQuantity: 3,
};

function renderModal(row: DeficientRow, mocks: MockedResponse[] = []) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <ResolveDeficiencyModal row={row} onClose={vi.fn()} onSuccess={vi.fn()} />
      </ToastProvider>
    </MockedProvider>,
  );
}

function resolveButton() {
  return screen.getByRole('button', { name: 'Resolve' });
}

describe('ResolveDeficiencyModal', () => {
  it('asks for the pool cost when a project row is sent to stock, with no default', () => {
    renderModal(projectRow); // resolution defaults to Send to stock pool
    expect(screen.getByText('Cost in the pool')).toBeInTheDocument();
    expect(resolveButton()).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Keeps its cost' }));
    expect(resolveButton()).toBeEnabled();
  });

  it('does not ask for a pool row, which is already in the pool at its own price', () => {
    renderModal(poolRow);
    expect(screen.queryByText('Cost in the pool')).not.toBeInTheDocument();
    expect(resolveButton()).toBeEnabled();
  });

  it('does not ask for any other resolution', async () => {
    renderModal(projectRow);
    fireEvent.mouseDown(screen.getByRole('combobox'));
    const listbox = await screen.findByRole('listbox');
    fireEvent.click(within(listbox).getByText('Scrap / write off'));

    expect(screen.queryByText('Cost in the pool')).not.toBeInTheDocument();
    expect(resolveButton()).toBeEnabled();
  });

  it('sends the chosen cost with the send-to-stock resolution', async () => {
    const variables = {
      input: {
        inventoryLocationId: 'inv-1',
        stockItemId: null,
        resolution: 'SEND_TO_STOCK',
        quantity: 3,
        reasonText: null,
        rmaReference: null,
        destockSource: 'DEFICIENT_SWAP',
        destockCost: 'ZERO',
      },
    };
    const result = vi.fn(() => ({
      data: {
        resolveDeficiency: {
          __typename: 'DeficiencyReview',
          id: 'rev-1',
          inventoryLocationId: 'inv-1',
          stockItemId: null,
          resolution: 'SEND_TO_STOCK',
          quantity: 3,
          reasonText: null,
          rmaReference: null,
          reviewedBy: 'manager',
          reviewedAt: '2026-09-30T00:00:00',
          resultingStockItemId: 'si-9',
        },
      },
    }));
    renderModal(projectRow, [{ request: { query: RESOLVE_DEFICIENCY, variables }, result }]);

    fireEvent.click(screen.getByRole('button', { name: 'Left behind - $0 cost' }));
    fireEvent.click(resolveButton());

    await waitFor(() => expect(result).toHaveBeenCalled());
  });
});
