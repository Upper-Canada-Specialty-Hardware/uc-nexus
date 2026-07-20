import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveModal from '../ReceiveModal';
import { GET_PO_RECEIVING_DETAILS, CREATE_RECEIVE } from '../../../graphql/warehouse';
import { GET_WAREHOUSES, GET_RELAY_STATUS } from '../../../graphql/shared';

// variables shape the component sends on CreateReceive (type alias, not interface, so it
// satisfies Apollo's OperationVariables constraint)
type CreateReceiveVars = {
  input: {
    poId: string;
    warehouseId: string | null;
    idempotencyKey: string;
    lineItems: {
      poLineItemId: string;
      quantityReceived: number;
      locations: { aisle: string; row: string; bay: string; quantity: number; deficientQuantity: number }[];
    }[];
  };
};

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

function relayMock(): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    result: { data: { relayStatus: { __typename: 'RelayStatus', connected: true, company: 'UCSH' } } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function warehousesMock(): MockedResponse {
  return {
    request: { query: GET_WAREHOUSES, variables: { includeInactive: false } },
    result: {
      data: {
        warehouses: [
          {
            __typename: 'Warehouse',
            id: 'wh-1',
            name: 'Main',
            code: 'MAIN',
            address: null,
            city: null,
            province: null,
            postalCode: null,
            isPrimary: true,
            isActive: true,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
          },
        ],
      },
    },
  };
}

// PO with one partially received line (pending 3) and one fully received line
function poDetailsMock(overrides: Record<string, unknown> = {}): MockedResponse {
  return {
    request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId: 'po-1' } },
    result: {
      data: {
        poReceivingDetails: {
          __typename: 'PurchaseOrder',
          id: 'po-1',
          poNumber: 'PO-123',
          requestNumber: 'RQ-77',
          gpCompany: 'UCSH',
          gpVendorId: 'GPV-1',
          vendorNameSnapshot: 'Acme Hardware',
          vendor: { __typename: 'Vendor', id: 'v-1', name: 'Acme Hardware', contactName: null },
          notes: null,
          status: 'ORDERED',
          lineItems: [
            {
              __typename: 'POLineItem',
              id: 'li-1',
              poId: 'po-1',
              hardwareCategory: 'Hinges',
              productCode: 'HG-100',
              classification: null,
              orderedQuantity: 10,
              receivedQuantity: 7,
              unitCost: 2.5,
              orderAs: null,
              gpLineOrd: 1,
            },
            {
              __typename: 'POLineItem',
              id: 'li-2',
              poId: 'po-1',
              hardwareCategory: 'Locksets',
              productCode: 'LK-200',
              classification: null,
              orderedQuantity: 5,
              receivedQuantity: 5,
              unitCost: 10,
              orderAs: null,
              gpLineOrd: 2,
            },
          ],
          receiveRecords: [],
          ...overrides,
        },
      },
    },
  };
}

function createReceiveData(quantityReceived: number) {
  return {
    createReceive: {
      __typename: 'ReceiveRecord',
      id: 'rr-1',
      poId: 'po-1',
      receivedAt: '2026-07-16T10:00:00Z',
      receivedBy: 'Warehouse',
      createdAt: '2026-07-16T10:00:00Z',
      lineItems: [
        {
          __typename: 'ReceiveLineItem',
          id: 'rli-1',
          receiveRecordId: 'rr-1',
          poLineItemId: 'li-1',
          hardwareCategory: 'Hinges',
          productCode: 'HG-100',
          quantityReceived,
          createdAt: '2026-07-16T10:00:00Z',
        },
      ],
    },
  };
}

function renderModal(extraMocks: MockedResponse[] = []) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[relayMock(), warehousesMock(), ...extraMocks]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveModal open onClose={onClose} poIds={['po-1']} />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
  return { onClose };
}

