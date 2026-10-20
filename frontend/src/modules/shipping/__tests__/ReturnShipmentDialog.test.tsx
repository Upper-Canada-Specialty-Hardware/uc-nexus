import { render, screen, fireEvent, waitFor, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ReturnShipmentDialog from '../ReturnShipmentDialog';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import {
  CREATE_SHIPMENT_RETURN,
  GET_PROJECT_RACK_LOCATIONS,
  GET_RETURNABLE_LINES,
} from '../../../graphql/shipping';

vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 10_000 });

const INFINITE = Number.POSITIVE_INFINITY;

const linesMock: MockedResponse = {
  request: { query: GET_RETURNABLE_LINES, variables: { packingSlipId: 'ps-1' } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      returnableLines: [
        {
          __typename: 'ReturnableLine',
          packingSlipItemId: 'psi-a',
          openingNumber: null,
          productCode: 'HG-1',
          hardwareCategory: 'HINGE',
          shippedQuantity: 4,
          returnedQuantity: 0,
          returnableQuantity: 4,
        },
        {
          __typename: 'ReturnableLine',
          packingSlipItemId: 'psi-b',
          openingNumber: null,
          productCode: 'HG-2',
          hardwareCategory: 'HINGE',
          shippedQuantity: 3,
          returnedQuantity: 0,
          returnableQuantity: 3,
        },
      ],
    },
  },
};

const warehousesMock: MockedResponse = {
  request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
  maxUsageCount: INFINITE,
  result: {
    data: {
      warehouses: [
        {
          __typename: 'Warehouse',
          id: 'w-1',
          name: 'Coast Meridian',
          code: 'CM',
          company: 'TUBC',
          address: '1120 1725 Coast Meridian Road',
          city: 'Port Coquitlam',
          province: 'BC',
          postalCode: 'V3C 3T7',
          isPrimary: true,
          isActive: true,
          createdAt: '2026-01-01T00:00:00Z',
          updatedAt: '2026-01-01T00:00:00Z',
        },
      ],
    },
  },
};

describe('ReturnShipmentDialog', () => {
  it('says where the rest of a product sits, for a line going back to the project (#1731)', async () => {
    const racksMock: MockedResponse = {
      request: { query: GET_PROJECT_RACK_LOCATIONS, variables: { projectId: 'proj-1' } },
      maxUsageCount: INFINITE,
      result: {
        data: {
          projectRackLocations: [
            {
              __typename: 'ProductRackLocations',
              hardwareCategory: 'HINGE',
              productCode: 'HG-1',
              locations: [
                { __typename: 'RackLocation', warehouseCode: 'CM', aisle: 'A', row: '1', bay: '2', quantity: 6 },
              ],
            },
          ],
        },
      },
    };
    render(
      <MockedProvider mocks={[linesMock, warehousesMock, racksMock]}>
        <ToastProvider>
          <ReturnShipmentDialog
            slip={{ id: 'ps-1', packingSlipNumber: 'PS-0019', projectName: 'Cowichan District Hospital', projectId: 'proj-1' }}
            onClose={() => {}}
            onCompleted={() => {}}
          />
        </ToastProvider>
      </MockedProvider>,
    );

    expect(await screen.findByText('CM A-1-2 ×6')).toBeInTheDocument();
    // HG-2 has nowhere on the racks yet, so it says nothing rather than guessing.
    expect(screen.getAllByText(/Put it back with the rest at/)).toHaveLength(1);
  });

  it("names each line's disposition by its product, and the destination warehouse (#1547)", async () => {
    render(
      <MockedProvider mocks={[linesMock, warehousesMock]}>
        <ToastProvider>
          <ReturnShipmentDialog
            slip={{ id: 'ps-1', packingSlipNumber: 'PS-0019', projectName: 'Cowichan District Hospital' }}
            onClose={() => {}}
            onCompleted={() => {}}
          />
        </ToastProvider>
      </MockedProvider>,
    );

    await screen.findByText('HG-2');
    expect(screen.getByRole('combobox', { name: /^Disposition HG-1/ })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /^Disposition HG-2/ })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: /^Destination warehouse/ })).toBeInTheDocument();
  });

  it('refuses a quantity that is not a whole number instead of returning only the other lines (#1177)', async () => {
    const createReturn = vi.fn(() => ({ data: { createShipmentReturn: null } }));
    const createMock: MockedResponse = {
      request: { query: CREATE_SHIPMENT_RETURN, variables: () => true },
      result: createReturn,
    };
    const onCompleted = vi.fn();
    render(
      <MockedProvider mocks={[linesMock, warehousesMock, createMock]}>
        <ToastProvider>
          <ReturnShipmentDialog
            slip={{ id: 'ps-1', packingSlipNumber: 'PS-0019', projectName: 'Cowichan District Hospital' }}
            onClose={() => {}}
            onCompleted={onCompleted}
          />
        </ToastProvider>
      </MockedProvider>,
    );

    await screen.findByText('HG-2');
    const [qtyA, qtyB] = screen.getAllByLabelText('Qty');
    fireEvent.change(qtyA, { target: { value: '2' } });
    fireEvent.change(qtyB, { target: { value: '1.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record return' }));

    expect(await screen.findByText('HG-2: return quantity must be a whole number')).toBeInTheDocument();
    expect(createReturn).not.toHaveBeenCalled();
    expect(onCompleted).not.toHaveBeenCalled();
  });
});

