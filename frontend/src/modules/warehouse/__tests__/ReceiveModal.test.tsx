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
    result: {
      data: {
        relayStatus: {
          __typename: 'RelayStatus',
          connected: true,
          company: 'UCSH',
          build: null,
          installId: null,
        },
      },
    },
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

// #353 PR E: createReceive returns a wrapper. `queued` false is the online path - the receipt
// reached GP and the UC Nexus receive was persisted with it.
function createReceiveData(quantityReceived: number, receiptNumber: string | null = null) {
  return {
    createReceive: {
      __typename: 'CreateReceiveResult',
      queued: false,
      outboxEntryId: null,
      receiveRecord: {
        __typename: 'ReceiveRecord',
        id: 'rr-1',
        poId: 'po-1',
        receivedAt: '2026-07-16T10:00:00Z',
        receivedBy: 'Warehouse',
        receiptNumber,
        batchNumber: null,
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
    },
  };
}

// The relay reported as DOWN. Used to drive the real offline path rather than mocking past it: the
// queued outcome only ever happens when the relay is unreachable, so a test that reports it connected
// and just stubs a queued mutation result never touches the gate that decides whether a user can get
// there at all (#376).
function offlineRelayMock(): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    result: {
      data: {
        relayStatus: {
          __typename: 'RelayStatus',
          connected: false,
          company: null,
          build: null,
          installId: null,
        },
      },
    },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

// A second PO for the batch flows, with one line still owed so it contributes a Receive Now cell.
function secondPoDetailsMock(): MockedResponse {
  return {
    request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId: 'po-2' } },
    result: {
      data: {
        poReceivingDetails: {
          __typename: 'PurchaseOrder',
          id: 'po-2',
          poNumber: 'PO-456',
          requestNumber: 'RQ-78',
          gpCompany: 'UCSH',
          gpVendorId: 'GPV-1',
          vendorNameSnapshot: 'Acme Hardware',
          vendor: { __typename: 'Vendor', id: 'v-1', name: 'Acme Hardware', contactName: null },
          notes: null,
          status: 'ORDERED',
          lineItems: [
            {
              __typename: 'POLineItem',
              id: 'li-3',
              poId: 'po-2',
              hardwareCategory: 'Closers',
              productCode: 'CL-300',
              classification: null,
              orderedQuantity: 4,
              receivedQuantity: 0,
              unitCost: 40,
              orderAs: null,
              gpLineOrd: 1,
            },
          ],
          receiveRecords: [],
        },
      },
    },
  };
}

function renderModal(
  extraMocks: MockedResponse[] = [],
  relay: MockedResponse = relayMock(),
  poIds: string[] = ['po-1'],
) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[relay, warehousesMock(), ...extraMocks]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveModal open onClose={onClose} poIds={poIds} />
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

// render + wait for the PO grid and the relay-connected chip
async function openModal(extraMocks: MockedResponse[] = []) {
  const result = renderModal(extraMocks);
  await screen.findByText('HG-100', undefined, SLOW);
  await screen.findByText('GP relay connected', undefined, SLOW);
  return result;
}

// render + wait for the PO grid and the offline-relay warning
async function openModalRelayOffline(extraMocks: MockedResponse[] = []) {
  const result = renderModal(extraMocks, offlineRelayMock());
  await screen.findByText('HG-100', undefined, SLOW);
  await screen.findByText(/GP relay offline/, undefined, SLOW);
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

  it('keeps the GP receipt numbers of the POs that committed when a later one fails', async () => {
    // A batch commits PO by PO, and the numbers GP gave the ones that landed are real whatever
    // happens to the rest. They used to be published only in the all-green case, so a batch that
    // failed on its second PO showed the user an error and no way back to what had posted.
    const committed: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      result: { data: createReceiveData(3, 'RCT0000123') },
    };
    const failed: MockedResponse = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      error: new Error('GP receipt rejected'),
    };
    renderModal([poDetailsMock(), secondPoDetailsMock(), committed, failed], relayMock(), [
      'po-1',
      'po-2',
    ]);
    await screen.findByText('HG-100', undefined, SLOW);
    await screen.findByText('CL-300', undefined, SLOW);

    const [firstQty, secondQty] = screen.getAllByRole('grid').map((g) => within(g).getByRole('spinbutton'));
    fireEvent.change(firstQty, { target: { value: '3' } });
    fireEvent.change(secondQty, { target: { value: '4' } });
    fillLocation(0, 'A1', 'B2', 'C3');
    fillLocation(1, 'A2', 'B3', 'C4');
    await submitViaConfirm();

    await screen.findByText(/Receiving PO-456 failed/, undefined, SLOW);
    expect(screen.getByText('RCT0000123')).toBeInTheDocument();
    // Named, because half the batch is not in GP and "which PO is this the receipt for" is the
    // whole question.
    expect(screen.getByText('PO-123')).toBeInTheDocument();
    expect(screen.queryByText(/Receive completed successfully/)).toBeNull();
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

  it('shows the queued outcome and keeps the idempotency key when the GP relay is offline', async () => {
    // #353 PR E: an offline relay no longer fails the receive - it is accepted onto the outbox. The
    // key must NOT be cleared: the outbox row owns it, and reusing it is what makes a resubmit return
    // the same queued entry instead of queueing a second receipt.
    const keys: string[] = [];
    const queuedMock: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      maxUsageCount: 2,
      result: (vars) => {
        keys.push(vars.input.idempotencyKey);
        return {
          data: {
            createReceive: {
              __typename: 'CreateReceiveResult',
              queued: true,
              outboxEntryId: 'outbox-1',
              receiveRecord: null,
            },
          },
        };
      },
    };
    await openModal([poDetailsMock(), queuedMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    await submitViaConfirm();

    await screen.findByText(/Queued — the GP relay is offline/, undefined, SLOW);
    // Not an inventory claim: nothing has been persisted yet.
    expect(screen.queryByText(/items added to inventory/)).toBeNull();
    expect(keys).toHaveLength(1);
    expect(keys[0]).toMatch(UUID_RE);
  });

  it('lets a receive be submitted while the GP relay is offline, and queues it', async () => {
    // #376: the queued outcome above was unreachable in the running app. Complete Receive was disabled
    // on !relayConnected - exactly the condition that produces a queued receipt - so the outbox path,
    // its amber panel and this behaviour existed only under a mock. The relay state is advisory now:
    // a warehouse user who has counted the hardware can record it, and it posts itself later.
    const queuedMock: MockedResponse<Record<string, unknown>, CreateReceiveVars> = {
      request: { query: CREATE_RECEIVE, variables: () => true },
      result: {
        data: {
          createReceive: {
            __typename: 'CreateReceiveResult',
            queued: true,
            outboxEntryId: 'outbox-9',
            receiveRecord: null,
          },
        },
      },
    };
    await openModalRelayOffline([poDetailsMock(), queuedMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    expect(completeButton()).toBeEnabled(); // the gate that used to make this unreachable

    await submitViaConfirm();

    await screen.findByText(/Queued — the GP relay is offline/, undefined, SLOW);
    expect(screen.queryByText(/items added to inventory/)).toBeNull();
  });

  it('still blocks a receive on the things that are genuinely invalid while the relay is offline', async () => {
    // the relay going advisory must not weaken the real validation - an empty receive is still refused.
    await openModalRelayOffline([poDetailsMock()]);

    expect(completeButton()).toBeDisabled(); // nothing entered yet
    setReceiveQty('3');
    expect(completeButton()).toBeDisabled(); // put-away location still missing
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
