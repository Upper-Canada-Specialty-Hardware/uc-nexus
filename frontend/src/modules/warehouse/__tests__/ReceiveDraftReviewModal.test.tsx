import { render, screen, fireEvent, within } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ReceiveDraftReviewModal from '../ReceiveDraftReviewModal';
import {
  GET_PO_RECEIVING_DETAILS,
  GET_RECEIVE_DRAFT,
  APPROVE_RECEIVE_DRAFT,
  UPDATE_RECEIVE_DRAFT,
  REJECT_RECEIVE_DRAFT,
  RELEASE_HELD_RECEIVE_APPROVAL,
} from '../../../graphql/warehouse';
import { GET_WAREHOUSES, GET_RELAY_STATUS } from '../../../graphql/shared';
import { GraphQLError } from 'graphql';
import type { ReceiveDraft } from '../receiveDraftTypes';

// Approving a drafted receive is where the GP-first pipeline lives now, so this file inherits the
// regime that used to be ReceiveModal's: the relay chip, the queued-outbox outcome, the GP receipt
// number, the eConnect error and the idempotency key that makes a retry safe. What is new is the
// two things only a reviewer can do - correct the count before approving, and send it back.

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

type ApproveVars = { input: { draftId: string; idempotencyKey: string; expectedUpdatedAt?: string } };
type UpdateVars = {
  input: {
    draftId: string;
    warehouseId: string | null;
    expectedUpdatedAt?: string;
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
    projectNumber: null,
    projectDescription: null,
    poolKind: 'STOCK',
    warehouseId: 'wh-1',
    createdByUserId: 'u_author',
    createdBy: 'Wendy Warehouse',
    reviewedBy: null,
    reviewedAt: null,
    rejectionReason: null,
    approvalIdempotencyKey: null,
    receiveRecordId: null,
    outboxEntryId: null,
    packingSlipDocumentId: null,
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
          companies: connected ? ['UCSH'] : [],
          gpCompanies: connected ? [{ id: 'UCSH', name: 'UC Shop', __typename: 'GpCompany' }] : [],
          companiesError: null,
          build: null,
          installId: null,
          lastConnectedAt: null,
          lastDisconnectedAt: null,
          lastDisconnectReason: null,
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
            company: 'TUBC',
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
// `project` is the PO's own project as the server reads it (#1877), archived or not.
function poDetailsMock(project: Record<string, unknown> | null = null): MockedResponse {
  return {
    request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId: 'po-1' } },
    result: {
      data: {
        poReceivingDetails: {
          __typename: 'PurchaseOrder',
          id: 'po-1',
          poNumber: 'PO-123',
          requestNumber: 'RQ-77',
          projectId: project ? 'proj-1' : null,
          project,
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

function renderModal(
  extraMocks: MockedResponse[] = [],
  d: ReceiveDraft = draft(),
  relayUp = true,
  poDetails: MockedResponse = poDetailsMock(),
) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[relayMock(relayUp), warehousesMock(), poDetails, ...extraMocks]}>
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

async function openModal(
  extraMocks: MockedResponse[] = [],
  d?: ReceiveDraft,
  relayUp = true,
  poDetails: MockedResponse = poDetailsMock(),
) {
  const result = renderModal(extraMocks, d, relayUp, poDetails);
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

async function retryViaConfirm() {
  fireEvent.click(await screen.findByRole('button', { name: 'Retry posting' }, SLOW));
  fireEvent.click(await screen.findByRole('button', { name: 'Retry' }, SLOW));
}

vi.setConfig({ testTimeout: 60_000 });

describe('ReceiveDraftReviewModal', () => {
  it('says when a resubmitted count last changed (#982)', async () => {
    await openModal([], draft({ updatedAt: '2026-08-03T15:30:00Z' }));
    expect(screen.getByText(/Counted by/)).toHaveTextContent(
      `last changed ${new Date('2026-08-03T15:30:00Z').toLocaleString()}`,
    );
  });

  it('says nothing about a change on a count nobody touched since (#982)', async () => {
    await openModal();
    expect(screen.queryByText(/last changed/)).not.toBeInTheDocument();
  });

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
        expectedUpdatedAt: '2026-08-02T10:00:00Z',
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
    // #1353: the failed approve may have claimed the draft, so the only way on is a same-key retry.
    expect(await screen.findByRole('button', { name: 'Retry posting' }, SLOW)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(within(screen.getByRole('table')).queryByRole('spinbutton')).toBeNull();
  });

  it('keeps the count and Reject after a refusal the server let go of - nothing was posted (#1582)', async () => {
    // The PO closed in GP after the dock counted it: the approval is refused and the claim released.
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('PO-3001 is closed in GP, so it cannot be received against.', {
            extensions: { code: 'VALIDATION_ERROR' },
          }),
        ],
      },
    };
    const rereadMock: MockedResponse = {
      request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
      result: { data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'PENDING_APPROVAL' } } },
    };
    await openModal([approveMock, rereadMock]);

    await approveViaConfirm();

    // The refusal, then the re-read: two round trips, slow under a full parallel run.
    await vi.waitFor(() => expect(document.body.textContent).toMatch(/Nothing was posted to GP/), { timeout: 15_000 });
    expect(document.body.textContent).toMatch(/closed in GP/);
    expect(screen.queryByRole('button', { name: 'Retry posting' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });

  it('keeps the failure and the GP detail when the re-read finds the draft still claimed (#1582)', async () => {
    // No answer came back: the server still holds the claim, so the only way on is the same-key retry -
    // and the reviewer must still see why.
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('GP did not answer in time while posting the receipt.', {
            extensions: { code: 'RELAY_TIMEOUT' },
          }),
        ],
      },
    };
    const rereadMock: MockedResponse = {
      request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
      result: {
        data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'APPROVING', approvalIdempotencyKey: 'k-1' } },
      },
    };
    await openModal([approveMock, rereadMock]);

    await approveViaConfirm();

    expect(await screen.findByRole('button', { name: 'Retry posting' }, { timeout: 15_000 })).toBeInTheDocument();
    await vi.waitFor(() => expect(document.body.textContent).toMatch(/Approving this receive failed/), SLOW);
    expect(screen.getByText('GP could not complete the receipt')).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Nothing was posted to GP/);
  });

  describe('a resumed approval refused with its claim held (#1945)', () => {
    const MAY_BE_IN_GP =
      'PO-3001 is closed in GP. An earlier attempt at this approval may already have posted the receipt to GP, ' +
      'so the draft stays claimed: check GP before going on - retry once the cause is fixed, or have the receipt reconciled.';
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: { errors: [new GraphQLError(MAY_BE_IN_GP, { extensions: { code: 'RECEIPT_MAY_BE_IN_GP' } })] },
    };
    function rereadMock(status: string): MockedResponse {
      return {
        request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
        result: {
          data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status, approvalIdempotencyKey: 'k-1' } },
        },
      };
    }

    it('says GP may hold the receipt and offers only the retry', async () => {
      await openModal([approveMock, rereadMock('APPROVING')]);

      await approveViaConfirm();

      expect(await screen.findByRole('button', { name: 'Retry posting' }, { timeout: 15_000 })).toBeInTheDocument();
      await vi.waitFor(() => expect(document.body.textContent).toMatch(/may already have posted the receipt/), SLOW);
      expect(document.body.textContent).not.toMatch(/Nothing was posted to GP/);
      expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    });

    it('never says nothing was posted, whatever the re-read finds', async () => {
      await openModal([approveMock, rereadMock('PENDING_APPROVAL')]);

      await approveViaConfirm();

      await vi.waitFor(() => expect(document.body.textContent).toMatch(/may already have posted the receipt/), {
        timeout: 15_000,
      });
      expect(document.body.textContent).not.toMatch(/Nothing was posted to GP/);
    });

    const RELEASE = "I've checked GP - no receipt was posted: release it";

    it('lets a manager who checked GP release it, behind a confirm that warns of a second receipt', async () => {
      let released = 0;
      const releaseMock: MockedResponse = {
        request: { query: RELEASE_HELD_RECEIVE_APPROVAL, variables: { id: 'draft-1' } },
        result: () => {
          released += 1;
          return { data: { releaseHeldReceiveApproval: { ...draft(), __typename: 'ReceiveDraft' } } };
        },
      };
      await openModal([approveMock, rereadMock('APPROVING'), releaseMock, rereadMock('PENDING_APPROVAL')]);

      await approveViaConfirm();
      fireEvent.click(await screen.findByRole('button', { name: RELEASE }, { timeout: 15_000 }));
      const confirm = await screen.findByRole('dialog', { name: 'Release this held approval' }, SLOW);
      expect(confirm).toHaveTextContent(/posted to GP twice/);
      expect(released).toBe(0);
      fireEvent.click(within(confirm).getByRole('button', { name: 'Release it' }));

      await vi.waitFor(() => expect(released).toBe(1), SLOW);
      expect(await screen.findByRole('button', { name: 'Approve & Post to GP' }, { timeout: 15_000 })).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: RELEASE })).toBeNull();
    });

    it('offers the release on reopening a draft still held, and not on a pending one', async () => {
      await openModal([], draft({ status: 'APPROVING', approvalIdempotencyKey: 'k-1' }));
      expect(screen.getByRole('button', { name: RELEASE })).toBeInTheDocument();
    });

    // #1945: another manager's attempt may still be out at GP, and the server refuses the release until then.
    it('does not offer the release on a claimed draft whose attempt may still be running', async () => {
      const soon = new Date(Date.now() + 60_000).toISOString();
      await openModal([], draft({ status: 'APPROVING', approvalIdempotencyKey: 'k-1', approvalReleasableAt: soon }));
      expect(screen.queryByRole('button', { name: RELEASE })).toBeNull();
    });

    it('offers the release once the attempt has run out of time', async () => {
      const past = new Date(Date.now() - 1_000).toISOString();
      await openModal([], draft({ status: 'APPROVING', approvalIdempotencyKey: 'k-1', approvalReleasableAt: past }));
      expect(screen.getByRole('button', { name: RELEASE })).toBeEnabled();
    });

    it('holds the release, saying why, when refused as maybe in GP while an attempt may still be running', async () => {
      const soon = new Date(Date.now() + 60_000).toISOString();
      const youngReread: MockedResponse = {
        request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
        result: {
          data: {
            receiveDraft: {
              ...draft(),
              __typename: 'ReceiveDraft',
              status: 'APPROVING',
              approvalIdempotencyKey: 'k-1',
              approvalReleasableAt: soon,
            },
          },
        },
      };
      await openModal([approveMock, youngReread]);

      await approveViaConfirm();

      // The reason first: the button is disabled while the approve is still submitting too, before the
      // re-read that says an attempt may be running has landed.
      expect(await screen.findByTestId('release-wait-reason', {}, { timeout: 15_000 })).toHaveTextContent(
        /may still be posting this receipt/,
      );
      expect(screen.getByRole('button', { name: RELEASE })).toBeDisabled();
    });

    it('does not offer the release on a draft awaiting approval', async () => {
      await openModal();
      expect(screen.queryByRole('button', { name: RELEASE })).toBeNull();
    });

    // A queued receipt that may be in GP, cancelled or failed with no answer: the draft stays approved.
    it('offers the release on an approved draft whose queued receipt stopped, and approves nothing', async () => {
      let released = 0;
      const releaseMock: MockedResponse = {
        request: { query: RELEASE_HELD_RECEIVE_APPROVAL, variables: { id: 'draft-1' } },
        result: () => {
          released += 1;
          return { data: { releaseHeldReceiveApproval: { ...draft(), __typename: 'ReceiveDraft' } } };
        },
      };
      await openModal(
        [releaseMock, rereadMock('PENDING_APPROVAL')],
        draft({ status: 'APPROVED', outboxEntryId: 'entry-1', queuedReceiptStopped: true }),
      );

      expect(document.body.textContent).toMatch(/stays approved until a manager checks GP/);
      expect(approveButton()).toBeDisabled();
      expect(screen.queryByTestId('approve-finished-reason')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: RELEASE }));
      const confirm = await screen.findByRole('dialog', { name: 'Release this held approval' }, SLOW);
      fireEvent.click(within(confirm).getByRole('button', { name: 'Release it' }));
      await vi.waitFor(() => expect(released).toBe(1), SLOW);
    });

    it('does not offer the release on an approved draft whose queued receipt is still going', async () => {
      await openModal([], draft({ status: 'APPROVED', outboxEntryId: 'entry-1', queuedReceiptStopped: false }));
      expect(screen.queryByRole('button', { name: RELEASE })).toBeNull();
    });
  });

  it('says another manager finished it, not "fix or reject", when the re-read is approved (#1582)', async () => {
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('This draft was already approved.', { extensions: { code: 'INVALID_STATE_TRANSITION' } }),
        ],
      },
    };
    const rereadMock: MockedResponse = {
      request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
      result: { data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'APPROVED' } } },
    };
    await openModal([approveMock, rereadMock]);

    await approveViaConfirm();

    await vi.waitFor(() => expect(document.body.textContent).toMatch(/approved elsewhere - refresh/), { timeout: 15_000 });
    expect(document.body.textContent).not.toMatch(/fix the count or reject/);
  });

  it('turns Approve off once the draft was approved elsewhere, and says why (#1593)', async () => {
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('This draft was already approved.', { extensions: { code: 'INVALID_STATE_TRANSITION' } }),
        ],
      },
    };
    const rereadMock: MockedResponse = {
      request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
      result: { data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'APPROVED' } } },
    };
    await openModal([approveMock, rereadMock]);

    await approveViaConfirm();

    await screen.findByTestId('approve-finished-reason', undefined, SLOW);
    expect(screen.getByTestId('approve-finished-reason')).toHaveTextContent('This draft was approved elsewhere.');
    expect(screen.getByRole('button', { name: 'Approve & Post to GP' })).toBeDisabled();
  });

  it('says a failed save approved nothing, without the duplicate-receipt assurance (#1593)', async () => {
    const updateMock: MockedResponse = {
      request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
      result: { errors: [new GraphQLError('Quantity must be whole', { extensions: { code: 'VALIDATION_ERROR' } })] },
    };
    await openModal([updateMock]);

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '3' } });
    await approveViaConfirm();

    await vi.waitFor(() => expect(document.body.textContent).toMatch(/Saving the counts failed - nothing was approved/), {
      timeout: 15_000,
    });
    expect(document.body.textContent).not.toMatch(/duplicate receipt/);
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

    await retryViaConfirm();
    await screen.findByText(/Approved\./, undefined, SLOW);

    expect(captured!.input.idempotencyKey).toBe('held-key-1');
  });

  // #1963: the modal stays mounted, so a key kept from an approval that has since ended would be sent
  // again by the next one - relinking its dead queued receipt, or booking a receipt GP may have reversed.
  describe('an approval key lives only as long as its approval (#1963)', () => {
    function capturingApprove(keys: string[], respond: () => Record<string, unknown>): MockedResponse<
      Record<string, unknown>,
      ApproveVars
    > {
      return {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        result: (vars) => {
          keys.push(vars.input.idempotencyKey);
          return respond();
        },
      };
    }

    it('mints a new key when a queued approval comes back for review', async () => {
      const keys: string[] = [];
      const mocks = [
        relayMock(false),
        warehousesMock(),
        poDetailsMock(),
        capturingApprove(keys, () => ({ data: approveResult(true, null) })),
        capturingApprove(keys, () => ({ data: approveResult(true, null) })),
      ];
      const tree = (d: ReceiveDraft) => (
        <MockedProvider mocks={mocks}>
          <MemoryRouter>
            <ToastProvider>
              <ReceiveDraftReviewModal open draft={d} onClose={() => undefined} />
            </ToastProvider>
          </MemoryRouter>
        </MockedProvider>
      );
      const { rerender } = render(tree(draft()));
      await screen.findByText('HG-100', undefined, SLOW);
      await approveViaConfirm();
      await screen.findByText(/Queued — the GP relay is offline/, undefined, SLOW);

      // The queued receipt was cancelled, and the list hands the modal the draft back for review.
      rerender(
        tree(draft({ rejectionReason: 'Back for review: the queued GP receipt was cancelled', updatedAt: '2026-08-02T10:00:00Z' })),
      );
      await approveViaConfirm();
      await vi.waitFor(() => expect(keys).toHaveLength(2), SLOW);

      expect(keys[0]).toMatch(UUID_RE);
      expect(keys[1]).toMatch(UUID_RE);
      expect(keys[1]).not.toBe(keys[0]);
    });

    it('mints a new key after a may-be-in-GP refusal whose re-read finds the draft back for review', async () => {
      // The approval was released while its attempt was out at GP: GP's answer is held under that key.
      const keys: string[] = [];
      const refused = capturingApprove(keys, () => ({
        errors: [
          new GraphQLError('This approval was released while the attempt was still out at GP.', {
            extensions: { code: 'RECEIPT_MAY_BE_IN_GP' },
          }),
        ],
      }));
      const reread: MockedResponse = {
        request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
        result: { data: { receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'PENDING_APPROVAL' } } },
      };
      const approved = capturingApprove(keys, () => ({ data: approveResult(false, 'RCT0000123') }));
      await openModal([refused, reread, approved]);

      await approveViaConfirm();
      await vi.waitFor(() => expect(document.body.textContent).toMatch(/released while the attempt/), {
        timeout: 15_000,
      });
      await approveViaConfirm();
      await screen.findByText(/Approved\./, undefined, SLOW);

      expect(keys).toHaveLength(2);
      expect(keys[1]).not.toBe(keys[0]);
    });

    it('keeps the key for the retry while the re-read finds the draft still claimed under it', async () => {
      const keys: string[] = [];
      const timedOut = capturingApprove(keys, () => ({
        errors: [new GraphQLError('GP did not answer in time.', { extensions: { code: 'RELAY_TIMEOUT' } })],
      }));
      const reread: MockedResponse = {
        request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
        result: () => ({
          data: {
            receiveDraft: { ...draft(), __typename: 'ReceiveDraft', status: 'APPROVING', approvalIdempotencyKey: keys[0] },
          },
        }),
      };
      const approved = capturingApprove(keys, () => ({ data: approveResult(false, 'RCT0000123') }));
      await openModal([timedOut, reread, approved]);

      await approveViaConfirm();
      await retryViaConfirm();
      await screen.findByText(/Approved\./, undefined, SLOW);

      expect(keys).toHaveLength(2);
      expect(keys[1]).toBe(keys[0]);
    });

    it('keeps the key for the retry when the connection dropped and nothing could be re-read', async () => {
      const keys: string[] = [];
      const dropped: MockedResponse<Record<string, unknown>, ApproveVars> = {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        result: (vars) => {
          keys.push(vars.input.idempotencyKey);
          return { errors: [new GraphQLError('connection reset')] };
        },
      };
      const approved = capturingApprove(keys, () => ({ data: approveResult(false, 'RCT0000123') }));
      // No re-read mock: the re-read fails as the approve did.
      await openModal([dropped, approved]);

      await approveViaConfirm();
      await retryViaConfirm();
      await screen.findByText(/Approved\./, undefined, SLOW);

      expect(keys).toHaveLength(2);
      expect(keys[1]).toBe(keys[0]);
    });
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

    await retryViaConfirm();
    await screen.findByText(/Approved\./, undefined, SLOW);

    expect(updateCalls).toBe(1);
  });

  it('shows an approving draft read-only, with retry instead of approve and no reject (#1353)', async () => {
    await openModal([], draft({ status: 'APPROVING', approvalIdempotencyKey: 'held-key-1' }));

    expect(screen.getByRole('button', { name: 'Retry posting' })).toBeEnabled();
    expect(screen.queryByRole('button', { name: 'Approve & Post to GP' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Reject' })).toBeNull();
    expect(within(screen.getByRole('table')).queryByRole('spinbutton')).toBeNull();
    expect(within(screen.getByRole('table')).getByText('2')).toBeInTheDocument();
  });

  it('the approve confirm says inventory waits on GP, and that an offline relay queues it (#1354)', async () => {
    await openModal([], draft(), false);
    fireEvent.click(await screen.findByRole('button', { name: 'Approve & Post to GP' }, SLOW));

    expect(await screen.findByText(/the receipt queues; inventory updates once it posts/, undefined, SLOW)).toBeInTheDocument();
    expect(screen.queryByText(/Inventory updates immediately/)).toBeNull();
  });

  it('flags a negative count as a line error and blocks approval (#1383)', async () => {
    await openModal();

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '-3' } });

    expect(screen.getByText('Whole units, 0 or more')).toBeInTheDocument();
    expect(approveButton()).toBeDisabled();
  });

  it('blocks approval when the reviewer raises the count past what the PO still owes', async () => {
    // The reviewer is deciding against what the PO owes NOW, which another receive may have moved
    // since the count was written - hence the live read this validates against.
    await openModal();

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '4' } });
    expect(screen.getByText('Max: 3')).toBeInTheDocument();
    expect(approveButton()).toBeDisabled();
  });

  // #730: GP refuses a GP RECEIVE ENTRY on a job it holds as inactive, closed or missing. #1877: the
  // project is the PO's own, off GET_PO_RECEIVING_DETAILS - the projects list left archived jobs out.
  function poProject(gpJobState: string | null, gpSetupOk = true): MockedResponse {
    return poDetailsMock({
      __typename: 'PurchaseOrderProject',
      id: 'proj-1',
      projectId: 'JOB-1',
      description: 'Riverside Tower',
      gpJobState,
      gpSetupOk,
      gpSetupIssues: gpSetupOk ? null : [{ __typename: 'GpSetupIssue', costCode: '08-710', accountIndex: 9999 }],
    });
  }

  it('blocks approval against a job that is inactive in GP, and says why', async () => {
    await openModal([], undefined, true, poProject('INACTIVE'));

    const banner = await screen.findByTestId('gp-job-not-open-banner', undefined, SLOW);
    expect(banner).toHaveTextContent('GP job JOB-1: Inactive in GP');
    expect(banner).toHaveTextContent('So approving a receive against it is not possible.');
    expect(approveButton()).toBeDisabled();
  });

  it('blocks approval against an archived job closed in GP, which the projects list leaves out (#1877)', async () => {
    // No projects-list mock at all: the modal reads the PO's own project, so an archived one is still seen.
    await openModal([], undefined, true, poProject('CLOSED'));

    const banner = await screen.findByTestId('gp-job-not-open-banner', undefined, SLOW);
    expect(banner).toHaveTextContent('GP job JOB-1');
    expect(approveButton()).toBeDisabled();
  });

  it("warns of an archived job's broken GP setup and blocks approval (#1877)", async () => {
    await openModal([], undefined, true, poProject('ACTIVE', false));

    expect(await screen.findByTestId('gp-setup-quarantine-banner', undefined, SLOW)).toBeInTheDocument();
    expect(approveButton()).toBeDisabled();
  });

  it("shows the server's refusal plainly when the job closed after the modal opened", async () => {
    const approveMock: MockedResponse = {
      request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('GP job JOB-1 is closed in GP.', { extensions: { code: 'GP_JOB_NOT_OPEN' } }),
        ],
      },
    };
    await openModal([approveMock], undefined, true, poProject('ACTIVE'));
    expect(approveButton()).toBeEnabled();

    await approveViaConfirm();

    expect(await screen.findByText('GP job JOB-1 is closed in GP.', undefined, SLOW)).toBeInTheDocument();
    expect(screen.queryByText(/A retry won't post a duplicate receipt/)).toBeNull();
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

  describe('the count it approves is the count it showed (#1497)', () => {
    it('sends the version it loaded with an unedited approval', async () => {
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

      await screen.findByText(/Approved\. 2 items added to inventory/, undefined, SLOW);
      expect(captured!.input.expectedUpdatedAt).toBe('2026-08-02T10:00:00Z');
    });

    it('approves against the version its own edit just saved, not the one it opened with', async () => {
      // The reviewer's edit moves updatedAt; approving with the loaded one would refuse their own change.
      let captured: ApproveVars | null = null;
      const updateMock: MockedResponse<Record<string, unknown>, UpdateVars> = {
        request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
        result: {
          data: { updateReceiveDraft: { ...draft({ updatedAt: '2026-08-02T10:05:00.123456' }), __typename: 'ReceiveDraft' } },
        },
      };
      const approveMock: MockedResponse<Record<string, unknown>, ApproveVars> = {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        result: (vars) => {
          captured = vars;
          return { data: approveResult(false, 'RCT0000123') };
        },
      };
      await openModal([updateMock, approveMock]);

      fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '3' } });
      await approveViaConfirm();

      await screen.findByText(/Approved\. 3 items added to inventory/, undefined, SLOW);
      expect(captured!.input.expectedUpdatedAt).toBe('2026-08-02T10:05:00.123456');
    });

    it('shows a refusal over a changed count and re-reads the draft, with nothing left to retry', async () => {
      const approveMock: MockedResponse = {
        request: { query: APPROVE_RECEIVE_DRAFT, variables: () => true },
        result: {
          errors: [
            new GraphQLError('This count changed since you opened it - review the new numbers before going on.', {
              extensions: { code: 'CONFLICT', field: 'expected_updated_at' },
            }),
          ],
        },
      };
      // The author recounted to three while the manager had two on screen.
      const recounted = draft({
        updatedAt: '2026-08-02T10:07:00',
        totalQuantity: 3,
        lineItems: [{ ...draft().lineItems[0], quantityReceived: 3 }],
      });
      const rereadMock: MockedResponse = {
        request: { query: GET_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
        result: { data: { receiveDraft: { ...recounted, __typename: 'ReceiveDraft' } } },
      };
      await openModal([approveMock, rereadMock]);

      await approveViaConfirm();

      expect(await screen.findByText(/This count changed since you opened it/, undefined, SLOW)).toBeInTheDocument();
      await vi.waitFor(
        () => expect(within(screen.getByRole('table')).getByRole('spinbutton')).toHaveValue(3),
        SLOW,
      );
      // Refused before any claim, so this is a fresh review of the new count, not a retry of a post.
      expect(screen.queryByRole('button', { name: 'Retry posting' })).toBeNull();
      expect(screen.queryByText(/A retry won't post a duplicate receipt/)).toBeNull();
      expect(approveButton()).toBeEnabled();
    });
  });
});
