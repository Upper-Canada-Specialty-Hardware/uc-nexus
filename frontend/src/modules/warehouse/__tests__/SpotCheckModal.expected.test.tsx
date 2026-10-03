import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import SpotCheckModal from '../SpotCheckModal';
import { ADJUST_INVENTORY_QUANTITY } from '../../../graphql/warehouse';

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({ ownsTenant: false, hasRole: () => false }),
}));

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

// No projectId: the reservation lookup is skipped, so only the adjust mutation is in play.
const item = {
  id: 'inv-1',
  productCode: 'HG-100',
  hardwareCategory: 'HINGE',
  quantity: 10,
  deficientQuantity: 0,
  aisle: 'A1',
  row: 'C1',
  bay: 'B1',
};

describe('SpotCheckModal', () => {
  it('sends the count it compared against, so a row that moved is refused (#1315)', async () => {
    let calledVariables: Record<string, unknown> | null = null;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_INVENTORY_QUANTITY,
          variables: {
            inventoryLocationId: 'inv-1',
            adjustment: -3,
            reason: 'Spot check: system=10, physical=7',
            spotCheck: true,
            expectedQuantity: 10,
          },
        },
        result: (vars: Record<string, unknown>) => {
          calledVariables = vars as Record<string, unknown>;
          return {
            data: {
              adjustInventoryQuantity: {
                id: 'inv-1',
                quantity: 7,
                deficientQuantity: 0,
                available: 7,
                __typename: 'InventoryLocation',
              },
            },
          };
        },
      },
    ];
    const onSuccess = vi.fn();
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <SpotCheckModal open onClose={vi.fn()} item={item} onSuccess={onSuccess} />
        </ToastProvider>
      </MockedProvider>,
    );

    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: /apply adjustment/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^apply$/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calledVariables).toMatchObject({ adjustment: -3, spotCheck: true, expectedQuantity: 10 });
  });

  it('closes on a row-changed refusal so the retry starts from the fresh count', async () => {
    const message = 'This row changed from 10 to 6 since you opened it. Reload and try again.';
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_INVENTORY_QUANTITY,
          variables: {
            inventoryLocationId: 'inv-1',
            adjustment: -3,
            reason: 'Spot check: system=10, physical=7',
            spotCheck: true,
            expectedQuantity: 10,
          },
        },
        result: {
          errors: [{ message, extensions: { code: 'CONFLICT', field: 'expected_quantity' } }],
        },
      },
    ];
    const onClose = vi.fn();
    const onSuccess = vi.fn();
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <SpotCheckModal open onClose={onClose} item={item} onSuccess={onSuccess} />
        </ToastProvider>
      </MockedProvider>,
    );

    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: /apply adjustment/i }));
    fireEvent.click(await screen.findByRole('button', { name: /^apply$/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });
});
