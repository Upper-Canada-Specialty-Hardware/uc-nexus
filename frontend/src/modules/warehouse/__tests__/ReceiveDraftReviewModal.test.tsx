import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveDraftReviewModal from '../ReceiveDraftReviewModal';
import {
  GET_PO_RECEIVING_DETAILS,
  APPROVE_RECEIVE_DRAFT,
  UPDATE_RECEIVE_DRAFT,
  REJECT_RECEIVE_DRAFT,
} from '../../../graphql/warehouse';
import { GET_WAREHOUSES, GET_RELAY_STATUS } from '../../../graphql/shared';
import type { ReceiveDraft } from '../receiveDraftTypes';

// Approving a drafted receive is where the GP-first pipeline lives now, so this file inherits the
// regime that used to be ReceiveModal's: the relay chip, the queued-outbox outcome, the GP receipt
// number, the eConnect error and the idempotency key that makes a retry safe. What is new is the
// two things only a reviewer can do - correct the count before approving, and send it back.

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

type ApproveVars = { input: { draftId: string; idempotencyKey: string } };
type UpdateVars = {
  input: {
    draftId: string;
    warehouseId: string | null;
    lineItems: {
      poLineItemId: string;
      quantityReceived: number;
      locations: { aisle: string; row: string; bay: string; quantity: number; deficientQuantity: number }[];
    }[];
  };
};

function draft(overrides: Partial<ReceiveDraft> = {}): ReceiveDraft {
  return {
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
    notes: null,
    totalQuantity: 2,
    createdAt: '2026-08-02T10:00:00Z',
    updatedAt: '2026-08-02T10:00:00Z',
    lineItems: [
      {
        id: 'dli-1',
        poLineItemId: 'li-1',
        hardwareCategory: 'Hinges',
        productCode: 'HG-100',
        quantityReceived: 2,
        locations: [{ aisle: 'A1', row: 'B2', bay: 'C3', quantity: 2, deficientQuantity: 0 }],
      },
    ],
    ...overrides,
  };
}

function relayMock(connected = true): MockedResponse {
  return {
    request: { query: GET_RELAY_STATUS },
    result: {
      data: {
        relayStatus: {
          __typename: 'RelayStatus',
          connected,
          company: connected ? 'UCSH' : null,
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

// Pending 3 on the drafted line, so a reviewer raising the count from 2 to 3 is legal and 4 is not.
function poDetailsMock(): MockedResponse {
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
          ],
          receiveRecords: [],
        },
      },
    },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function approveResult(queued: boolean, receiptNumber: string | null) {
  return {
    approveReceiveDraft: {
      __typename: 'ApproveReceiveDraftResult',
      queued,
      outboxEntryId: queued ? 'outbox-1' : null,
      draft: { ...draft(), __typename: 'ReceiveDraft', status: 'APPROVED' },
      receiveRecord: queued
        ? null
        : {
            __typename: 'ReceiveRecord',
            id: 'rr-1',
            poId: 'po-1',
            receivedAt: '2026-08-02T11:00:00Z',
            receivedBy: 'Wendy Warehouse',
            receiptNumber,
            batchNumber: null,
            createdAt: '2026-08-02T11:00:00Z',
            lineItems: [],
          },
    },
  };
}

function renderModal(extraMocks: MockedResponse[] = [], d: ReceiveDraft = draft(), relayUp = true) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[relayMock(relayUp), warehousesMock(), poDetailsMock(), ...extraMocks]}>
      <MemoryRouter>
        <ToastProvider>
          <ReceiveDraftReviewModal open draft={d} onClose={onClose} />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
  return { onClose };
}

const SLOW = { timeout: 5000 };

async function openModal(extraMocks: MockedResponse[] = [], d?: ReceiveDraft, relayUp = true) {
  const result = renderModal(extraMocks, d, relayUp);
  await screen.findByText('HG-100', undefined, SLOW);
  return result;
}

function approveButton() {
  return screen.getByRole('button', { name: 'Approve & Post to GP' });
}

async function approveViaConfirm() {
  fireEvent.click(await screen.findByRole('button', { name: 'Approve & Post to GP' }, SLOW));
  fireEvent.click(await screen.findByRole('button', { name: 'Approve' }, SLOW));
}

vi.setConfig({ testTimeout: 60_000 });

