import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../../components/Toast';
import TransferDialog, { type TransferSource } from '../TransferDialog';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import { GET_LOCATION_DISTINCT_VALUES, TRANSFER_INVENTORY } from '../../../graphql/warehouse';

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const warehousesMock: MockedResponse = {
  request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
  result: {
    data: {
      warehouses: [
        {
          id: 'wh-1',
          name: 'Main',
          code: 'MN',
          address: null,
          city: null,
          province: null,
          postalCode: null,
          isPrimary: true,
          isActive: true,
          createdAt: '2026-01-01',
          __typename: 'Warehouse',
        },
      ],
    },
  },
};

const distinctMock: MockedResponse = {
  request: { query: GET_LOCATION_DISTINCT_VALUES },
  result: {
    data: { locationDistinctValues: { aisles: ['A1'], rows: ['R1'], bays: ['B1'], __typename: 'LocationDistinctValues' } },
  },
};

function transferMock(input: Record<string, unknown>, onCall?: () => void): MockedResponse {
  return {
    request: { query: TRANSFER_INVENTORY, variables: { input } },
    result: () => {
      onCall?.();
      return {
        data: {
          transferInventory: {
            success: true,
            quantity: input.quantity,
            destWarehouseId: input.destWarehouseId,
            __typename: 'TransferInventoryResult',
          },
        },
      };
    },
  };
}

function renderDialog(sources: TransferSource[], mocks: MockedResponse[]) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <MockedProvider mocks={[warehousesMock, distinctMock, ...mocks]}>
      <ToastProvider>
        <TransferDialog sources={sources} onClose={onClose} onSuccess={onSuccess} />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSuccess };
}

function setLocation(aisle: string, row: string, bay: string) {
  fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: aisle } });
  fireEvent.change(screen.getByLabelText('Row'), { target: { value: row } });
  fireEvent.change(screen.getByLabelText('Bay'), { target: { value: bay } });
}

describe('TransferDialog', () => {
  it('single source: shows a quantity field and fires one transfer', async () => {
    const source: TransferSource = {
      type: 'INVENTORY_LOCATION',
      id: 'inv-1',
      productCode: 'HG-100',
      available: 6,
      warehouseId: 'wh-1',
      aisle: null,
      row: null,
      bay: null,
    };
    let called = 0;
    const mocks = [
      transferMock(
        {
          sourceType: 'INVENTORY_LOCATION',
          sourceId: 'inv-1',
          quantity: 6,
          destWarehouseId: 'wh-1',
          destAisle: 'A1',
          destRow: 'R1',
          destBay: 'B1',
        },
        () => {
          called += 1;
        },
      ),
    ];
    const { onSuccess } = renderDialog([source], mocks);

    // Quantity defaults to full available and is present only in single-source mode.
    expect(screen.getByLabelText('Quantity')).toHaveValue(6);
    setLocation('A1', 'R1', 'B1');
    fireEvent.click(screen.getByRole('button', { name: /^transfer$/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(called).toBe(1);
  });

  it('multiple sources: lists each source, no quantity field, and loops one transfer per source', async () => {
    const sources: TransferSource[] = [
      { type: 'STOCK_ITEM', id: 's1', productCode: 'LK-200', available: 3, warehouseId: 'wh-1', aisle: 'A1', row: 'R1', bay: 'B1' },
      { type: 'STOCK_ITEM', id: 's2', productCode: 'LK-300', available: 4, warehouseId: 'wh-1', aisle: 'A2', row: 'R2', bay: 'B2' },
    ];
    let calls = 0;
    const base = { destWarehouseId: 'wh-1', destAisle: 'A9', destRow: 'R9', destBay: 'B9' };
    const mocks = [
      transferMock({ sourceType: 'STOCK_ITEM', sourceId: 's1', quantity: 3, ...base }, () => (calls += 1)),
      transferMock({ sourceType: 'STOCK_ITEM', sourceId: 's2', quantity: 4, ...base }, () => (calls += 1)),
    ];
    const { onSuccess } = renderDialog(sources, mocks);

    // Both source product codes appear in the per-source list.
    expect(screen.getByText('LK-200')).toBeInTheDocument();
    expect(screen.getByText('LK-300')).toBeInTheDocument();
    // No editable quantity in multi-source mode.
    expect(screen.queryByLabelText('Quantity')).not.toBeInTheDocument();

    setLocation('A9', 'R9', 'B9');
    fireEvent.click(screen.getByRole('button', { name: /^transfer$/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls).toBe(2);
  });
});
