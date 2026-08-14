import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import LocationActionDialog, { type LocationActionTarget } from '../LocationActionDialog';
import {
  MOVE_INVENTORY_LOCATION,
  MARK_INVENTORY_UNLOCATED,
} from '../../../graphql/shared';
import {
  ADJUST_INVENTORY_QUANTITY,
  GET_LOCATION_DISTINCT_VALUES,
  MOVE_STOCK_LOCATION,
} from '../../../graphql/warehouse';

// Move mode now owns the distinct-values read (the aisle/row/bay option props are gone). Supplied to
// every render; adjust/unlocate skip the query so the mock simply goes unused there.
const distinctMock: MockedResponse = {
  request: { query: GET_LOCATION_DISTINCT_VALUES },
  result: {
    data: {
      locationDistinctValues: {
        aisles: ['A1', 'A2'],
        rows: ['C1'],
        bays: ['B1'],
        __typename: 'LocationDistinctValues',
      },
    },
  },
};

// DataGrid-heavy dialogs render slowly under jsdom, slower still when the whole suite runs in
// parallel - lift both the per-test budget and testing-library's 1s async-util default.
vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });


const invTarget: LocationActionTarget = {
  id: 'inv-1',
  kind: 'inventory',
  productCode: 'HG-100',
  quantity: 10,
  aisle: 'A1',
  row: 'C1',
  bay: 'B1',
};

const stockTarget: LocationActionTarget = {
  id: 'stock-1',
  kind: 'stock',
  productCode: 'LK-200',
  quantity: 4,
  aisle: null,
  row: null,
  bay: null,
};

function renderDialog(
  props: Partial<React.ComponentProps<typeof LocationActionDialog>> = {},
  mocks: MockedResponse[] = [],
) {
  const onClose = vi.fn();
  const onSuccess = vi.fn();
  render(
    <MockedProvider mocks={[distinctMock, ...mocks]}>
      <ToastProvider>
        <LocationActionDialog
          open
          onClose={onClose}
          onSuccess={onSuccess}
          mode="move"
          targets={[invTarget]}
          {...props}
        />
      </ToastProvider>
    </MockedProvider>,
  );
  return { onClose, onSuccess };
}

function confirmButton() {
  return screen.getByRole('button', { name: /confirm/i });
}

describe('LocationActionDialog', () => {
  it('move mode pre-fills the single target location and enables confirm', () => {
    renderDialog();
    expect(screen.getByLabelText('Aisle')).toHaveValue('A1');
    expect(screen.getByLabelText('Row')).toHaveValue('C1');
    expect(screen.getByLabelText('Bay')).toHaveValue('B1');
    expect(confirmButton()).toBeEnabled();
  });

  it('move mode disables confirm when a location field is cleared', () => {
    renderDialog();
    fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: '' } });
    expect(confirmButton()).toBeDisabled();
  });

  it('move on an inventory target fires MOVE_INVENTORY_LOCATION and reports success', async () => {
    let calledVariables: Record<string, unknown> | null = null;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: MOVE_INVENTORY_LOCATION,
          variables: { inventoryLocationId: 'inv-1', newAisle: 'A2', newRow: 'C1', newBay: 'B1' },
        },
        result: (vars) => {
          calledVariables = vars as Record<string, unknown>;
          return {
            data: {
              moveInventoryLocation: { id: 'inv-1', aisle: 'A2', row: 'C1', bay: 'B1', __typename: 'InventoryLocation' },
            },
          };
        },
      },
    ];
    const { onClose, onSuccess } = renderDialog({}, mocks);

    fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: 'A2' } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
    expect(calledVariables).toEqual({
      inventoryLocationId: 'inv-1',
      newAisle: 'A2',
      newRow: 'C1',
      newBay: 'B1',
    });
  });

  it('move on a stock target uses the MOVE_STOCK_LOCATION input shape', async () => {
    let called = false;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: MOVE_STOCK_LOCATION,
          variables: { input: { stockItemId: 'stock-1', newAisle: 'A1', newRow: 'C1', newBay: 'B1' } },
        },
        result: () => {
          called = true;
          return {
            data: { moveStockLocation: { id: 'stock-1', aisle: 'A1', row: 'C1', bay: 'B1', __typename: 'StockItem' } },
          };
        },
      },
    ];
    const { onSuccess } = renderDialog({ targets: [stockTarget] }, mocks);

    fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: 'A1' } });
    fireEvent.change(screen.getByLabelText('Row'), { target: { value: 'C1' } });
    fireEvent.change(screen.getByLabelText('Bay'), { target: { value: 'B1' } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(called).toBe(true);
  });

  it('adjust mode requires a non-zero adjustment and a reason', () => {
    renderDialog({ mode: 'adjust' });
    expect(confirmButton()).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '5' } });
    expect(confirmButton()).toBeDisabled(); // reason still missing

    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'recount' } });
    expect(confirmButton()).toBeEnabled();
  });

  it('adjust mode blocks a decrease below zero', () => {
    renderDialog({ mode: 'adjust' });
    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-11' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'damaged' } });
    expect(screen.getByText(/cannot go below 0/)).toBeInTheDocument();
    expect(confirmButton()).toBeDisabled();
  });

  it('adjust fires ADJUST_INVENTORY_QUANTITY with the delta and reason', async () => {
    let calledVariables: Record<string, unknown> | null = null;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_INVENTORY_QUANTITY,
          variables: { inventoryLocationId: 'inv-1', adjustment: -3, reason: 'damaged in transit' },
        },
        result: (vars) => {
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
    const { onSuccess } = renderDialog({ mode: 'adjust' }, mocks);

    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-3' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'damaged in transit' } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calledVariables).toEqual({
      inventoryLocationId: 'inv-1',
      adjustment: -3,
      reason: 'damaged in transit',
    });
  });

  it('unlocate mode warns and fires MARK_INVENTORY_UNLOCATED on confirm', async () => {
    let called = false;
    const mocks: MockedResponse[] = [
      {
        request: { query: MARK_INVENTORY_UNLOCATED, variables: { inventoryLocationId: 'inv-1' } },
        result: () => {
          called = true;
          return {
            data: { markInventoryUnlocated: { id: 'inv-1', aisle: null, row: null, bay: null, __typename: 'InventoryLocation' } },
          };
        },
      },
    ];
    const { onSuccess } = renderDialog({ mode: 'unlocate' }, mocks);

    expect(screen.getByText(/Clears aisle\/row\/bay/)).toBeInTheDocument();
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(called).toBe(true);
  });

  it('keeps the dialog open and reports the error when the mutation fails', async () => {
    const mocks: MockedResponse[] = [
      {
        request: { query: MARK_INVENTORY_UNLOCATED, variables: { inventoryLocationId: 'inv-1' } },
        error: new Error('boom'),
      },
    ];
    const { onSuccess, onClose } = renderDialog({ mode: 'unlocate' }, mocks);

    fireEvent.click(confirmButton());

    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
