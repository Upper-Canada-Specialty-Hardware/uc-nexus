import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { describe, it, expect, vi } from 'vitest';
import { ToastProvider } from '../../../components/Toast';
import TransferDialog, { type TransferSource } from '../TransferDialog';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import { GET_WAREHOUSE_LOCATIONS, TRANSFER_INVENTORY } from '../../../graphql/warehouse';

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
          company: 'TUBC',
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

// #1046: the destination is a strict pick from the destination warehouse's defined locations.
// C1-R1-B1 is defined only in another warehouse, so it never counts for wh-1.
const defined = (id: string, warehouseId: string, aisle: string, row: string, bay: string) => ({
  id,
  warehouseId,
  aisle,
  row,
  bay,
  active: true,
  createdAt: '2026-01-01T00:00:00Z',
  __typename: 'WarehouseLocation',
});
const registryMock: MockedResponse = {
  request: { query: GET_WAREHOUSE_LOCATIONS, variables: { activeOnly: true } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      warehouseLocations: [
        defined('l1', 'wh-1', 'A1', 'R1', 'B1'),
        defined('l2', 'wh-1', 'A9', 'R9', 'B9'),
        defined('l3', 'wh-2', 'C1', 'R1', 'B1'),
      ],
    },
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
    <MockedProvider mocks={[warehousesMock, registryMock, ...mocks]}>
      <ToastProvider>
        <TransferDialog sources={sources} onClose={onClose} onSuccess={onSuccess} />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSuccess };
}

function setLocation(aisle: string, row: string, bay: string) {
  fireEvent.change(screen.getByRole('combobox', { name: 'Aisle' }), { target: { value: aisle } });
  fireEvent.change(screen.getByRole('combobox', { name: 'Row' }), { target: { value: row } });
  fireEvent.change(screen.getByRole('combobox', { name: 'Bay' }), { target: { value: bay } });
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
    await waitFor(() => expect(screen.getByRole('button', { name: /^transfer$/i })).toBeEnabled());
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
    await waitFor(() => expect(screen.getByRole('button', { name: /^transfer$/i })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: /^transfer$/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls).toBe(2);
  });

  it('keeps Transfer off for a bin not defined in the destination warehouse', async () => {
    const source: TransferSource = {
      type: 'INVENTORY_LOCATION',
      id: 'inv-1',
      productCode: 'HG-100',
      available: 6,
      warehouseId: 'wh-1',
    };
    renderDialog([source], []);

    // Defined, but only in another warehouse.
    setLocation('C1', 'R1', 'B1');
    expect(await screen.findByText(/defined in the destination warehouse/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^transfer$/i })).toBeDisabled();

    // Never defined anywhere.
    setLocation('ZZ', 'R1', 'B1');
    expect(screen.getByRole('button', { name: /^transfer$/i })).toBeDisabled();

    setLocation('A1', 'R1', 'B1');
    await waitFor(() => expect(screen.getByRole('button', { name: /^transfer$/i })).toBeEnabled());
  });
});
