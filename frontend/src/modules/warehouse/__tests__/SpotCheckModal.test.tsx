import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../../components/Toast';
import SpotCheckModal from '../SpotCheckModal';
import { ADJUST_INVENTORY_QUANTITY } from '../../../graphql/warehouse';

vi.mock('@clerk/clerk-react', () => ({
  useUser: () => ({ user: { fullName: 'Spot Checker', publicMetadata: {} } }),
}));

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

// No projectId, so the reservation lookup is skipped and only the adjustment is mocked.
const item = {
  id: 'inv-1',
  productCode: 'HG-100',
  hardwareCategory: 'HINGES',
  quantity: 10,
  deficientQuantity: 0,
  aisle: 'A1',
  row: 'R1',
  bay: 'B1',
};

describe('SpotCheckModal', () => {
  it('a double click on Apply sends the discrepancy once (#1204)', async () => {
    let calls = 0;
    const adjustMock: MockedResponse = {
      request: {
        query: ADJUST_INVENTORY_QUANTITY,
        variables: {
          inventoryLocationId: 'inv-1',
          adjustment: -3,
          reason: 'Spot check: system=10, physical=7',
          spotCheck: true,
        },
      },
      delay: 50,
      result: () => {
        calls += 1;
        return {
          data: {
            adjustInventoryQuantity: {
              __typename: 'InventoryLocation',
              id: 'inv-1',
              projectId: null,
              poLineItemId: null,
              receiveLineItemId: null,
              hardwareCategory: 'HINGES',
              productCode: 'HG-100',
              quantity: 7,
              deficientQuantity: 0,
              available: 7,
              aisle: 'A1',
              row: 'R1',
              bay: 'B1',
              receivedAt: null,
              createdAt: '2026-01-01T00:00:00Z',
              updatedAt: '2026-01-01T00:00:00Z',
            },
          },
        };
      },
    };
    const onSuccess = vi.fn();
    render(
      <MockedProvider mocks={[adjustMock]}>
        <ToastProvider>
          <SpotCheckModal open item={item} onClose={vi.fn()} onSuccess={onSuccess} />
        </ToastProvider>
      </MockedProvider>,
    );

    fireEvent.change(screen.getByLabelText('Physical Count'), { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Adjustment' }));
    const apply = await screen.findByRole('button', { name: 'Apply' });
    fireEvent.click(apply);
    fireEvent.click(apply);

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls).toBe(1);
  });
});