// long timeout: jsdom + the DataGrid make renders slow, and right after a submit the confirm
// dialog's exit transition still has the main modal aria-hidden, hiding its buttons from role
// queries until the transition finishes
const SLOW = { timeout: 5000 };

// render + wait for the PO grid and the relay-connected chip (submit is gated on the relay)
async function openModal(extraMocks: MockedResponse[] = []) {
  const result = renderModal(extraMocks);
  await screen.findByText('HG-100', undefined, SLOW);
  await screen.findByText('GP relay connected', undefined, SLOW);
  return result;
}

// the Receive Now cell input is the only spinbutton inside the grid (the fully received
// line renders text, and the put-away Qty/Deficient inputs live outside the grid)
function receiveNowInput() {
  return within(screen.getByRole('grid')).getByRole('spinbutton');
}

function completeButton() {
  return screen.getByRole('button', { name: 'Complete Receive' });
}

function setReceiveQty(value: string) {
  fireEvent.change(receiveNowInput(), { target: { value } });
}

function fillLocation(idx: number, aisle: string, row: string, bay: string, qty?: string) {
  fireEvent.change(screen.getAllByLabelText('Aisle')[idx], { target: { value: aisle } });
  fireEvent.change(screen.getAllByLabelText('Row')[idx], { target: { value: row } });
  fireEvent.change(screen.getAllByLabelText('Bay')[idx], { target: { value: bay } });
  if (qty !== undefined) {
    fireEvent.change(screen.getAllByLabelText('Qty')[idx], { target: { value: qty } });
  }
}

async function submitViaConfirm() {
  fireEvent.click(await screen.findByRole('button', { name: 'Complete Receive' }, SLOW));
  fireEvent.click(await screen.findByRole('button', { name: 'Receive' }, SLOW));
}

// DataGrid renders are slow under jsdom, and slower still when the whole suite runs in parallel -
// the default 5s per-test budget flakes on the multi-interaction flows.
vi.setConfig({ testTimeout: 60_000 });

