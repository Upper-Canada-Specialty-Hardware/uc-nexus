import { render, screen, fireEvent, within, configure, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { DESTOCK_INVENTORY, GET_WAREHOUSE_LOCATIONS } from '../../../graphql/warehouse';
import { ToastProvider } from '../../../components/Toast';
import DestockInventoryModal, { type DestockSource } from '../stock/DestockInventoryModal';

// The modal renders inside a MUI Dialog; under the full parallel suite jsdom rendering is slow, so
// lift the per-test budget and testing-library's async-util default (mirrors LocationActionDialog).
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

const baseSource: DestockSource = {
  id: 'inv-1',
  warehouseId: 'w1',
  hardwareCategory: 'Hinges',
  productCode: 'HG-100',
  quantity: 10,
  deficientQuantity: 2,
  aisle: 'A1',
  row: 'R1',
  bay: 'B1',
};

// #1046: a target bin is a strict pick from the row's warehouse. C3-4-2 is defined in w1; D1-1-1 is
// defined only in w2, so it never counts here.
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
      warehouseLocations: [defined('l1', 'w1', 'C3', '4', '2'), defined('l2', 'w2', 'D1', '1', '1')],
    },
  },
};

function renderModal(source: Partial<DestockSource> = {}, mocks: MockedResponse[] = []) {
  render(
    <MockedProvider mocks={[registryMock, ...mocks]}>
      <ToastProvider>
        <DestockInventoryModal
          inventoryLocation={{ ...baseSource, ...source }}
          onClose={vi.fn()}
          onSuccess={vi.fn()}
        />
      </ToastProvider>
    </MockedProvider>,
  );
}

function destockButton() {
  return screen.getByRole('button', { name: 'Destock' });
}

function quantityInput() {
  return screen.getByLabelText(/Quantity/) as HTMLInputElement;
}

function pickCost(name: RegExp) {
  fireEvent.click(screen.getByRole('button', { name }));
}

async function openSourceSelect() {
  // The modal's only combobox is the Source select.
  fireEvent.mouseDown(screen.getByRole('combobox'));
  return screen.findByRole('listbox');
}

describe('DestockInventoryModal', () => {
  it('caps a non-deficient-swap at quantity minus deficient units', () => {
    renderModal(); // qty 10, deficient 2 -> max 8, source defaults to OVERAGE
    pickCost(/Keeps its cost/);
    expect(screen.getByLabelText(/Quantity \(max 8\)/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '9' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(quantityInput(), { target: { value: '8' } });
    expect(destockButton()).toBeEnabled();
  });

  it('caps a deficient swap at the deficient count', async () => {
    renderModal(); // qty 10, deficient 2
    const listbox = await openSourceSelect();
    fireEvent.click(within(listbox).getByText('Deficient swap'));
    pickCost(/Left behind/);

    expect(screen.getByLabelText(/Quantity \(max 2\)/)).toBeInTheDocument();

    fireEvent.change(quantityInput(), { target: { value: '3' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(quantityInput(), { target: { value: '2' } });
    expect(destockButton()).toBeEnabled();
  });

  it('requires a defined aisle/row/bay once the target override is on', async () => {
    renderModal();
    pickCost(/Keeps its cost/);
    expect(destockButton()).toBeEnabled(); // qty 1 within cap, no override

    fireEvent.click(screen.getByRole('button', { name: 'Override target location' }));
    expect(destockButton()).toBeDisabled(); // override on, fields blank

    fireEvent.change(screen.getByRole('combobox', { name: 'Aisle' }), { target: { value: 'C3' } });
    expect(destockButton()).toBeDisabled(); // partial override still blocked

    fireEvent.change(screen.getByRole('combobox', { name: 'Row' }), { target: { value: '4' } });
    expect(destockButton()).toBeDisabled();

    fireEvent.change(screen.getByRole('combobox', { name: 'Bay' }), { target: { value: '2' } });
    await waitFor(() => expect(destockButton()).toBeEnabled()); // a defined location in w1

    // Defined, but only in another warehouse - the server would refuse it, so the dialog does too.
    fireEvent.change(screen.getByRole('combobox', { name: 'Aisle' }), { target: { value: 'D1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Row' }), { target: { value: '1' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Bay' }), { target: { value: '1' } });
    expect(destockButton()).toBeDisabled();
    expect(screen.getByText(/defined on the Locations tab/)).toBeInTheDocument();
  });

  it('requires the cost choice, with neither option picked to start', () => {
    renderModal();
    const zero = screen.getByRole('button', { name: 'Left behind - $0 cost' });
    const keep = screen.getByRole('button', { name: 'Keeps its cost' });
    expect(screen.getByText('Cost in the pool')).toBeInTheDocument();
    expect(zero).toHaveAttribute('aria-pressed', 'false');
    expect(keep).toHaveAttribute('aria-pressed', 'false');
    expect(destockButton()).toBeDisabled(); // qty 1 is fine; only the cost is missing

    fireEvent.click(zero);
    expect(zero).toHaveAttribute('aria-pressed', 'true');
    expect(destockButton()).toBeEnabled();
  });

  it('sends the chosen cost with the destock', async () => {
    const onSuccess = vi.fn();
    const variables = {
      input: {
        inventoryLocationId: 'inv-1',
        quantity: 1,
        source: 'OVERAGE',
        destockCost: 'ZERO',
        reasonText: null,
        targetAisle: null,
        targetRow: null,
        targetBay: null,
      },
    };
    const result = vi.fn(() => ({
      data: {
        destockInventory: {
          __typename: 'StockItem',
          id: 'si-1',
          hardwareCategory: 'Hinges',
          productCode: 'HG-100',
          quantity: 1,
          deficientQuantity: 0,
          available: 1,
          aisle: 'A1',
          row: 'R1',
          bay: 'B1',
          receivedAt: '2026-09-30T00:00:00',
        },
      },
    }));
    render(
      <MockedProvider mocks={[{ request: { query: DESTOCK_INVENTORY, variables }, result }]}>
        <ToastProvider>
          <DestockInventoryModal inventoryLocation={baseSource} onClose={vi.fn()} onSuccess={onSuccess} />
        </ToastProvider>
      </MockedProvider>,
    );

    pickCost(/Left behind/);
    fireEvent.click(destockButton());

    await waitFor(() => expect(result).toHaveBeenCalled());
  });
});