describe('ReceiveDraftReviewModal', () => {
  it('prefills the counted quantities and shows no rack rows to review', async () => {
    // #501: the reviewer is checking a count against a packing slip, not a put-away. Even a draft
    // that still carries rack rows from before the change renders none - they are not the
    // manager's decision any more, and the shelf is chosen on the Put Away queue after approval.
    await openModal();

    expect(screen.getByText(/Counted by/)).toHaveTextContent('Wendy Warehouse');
    expect(within(screen.getByRole('table')).getByRole('spinbutton')).toHaveValue(2);
    expect(screen.queryByLabelText('Aisle')).toBeNull();
    expect(screen.queryByLabelText('Bay')).toBeNull();
  });

  it('approves an unedited draft without saving it first', async () => {
    let updateCalls = 0;
    const updateMock: MockedResponse<Record<string, unknown>, UpdateVars> = {
      request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
      result: () => {
        updateCalls += 1;
        return { data: { updateReceiveDraft: { ...draft(), __typename: 'ReceiveDraft' } } };
      },
    };
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: { data: approveResult(false, 'RCT0000123') },
    };
    await openModal([updateMock, approveMock]);

    await approveViaConfirm();

    await screen.findByText(/Approved\. 2 items added to inventory/, undefined, SLOW);
    expect(updateCalls).toBe(0);
  });

  it('saves the reviewer edits before approving, so what posts is what is on screen', async () => {
    let captured: UpdateVars | null = null;
    const updateMock: MockedResponse<Record<string, unknown>, UpdateVars> = {
      request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: { updateReceiveDraft: { ...draft(), __typename: 'ReceiveDraft' } } };
      },
    };
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: { data: approveResult(false, 'RCT0000123') },
    };
    await openModal([updateMock, approveMock]);

    // The count was two; the reviewer makes it three, which is exactly the PO's pending quantity.
    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '3' } });
    await approveViaConfirm();

    await screen.findByText(/Approved\. 3 items added to inventory/, undefined, SLOW);
    expect(captured).toEqual({
      input: {
        draftId: 'draft-1',
        warehouseId: 'wh-1',
        lineItems: [
          {
            poLineItemId: 'li-1',
            quantityReceived: 3,
            locations: [],
          },
        ],
      },
    });
  });

  it('shows the GP receipt number, which is the only moment it is in front of anybody', async () => {
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: { data: approveResult(false, 'RCT0000123') },
    };
    await openModal([approveMock]);

    await approveViaConfirm();

    await screen.findByText('RCT0000123', undefined, SLOW);
    expect(await screen.findByRole('button', { name: 'Put Away Items' }, SLOW)).toBeInTheDocument();
  });

  it('sends a UUID idempotency key so a retry cannot post a second GP receipt', async () => {
    let captured: ApproveVars | null = null;
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: approveResult(false, 'RCT0000123') };
      },
    };
    await openModal([approveMock]);

    await approveViaConfirm();
    await screen.findByText(/Approved\./, undefined, SLOW);

    expect(captured!.input.draftId).toBe('draft-1');
    expect(captured!.input.idempotencyKey).toMatch(UUID_RE);
  });

  it('shows the queued outcome and claims no inventory when the relay is offline', async () => {
    // #353 PR E, moved: the receipt is on the durable outbox and posts itself. Nothing is booked
    // until it drains, so saying "added to inventory" here would be a lie.
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: { data: approveResult(true, null) },
    };
    await openModal([approveMock], draft(), false);

    await screen.findByText(/GP relay offline - approving will queue this receipt/, undefined, SLOW);
    expect(approveButton()).toBeEnabled(); // advisory, not a gate (#376)

    await approveViaConfirm();

    await screen.findByText(/Queued — the GP relay is offline/, undefined, SLOW);
    expect(screen.queryByText(/added to inventory/)).toBeNull();
    expect(screen.queryByRole('button', { name: 'Put Away Items' })).toBeNull();
  });

  it('keeps the modal open on a GP failure and shows the error detail', async () => {
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      error: new Error('eConnect rejected the receipt'),
    };
    const { onClose } = await openModal([approveMock]);

    await approveViaConfirm();

    await screen.findByText(/Approving this receive failed/, undefined, SLOW);
    expect(screen.getByText('eConnect rejected the receipt')).toBeInTheDocument();
    expect(screen.queryByText(/Approved\./)).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(await screen.findByRole('button', { name: 'Approve & Post to GP' }, SLOW)).toBeInTheDocument();
  });

  it('will not reject without a reason, and sends it back to the author with one', async () => {
    let captured: { input: { draftId: string; reason: string } } | null = null;
    const rejectMock: MockedResponse<Record<string, unknown>, { input: { draftId: string; reason: string } }> = {
      request: { query: REJECT_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: { rejectReceiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'REJECTED' } } };
      },
    };
    const { onClose } = await openModal([rejectMock]);

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    const dialogReject = await screen.findByRole('button', { name: 'Reject' }, SLOW);
    expect(dialogReject).toBeDisabled(); // no reason entered

    fireEvent.change(await screen.findByLabelText('Reason', undefined, SLOW), {
      target: { value: 'Count is two boxes short' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled(), SLOW);
    expect(captured).toEqual({ input: { draftId: 'draft-1', reason: 'Count is two boxes short' } });
  });

  it('resumes a parked approval with the key the draft is still claimed under', async () => {
    // An approval that died ambiguously - a dispatched disconnect, a timeout - leaves the draft
    // APPROVING and GP possibly holding the receipt. The key it was claimed under is the only route
    // back through the idempotency ledger, and it does not survive the browser tab that started it,
    // so the draft carries it.
    let captured: ApproveVars | null = null;
    const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        captured = vars;
        return { data: approveResult(false, 'RCT0000123') };
      },
    };
    await openModal([approveMock], draft({ status: 'APPROVING', approvalIdempotencyKey: 'held-key-1' }));

    await approveViaConfirm();
    await screen.findByText(/Approved\./, undefined, SLOW);

    expect(captured!.input.idempotencyKey).toBe('held-key-1');
  });

  it('does not re-send the edit on a retry, so the same-key approve is reachable', async () => {
    // The backend refuses to edit an APPROVING draft. A retry that still thought itself dirty would
    // fail on that refusal every time and never reach the approve that is the actual way out.
    let updateCalls = 0;
    const updateMock: MockedResponse<Record<string, unknown>, UpdateVars> = {
      request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
      maxUsageCount: Number.POSITIVE_INFINITY,
      result: () => {
        updateCalls += 1;
        return { data: { updateReceiveDraft: { ...draft(), __typename: 'ReceiveDraft' } } };
      },
    };
    const failThenPass: MockedResponse[] = [
      {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        error: new Error('relay disconnected'),
      },
      {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        result: { data: approveResult(false, 'RCT0000123') },
      },
    ];
    await openModal([updateMock, ...failThenPass]);

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '3' } });
    await approveViaConfirm();
    await screen.findByText(/Approving this receive failed/, undefined, SLOW);

    await approveViaConfirm();
    await screen.findByText(/Approved\./, undefined, SLOW);

    expect(updateCalls).toBe(1);
  });

  it('blocks approval when the reviewer raises the count past what the PO still owes', async () => {
    // The reviewer is deciding against what the PO owes NOW, which another receive may have moved
    // since the count was written - hence the live read this validates against.
    await openModal();

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '4' } });
    expect(screen.getByText('Max: 3')).toBeInTheDocument();
    expect(approveButton()).toBeDisabled();
  });

  describe('the counted-at timestamp (#474)', () => {
    // The backend serializes naive UTC with no zone suffix, and new Date() reads that as LOCAL -
    // this modal showed a 3:48 PM count as 7:48 PM while the approvals queue, which parses through
    // parseServerDate, showed it right. Forced behind UTC per the serverDate.test.ts pattern,
    // because on a UTC runner the buggy parse and the fixed one agree and the test proves nothing.
    const ORIGINAL_TZ = process.env.TZ;
    beforeAll(() => {
      process.env.TZ = 'America/Toronto';
    });
    afterAll(() => {
      process.env.TZ = ORIGINAL_TZ;
    });

    it('renders the zoneless server instant as UTC converted to local', async () => {
      // Not ceremony: if the forced zone stops taking effect, this fails rather than the test
      // silently passing against the bug. August, so the offset is EDT's 240.
      expect(new Date(2026, 7, 1).getTimezoneOffset()).toBe(240);

      await openModal([], draft({ createdAt: '2026-08-02T19:48:32' }));

      const expected = new Date('2026-08-02T19:48:32Z').toLocaleString();
      expect(screen.getByText(/Counted by/)).toHaveTextContent(`on ${expected}`);
    });
  });
});