describe('ReceiveModal', () => {
  it('renders line items with pending quantities and starts with submit disabled', async () => {
    await openModal([poDetailsMock()]);

    expect(screen.getByText(/PO-123/)).toBeInTheDocument();

    const pendingRow = screen.getByText('HG-100').closest('[role="row"]') as HTMLElement;
    expect(within(pendingRow).getByText('10')).toBeInTheDocument(); // ordered
    expect(within(pendingRow).getByText('7')).toBeInTheDocument(); // already received
    expect(within(pendingRow).getByText('3')).toBeInTheDocument(); // pending
    expect(within(pendingRow).getByRole('spinbutton')).toHaveValue(0);

    const fullRow = screen.getByText('LK-200').closest('[role="row"]') as HTMLElement;
    expect(within(fullRow).getByText('Fully Received')).toBeInTheDocument();
    expect(within(fullRow).queryByRole('spinbutton')).toBeNull();

    expect(completeButton()).toBeDisabled();
  });

  it('enables submit only after a quantity is entered and every unit is placed in a row', async () => {
    await openModal([poDetailsMock()]);

    expect(completeButton()).toBeDisabled();

    setReceiveQty('3');
    expect(screen.getByText(/placing 3/)).toBeInTheDocument();
    // row fields still blank, so put-away is incomplete
    expect(completeButton()).toBeDisabled();

    fillLocation(0, 'A1', 'B2', 'C3');
    expect(screen.getByText('all placed')).toBeInTheDocument();
    expect(completeButton()).toBeEnabled();
  });

  it('blocks receiving more than the pending quantity', async () => {
    await openModal([poDetailsMock()]);

    setReceiveQty('5'); // pending is only 3
    expect(screen.getByText('Max: 3')).toBeInTheDocument();
    fillLocation(0, 'A1', 'B2', 'C3'); // put-away itself is valid at 5 placed
    expect(completeButton()).toBeDisabled();

    // dropping back within pending (and matching the row qty) makes it submittable
    setReceiveQty('3');
    fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '3' } });
    expect(screen.queryByText('Max: 3')).toBeNull();
    expect(completeButton()).toBeEnabled();
  });

  it('requires the row split to sum to the received quantity', async () => {
    await openModal([poDetailsMock()]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3', '2');
    expect(screen.getByText('1 unplaced')).toBeInTheDocument();
    expect(completeButton()).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /add location/i }));
    fillLocation(1, 'A2', 'B2', 'C4', '1');
    expect(screen.getByText('all placed')).toBeInTheDocument();
    expect(completeButton()).toBeEnabled();
  });

  it('fires CREATE_RECEIVE with the receive input shape and shows the success state', async () => {
    let captured: CreateReceiveVars | null = null;
    const receiveMock: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: createReceiveData(2) };
      },
    };
    const { onClose } = await openModal([poDetailsMock(), receiveMock]);
    await screen.findByText(/Main \(MAIN\)/, undefined, SLOW); // default warehouse selected

    setReceiveQty('2');
    fillLocation(0, 'A1', 'B2', 'C3'); // row qty defaults to the received 2
    fireEvent.change(screen.getByLabelText('Deficient'), { target: { value: '1' } });
    await submitViaConfirm();

    await screen.findByText(/Receive completed successfully! 2 items added to inventory/, undefined, SLOW);
    expect(captured).toEqual({
      input: {
        poId: 'po-1',
        warehouseId: 'wh-1',
        idempotencyKey: expect.stringMatching(UUID_RE),
        lineItems: [
          {
            poLineItemId: 'li-1',
            quantityReceived: 2,
            locations: [{ aisle: 'A1', row: 'B2', bay: 'C3', quantity: 2, deficientQuantity: 1 }],
          },
        ],
      },
    });
    expect(await screen.findByRole('button', { name: 'Put Away Items' }, SLOW)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps the modal open and surfaces the error when the mutation fails', async () => {
    const receiveMock: MockedResponse = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      error: new Error('GP receipt rejected'),
    };
    const { onClose } = await openModal([poDetailsMock(), receiveMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    await submitViaConfirm();

    await screen.findByText(/Receiving PO-123 failed - see the GP error detail below/, undefined, SLOW);
    expect(screen.getByText('GP could not complete the receipt')).toBeInTheDocument();
    expect(screen.getByText('GP receipt rejected')).toBeInTheDocument();
    expect(screen.queryByText(/Receive completed successfully/)).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    // still on the editing actions, so the user can retry
    expect(await screen.findByRole('button', { name: 'Complete Receive' }, SLOW)).toBeInTheDocument();
  });

  it('reuses the same idempotency key when retrying a failed PO', async () => {
    const keys: string[] = [];
    const failMock: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: {
        query: CREATE_RECEIVE,
        variables: (vars) => {
          keys.push(vars.input.idempotencyKey);
          return true;
        },
      },
      error: new Error('gp temporarily down'),
    };
    const successMock: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      result: (vars) => {
        keys.push(vars.input.idempotencyKey);
        return { data: createReceiveData(3) };
      },
    };
    await openModal([poDetailsMock(), failMock, successMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    await submitViaConfirm();
    await screen.findByText(/Receiving PO-123 failed/, undefined, SLOW);

    await submitViaConfirm();
    await screen.findByText(/Receive completed successfully! 3 items added to inventory/, undefined, SLOW);

    expect(keys).toHaveLength(2);
    expect(keys[0]).toMatch(UUID_RE);
    expect(keys[1]).toBe(keys[0]);
  });

  it('blocks receiving a PO that is not GP-registered', async () => {
    await openModal([poDetailsMock({ gpCompany: null })]);

    expect(screen.getByText(/isn't registered in GP yet/)).toBeInTheDocument();

    // even a fully valid receive stays blocked
    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    expect(completeButton()).toBeDisabled();
  });
});