// #1578: a failed read is not an empty shipment, and the full-return shortcut says what it will do.
describe('ReturnShipmentDialog honesty (#1578)', () => {
  const renderWith = (mocks: MockedResponse[], status?: string) =>
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <ReturnShipmentDialog
            slip={{ id: 'ps-1', packingSlipNumber: 'PS-0019', projectName: 'Cowichan District Hospital', status }}
            onClose={() => {}}
            onCompleted={() => {}}
          />
        </ToastProvider>
      </MockedProvider>,
    );

  it('says the returnable lines could not be read, with a retry, not "nothing left to return"', async () => {
    const failedLines: MockedResponse = {
      request: { query: GET_RETURNABLE_LINES, variables: { packingSlipId: 'ps-1' } },
      maxUsageCount: INFINITE,
      error: new TypeError('Failed to fetch'),
    };
    renderWith([failedLines, warehousesMock], 'PICKED_UP');

    expect(await screen.findByRole('button', { name: 'Retry' })).toBeInTheDocument();
    expect(screen.queryByText(/Nothing left to return/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record return' })).toBeDisabled();
  });

  it('names the full-return shortcut for what it does at each status', async () => {
    const { unmount } = renderWith([linesMock, warehousesMock], 'PICKED_UP');
    await screen.findByText('HG-2');
    expect(screen.getByRole('button', { name: 'Return everything' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cancel whole shipment' })).not.toBeInTheDocument();
    unmount();

    renderWith([linesMock, warehousesMock], 'SCHEDULED');
    await screen.findByText('HG-2');
    expect(screen.getByRole('button', { name: 'Cancel whole shipment' })).toBeInTheDocument();
  });
  it('sends the same key when the same return is sent again after a lost reply (#1552)', async () => {
    const keys: string[] = [];
    const record = (vars: Record<string, unknown>) =>
      keys.push((vars as { input: { idempotencyKey: string } }).input.idempotencyKey);
    const mocks: MockedResponse[] = [
      linesMock,
      warehousesMock,
      {
        request: { query: CREATE_SHIPMENT_RETURN, variables: (v) => (record(v), true) },
        error: new Error('Failed to fetch'),
      },
      {
        request: { query: CREATE_SHIPMENT_RETURN, variables: (v) => (record(v), true) },
        result: { data: { createShipmentReturn: null } },
      },
    ];
    render(
      <MockedProvider mocks={mocks}>
        <ToastProvider>
          <ReturnShipmentDialog
            slip={{ id: 'ps-1', packingSlipNumber: 'PS-0019', projectName: 'Cowichan District Hospital' }}
            onClose={() => {}}
            onCompleted={() => {}}
          />
        </ToastProvider>
      </MockedProvider>,
    );

    await screen.findByText('HG-2');
    fireEvent.change(screen.getAllByLabelText('Qty')[0], { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record return' }));
    await waitFor(() => expect(keys).toHaveLength(1));
    await screen.findByText(/Failed to fetch|network|connection/i);

    fireEvent.click(screen.getByRole('button', { name: 'Record return' }));
    await waitFor(() => expect(keys).toHaveLength(2));
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).toBe(keys[0]);
  });
});
