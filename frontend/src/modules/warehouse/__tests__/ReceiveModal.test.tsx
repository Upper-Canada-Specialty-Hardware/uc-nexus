import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveModal from '../ReceiveModal';
import { GET_PO_RECEIVING_DETAILS, CREATE_RECEIVE_DRAFT } from '../../../graphql/warehouse';
import { GET_WAREHOUSES } from '../../../graphql/shared';

// This dialog counts a delivery in. It used to post the GP receipt too, and everything about that
// round trip - the relay chip, the queued-outbox panel, the GP receipt number, the eConnect error -
// moved to the approval, so those assertions now live in ReceiveDraftReviewModal.test.tsx. What is
// left here is the data entry and the one output it has: a draft was submitted.

// variables shape the component sends on CreateReceiveDraft (type alias, not interface, so it
// satisfies Apollo's OperationVariables constraint)
type CreateDraftVars = {
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

function draftResultData() {
  return {
    createReceiveDraft: {
      __typename: 'ReceiveDraft',
      id: 'draft-1',
      status: 'PENDING_APPROVAL',
      poId: 'po-1',
      poNumber: 'PO-123',
      projectId: 'proj-1',
      warehouseId: 'wh-1',
      createdByUserId: 'u_author',
      createdBy: 'Wendy Warehouse',
      reviewedBy: null,
      reviewedAt: null,
      rejectionReason: null,
    approvalIdempotencyKey: null,
      receiveRecordId: null,
      outboxEntryId: null,
      totalQuantity: 2,
      createdAt: '2026-08-02T10:00:00Z',
      updatedAt: '2026-08-02T10:00:00Z',
      lineItems: [],
    },
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
  poIds: string[] = ['po-1'],
  pendingDraftsByPoId?: Map<string, { id: string; totalQuantity: number }[]>,
) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[warehousesMock(), ...extraMocks]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveModal
            open
            onClose={onClose}
            poIds={poIds}
            pendingDraftsByPoId={pendingDraftsByPoId}
          />
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

// render + wait for the PO grid
async function openModal(extraMocks: MockedResponse[] = []) {
  const result = renderModal(extraMocks);
  await screen.findByText('HG-100', undefined, SLOW);
  return result;
}

// the Receive Now cell input is the only spinbutton inside the grid (the fully received
// line renders text, and the put-away Qty/Deficient inputs live outside the grid)
function receiveNowInput() {
  return within(screen.getByRole('grid')).getByRole('spinbutton');
}

function submitButton() {
  return screen.getByRole('button', { name: 'Submit for Approval' });
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
  fireEvent.click(await screen.findByRole('button', { name: 'Submit for Approval' }, SLOW));
  fireEvent.click(await screen.findByRole('button', { name: 'Submit' }, SLOW));
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

    expect(submitButton()).toBeDisabled();
  });

  it('says nothing about the GP relay, because drafting never touches it', async () => {
    // The relay chip and its offline warning moved to the approval. Leaving them here would tell a
    // warehouse user that whether they can write down what arrived depends on GP being up.
    await openModal([poDetailsMock()]);

    expect(screen.queryByText(/GP relay/)).toBeNull();
    expect(screen.queryByText(/queued/i)).toBeNull();
  });

  it('enables submit only after a quantity is entered and every unit is placed in a row', async () => {
    await openModal([poDetailsMock()]);

    expect(submitButton()).toBeDisabled();

    setReceiveQty('3');
    expect(screen.getByText(/placing 3/)).toBeInTheDocument();
    // row fields still blank, so put-away is incomplete
    expect(submitButton()).toBeDisabled();

    fillLocation(0, 'A1', 'B2', 'C3');
    expect(screen.getByText('all placed')).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it('blocks receiving more than the pending quantity', async () => {
    await openModal([poDetailsMock()]);

    setReceiveQty('5'); // pending is only 3
    expect(screen.getByText('Max: 3')).toBeInTheDocument();
    fillLocation(0, 'A1', 'B2', 'C3'); // put-away itself is valid at 5 placed
    expect(submitButton()).toBeDisabled();

    // dropping back within pending (and matching the row qty) makes it submittable
    setReceiveQty('3');
    fireEvent.change(screen.getByLabelText('Qty'), { target: { value: '3' } });
    expect(screen.queryByText('Max: 3')).toBeNull();
    expect(submitButton()).toBeEnabled();
  });

  it('requires the row split to sum to the received quantity', async () => {
    await openModal([poDetailsMock()]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3', '2');
    expect(screen.getByText('1 unplaced')).toBeInTheDocument();
    expect(submitButton()).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /add location/i }));
    fillLocation(1, 'A2', 'B2', 'C4', '1');
    expect(screen.getByText('all placed')).toBeInTheDocument();
    expect(submitButton()).toBeEnabled();
  });

  it('fires CREATE_RECEIVE_DRAFT with the receive input shape and shows the submitted state', async () => {
    // The input shape is unchanged from when this posted straight to GP - the same counted lines and
    // rack rows, now recorded rather than posted - so the assertion is the same one it always was.
    let captured: CreateDraftVars | null = null;
    const draftMock: MockedResponse<Record<string, unknown>, CreateDraftVars> = {
      request: { query: CREATE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: draftResultData() };
      },
    };
    const { onClose } = await openModal([poDetailsMock(), draftMock]);
    await screen.findByText(/Main \(MAIN\)/, undefined, SLOW); // default warehouse selected

    setReceiveQty('2');
    fillLocation(0, 'A1', 'B2', 'C3'); // row qty defaults to the received 2
    fireEvent.change(screen.getByLabelText('Deficient'), { target: { value: '1' } });
    await submitViaConfirm();

    await screen.findByText(/Submitted for approval\. 2 items across 1 PO/, undefined, SLOW);
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
    // Nothing is in inventory and GP has numbered nothing, so neither may be claimed.
    expect(screen.queryByText(/added to inventory/)).toBeNull();
    expect(screen.queryByText(/GP Receipt/)).toBeNull();
    expect(await screen.findByRole('button', { name: 'View My Drafts' }, SLOW)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('keeps the modal open and surfaces the error when the mutation fails', async () => {
    const draftMock: MockedResponse = {
      request: { query: CREATE_RECEIVE_DRAFT, variables: () => true },
      error: new Error('draft rejected'),
    };
    const { onClose } = await openModal([poDetailsMock(), draftMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    await submitViaConfirm();

    await screen.findByText(/Submitting PO-123 failed/, undefined, SLOW);
    expect(screen.queryByText(/Submitted for approval/)).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    // still on the editing actions, so the user can retry
    expect(await screen.findByRole('button', { name: 'Submit for Approval' }, SLOW)).toBeInTheDocument();
  });

  it('reuses the same idempotency key when retrying a failed PO', async () => {
    // A retry after a timeout that actually committed must not leave two counts of one delivery in
    // the approval queue.
    const keys: string[] = [];
    const failMock: MockedResponse<Record<string, unknown>, CreateDraftVars> = {
      request: {
        query: CREATE_RECEIVE_DRAFT,
        variables: (vars) => {
          keys.push(vars.input.idempotencyKey);
          return true;
        },
      },
      error: new Error('network blip'),
    };
    const successMock: MockedResponse<Record<string, unknown>, CreateDraftVars> = {
      request: { query: CREATE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        keys.push(vars.input.idempotencyKey);
        return { data: draftResultData() };
      },
    };
    await openModal([poDetailsMock(), failMock, successMock]);

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    await submitViaConfirm();
    await screen.findByText(/Submitting PO-123 failed/, undefined, SLOW);

    await submitViaConfirm();
    await screen.findByText(/Submitted for approval\. 3 items/, undefined, SLOW);

    expect(keys).toHaveLength(2);
    expect(keys[0]).toMatch(UUID_RE);
    expect(keys[1]).toBe(keys[0]);
  });

  it('warns without blocking when a PO already has a draft awaiting approval', async () => {
    // Two deliveries against one PO is ordinary; re-counting the same one is not. The backend's
    // approval claim is the enforcement point, so this only has to be visible.
    const pending = new Map([['po-1', [{ id: 'draft-9', totalQuantity: 2 }]]]);
    renderModal([poDetailsMock()], ['po-1'], pending);
    await screen.findByText('HG-100', undefined, SLOW);

    expect(screen.getByText(/already has a receive awaiting approval \(2 units\)/)).toBeInTheDocument();

    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    expect(submitButton()).toBeEnabled();
  });

  it('blocks receiving a PO that is not GP-registered', async () => {
    // Still a hard block, unlike the GP-job quarantine: such a draft could never be approved at all,
    // and pushing the PO to GP is a different user's job.
    await openModal([poDetailsMock({ gpCompany: null })]);

    expect(screen.getByText(/isn't registered in GP yet/)).toBeInTheDocument();

    // even a fully valid receive stays blocked
    setReceiveQty('3');
    fillLocation(0, 'A1', 'B2', 'C3');
    expect(submitButton()).toBeDisabled();
  });

  it('counts a multi-PO batch into one draft per PO', async () => {
    const seen: string[] = [];
    const draftMock: MockedResponse<Record<string, unknown>, CreateDraftVars> = {
      request: { query: CREATE_RECEIVE_DRAFT, variables: () => true },
      maxUsageCount: 2,
      result: (vars) => {
        seen.push(vars.input.poId);
        return { data: draftResultData() };
      },
    };
    renderModal([poDetailsMock(), secondPoDetailsMock(), draftMock], ['po-1', 'po-2']);
    await screen.findByText('HG-100', undefined, SLOW);
    await screen.findByText('CL-300', undefined, SLOW);

    const [firstQty, secondQty] = screen.getAllByRole('grid').map((g) => within(g).getByRole('spinbutton'));
    fireEvent.change(firstQty, { target: { value: '3' } });
    fireEvent.change(secondQty, { target: { value: '4' } });
    fillLocation(0, 'A1', 'B2', 'C3');
    fillLocation(1, 'A2', 'B3', 'C4');
    await submitViaConfirm();

    await screen.findByText(/Submitted for approval\. 7 items across 2 POs/, undefined, SLOW);
    expect(seen).toEqual(['po-1', 'po-2']);
  });
});
