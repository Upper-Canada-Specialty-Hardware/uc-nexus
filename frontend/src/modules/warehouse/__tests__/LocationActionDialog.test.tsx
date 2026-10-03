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
  ADJUST_STOCK_QUANTITY,
  GET_PROJECT_INVENTORY_AVAILABILITY,
  GET_WAREHOUSE_LOCATIONS,
  MOVE_STOCK_LOCATION,
} from '../../../graphql/warehouse';

// #1124: whether the caller may record a count below what is reserved. Floor staff by default.
const identity = { roles: [] as string[] };
vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    ownsTenant: false,
    hasRole: (role: string) => identity.roles.includes(role),
  }),
}));
afterEach(() => {
  identity.roles = [];
});

// #975: move mode picks only from the defined-locations registry. Supplied to every render;
// adjust/unlocate skip the query so the mock simply goes unused there. A3-C1-B1 is defined in a
// different warehouse, so it is never offered for a w1 item.
const defined = (id: string, warehouseId: string, aisle: string) => ({
  id,
  warehouseId,
  aisle,
  row: 'C1',
  bay: 'B1',
  active: true,
  createdAt: '2026-01-01T00:00:00Z',
  __typename: 'WarehouseLocation',
});
const distinctMock: MockedResponse = {
  request: { query: GET_WAREHOUSE_LOCATIONS, variables: { activeOnly: true } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: {
    data: {
      warehouseLocations: [defined('l1', 'w1', 'A1'), defined('l2', 'w1', 'A2'), defined('l3', 'w2', 'A3')],
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
  warehouseId: 'w1',
  aisle: 'A1',
  row: 'C1',
  bay: 'B1',
};

const stockTarget: LocationActionTarget = {
  id: 'stock-1',
  kind: 'stock',
  productCode: 'LK-200',
  quantity: 4,
  warehouseId: 'w1',
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
  it('move mode pre-fills the single target location and enables confirm', async () => {
    renderDialog();
    expect(screen.getByLabelText('Aisle')).toHaveValue('A1');
    expect(screen.getByLabelText('Row')).toHaveValue('C1');
    expect(screen.getByLabelText('Bay')).toHaveValue('B1');
    await waitFor(() => expect(confirmButton()).toBeEnabled());
  });

  it('move mode refuses a location not defined for the item warehouse (#975)', async () => {
    renderDialog();
    await waitFor(() => expect(confirmButton()).toBeEnabled());

    // Never defined anywhere.
    fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: 'Z' } });
    expect(confirmButton()).toBeDisabled();
    // Defined, but in another warehouse.
    fireEvent.change(screen.getByLabelText('Aisle'), { target: { value: 'A3' } });
    expect(confirmButton()).toBeDisabled();
    expect(screen.getByText(/Pick a location defined for this warehouse/)).toBeInTheDocument();
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
    await waitFor(() => expect(confirmButton()).toBeEnabled());
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
    await waitFor(() => expect(confirmButton()).toBeEnabled());
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
    // #981: and says so where Confirm is decided, in the row's own numbers.
    expect(screen.getByTestId('adjust-blocked-reason')).toHaveTextContent(
      'Only 10 on this row - the most you can take off is 10.',
    );
  });

  it('says what a disabled adjust Confirm is waiting for (#981)', () => {
    renderDialog({ mode: 'adjust' });
    const why = () => screen.getByTestId('adjust-blocked-reason');

    expect(why()).toHaveTextContent('Enter how many to add (+) or take off (-).');
    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-3' } });
    expect(why()).toHaveTextContent('Give a reason for the adjustment.');
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'damaged' } });
    expect(screen.queryByTestId('adjust-blocked-reason')).not.toBeInTheDocument();
    expect(confirmButton()).toBeEnabled();
  });

  it('adjust fires ADJUST_INVENTORY_QUANTITY with the delta and reason', async () => {
    let calledVariables: Record<string, unknown> | null = null;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_INVENTORY_QUANTITY,
          variables: { inventoryLocationId: 'inv-1', adjustment: -3, reason: 'damaged in transit', expectedQuantity: 10 },
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
      expectedQuantity: 10,
    });
  });

  it('a pool adjust sends the count it was built from (#1316)', async () => {
    let calledVariables: Record<string, unknown> | null = null;
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_STOCK_QUANTITY,
          variables: { input: { stockItemId: 'stock-1', newQuantity: 2, reasonText: 'recount', expectedQuantity: 4 } },
        },
        result: (vars) => {
          calledVariables = vars as Record<string, unknown>;
          return {
            data: {
              adjustStockQuantity: {
                id: 'stock-1',
                hardwareCategory: 'LOCK',
                productCode: 'LK-200',
                quantity: 2,
                deficientQuantity: 0,
                available: 2,
                __typename: 'StockItem',
              },
            },
          };
        },
      },
    ];
    const { onSuccess } = renderDialog({ mode: 'adjust', targets: [stockTarget] }, mocks);

    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-2' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'recount' } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calledVariables).toEqual({
      input: { stockItemId: 'stock-1', newQuantity: 2, reasonText: 'recount', expectedQuantity: 4 },
    });
  });

  it('closes on a row-changed refusal instead of retrying from the stale count (#1316)', async () => {
    const message = 'This row changed from 4 to 1 since you opened it. Reload and try again.';
    const mocks: MockedResponse[] = [
      {
        request: {
          query: ADJUST_STOCK_QUANTITY,
          variables: { input: { stockItemId: 'stock-1', newQuantity: 2, reasonText: 'recount', expectedQuantity: 4 } },
        },
        result: { errors: [{ message, extensions: { code: 'CONFLICT', field: 'expected_quantity' } }] },
      },
    ];
    const { onSuccess, onClose } = renderDialog({ mode: 'adjust', targets: [stockTarget] }, mocks);

    fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-2' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'recount' } });
    fireEvent.click(confirmButton());

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(screen.getByText(message)).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('a multi-row unlocate that fails partway says how far it got and retries only the rest (#1317)', async () => {
    const second: LocationActionTarget = { ...invTarget, id: 'inv-2', productCode: 'HG-200' };
    const unlocated = (id: string) => ({
      data: { markInventoryUnlocated: { id, aisle: null, row: null, bay: null, __typename: 'InventoryLocation' } },
    });
    let firstCalls = 0;
    let secondCalls = 0;
    const mocks: MockedResponse[] = [
      {
        request: { query: MARK_INVENTORY_UNLOCATED, variables: { inventoryLocationId: 'inv-1' } },
        maxUsageCount: Number.POSITIVE_INFINITY,
        result: () => {
          firstCalls += 1;
          return unlocated('inv-1');
        },
      },
      {
        request: { query: MARK_INVENTORY_UNLOCATED, variables: { inventoryLocationId: 'inv-2' } },
        error: new Error('picked meanwhile'),
      },
      {
        request: { query: MARK_INVENTORY_UNLOCATED, variables: { inventoryLocationId: 'inv-2' } },
        result: () => {
          secondCalls += 1;
          return unlocated('inv-2');
        },
      },
    ];
    const { onSuccess, onClose } = renderDialog({ mode: 'unlocate', targets: [invTarget, second] }, mocks);

    fireEvent.click(confirmButton());

    await waitFor(() => expect(screen.getByText(/1 of 2 unlocated/)).toBeInTheDocument());
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    // The row that went through has dropped out; only the failed one is left to do.
    await waitFor(() => expect(screen.getAllByText(/qty 10 — at/)).toHaveLength(1));
    expect(screen.getAllByText(/qty 10 — at/)[0]).toHaveTextContent('HG-200');

    fireEvent.click(confirmButton());

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(firstCalls).toBe(1);
    expect(secondCalls).toBe(1);
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

  describe('a count below what is reserved (#1124)', () => {
    // 10 on hand of HG-100 in p1, 4 of them reserved: taking 8 off leaves 2 under the claim.
    const reservedTarget: LocationActionTarget = {
      ...invTarget,
      projectId: 'p1',
      hardwareCategory: 'HINGE',
    };
    const availabilityMock: MockedResponse = {
      request: { query: GET_PROJECT_INVENTORY_AVAILABILITY, variables: { projectId: 'p1' } },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: {
        data: {
          projectInventoryAvailability: [
            {
              hardwareCategory: 'HINGE',
              productCode: 'HG-100',
              onHandQuantity: 10,
              deficientQuantity: 0,
              reservedQuantity: 4,
              availableQuantity: 6,
              classification: null,
              __typename: 'ProjectInventoryAvailability',
            },
          ],
        },
      },
    };

    function enterShortCount() {
      fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-8' } });
      fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'counted short' } });
    }

    it('is refused to floor staff, saying who can record it', async () => {
      renderDialog({ mode: 'adjust', targets: [reservedTarget] }, [availabilityMock]);
      enterShortCount();

      await waitFor(() =>
        expect(screen.getByRole('alert')).toHaveTextContent('below the 4 unit(s) reserved by active requests'),
      );
      expect(screen.getByRole('alert')).toHaveTextContent(
        'Only a Warehouse Manager can record a count below what is reserved.',
      );
      expect(screen.queryByRole('checkbox')).toBeNull();
      expect(confirmButton()).toBeDisabled();
    });

    it('lets a Warehouse Manager record it once confirmed, and says so to the server', async () => {
      identity.roles = ['Warehouse Manager'];
      let calledVariables: Record<string, unknown> | null = null;
      const adjustMock: MockedResponse = {
        request: {
          query: ADJUST_INVENTORY_QUANTITY,
          variables: {
            inventoryLocationId: 'inv-1',
            adjustment: -8,
            reason: 'counted short',
            expectedQuantity: 10,
            confirmBelowReserved: true,
          },
        },
        result: (vars) => {
          calledVariables = vars as Record<string, unknown>;
          return {
            data: {
              adjustInventoryQuantity: {
                id: 'inv-1',
                quantity: 2,
                deficientQuantity: 0,
                available: 2,
                __typename: 'InventoryLocation',
              },
            },
          };
        },
      };
      const { onSuccess } = renderDialog({ mode: 'adjust', targets: [reservedTarget] }, [availabilityMock, adjustMock]);
      enterShortCount();

      const confirmBox = await screen.findByRole('checkbox', { name: /record it anyway/i });
      expect(confirmButton()).toBeDisabled();
      fireEvent.click(confirmBox);
      await waitFor(() => expect(confirmButton()).toBeEnabled());
      fireEvent.click(confirmButton());

      await waitFor(() => expect(onSuccess).toHaveBeenCalled());
      expect(calledVariables).toMatchObject({ confirmBelowReserved: true });
    });

    it('does not gate a decrease that stays within the free stock', async () => {
      renderDialog({ mode: 'adjust', targets: [reservedTarget] }, [availabilityMock]);
      fireEvent.change(screen.getByLabelText('Adjustment (+/-)'), { target: { value: '-6' } });
      fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'counted short' } });

      await waitFor(() => expect(screen.getByText('4 unit(s) reserved by active requests.')).toBeInTheDocument());
      expect(screen.queryByRole('alert')).toBeNull();
      expect(confirmButton()).toBeEnabled();
    });
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
