import { render, screen, fireEvent, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ReturnShipmentDialog from '../ReturnShipmentDialog';
import { GET_WAREHOUSES } from '../../../graphql/shared';
import { CREATE_SHIPMENT_RETURN, GET_RETURNABLE_LINES } from '../../../graphql/shipping';

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
