import { render, screen, fireEvent, within } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { ToastProvider } from '../../../components/Toast';
import ReceiveDraftEditModal from '../ReceiveDraftEditModal';
import {
  GET_PO_RECEIVING_DETAILS,
  UPDATE_RECEIVE_DRAFT,
  RESUBMIT_RECEIVE_DRAFT,
} from '../../../graphql/warehouse';
import type { ReceiveDraft } from '../receiveDraftTypes';

// The author's side of a draft: fix the count, add or clear the remark, and put a rejected one back
// in the queue. Nothing here can reach GP, so there is no relay apparatus to stand up.

type UpdateVars = {
  input: {
    draftId: string;
    warehouseId: string | null;
    notes: string;
    lineItems: { poLineItemId: string; quantityReceived: number; locations: unknown[] }[];
  };
};

vi.setConfig({ testTimeout: 30_000 });

const SLOW = { timeout: 5000 };

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
    packingSlipDocumentId: null,
    notes: 'box crushed',
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
        locations: [],
      },
    ],
    ...overrides,
  };
}

function poDetailsMock(): MockedResponse {
  return {
    request: { query: GET_PO_RECEIVING_DETAILS, variables: { poId: 'po-1' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
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
              receivedQuantity: 0,
              unitCost: 2.5,
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

function updateMock(capture: (vars: UpdateVars) => void): MockedResponse<Record<string, unknown>, UpdateVars> {
  return {
    request: { query: UPDATE_RECEIVE_DRAFT, variables: () => true },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: (vars) => {
      capture(vars);
      return { data: { updateReceiveDraft: { __typename: 'ReceiveDraft', id: 'draft-1' } } };
    },
  };
}

const resubmitMock: MockedResponse = {
  request: { query: RESUBMIT_RECEIVE_DRAFT, variables: { id: 'draft-1' } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { resubmitReceiveDraft: { __typename: 'ReceiveDraft', id: 'draft-1' } } },
};

async function openModal(extraMocks: MockedResponse[] = [], d: ReceiveDraft = draft()) {
  const onClose = vi.fn();
  render(
    <MockedProvider mocks={[poDetailsMock(), ...extraMocks]}>
      <ToastProvider>
        <ReceiveDraftEditModal open draft={d} onClose={onClose} />
      </ToastProvider>
    </MockedProvider>,
  );
  await screen.findByText('HG-100', undefined, SLOW);
  return { onClose };
}

const notesField = () => screen.getByLabelText('Notes (optional)');

describe('ReceiveDraftEditModal notes (#632)', () => {
  it('seeds the remark off the draft', async () => {
    await openModal();
    expect(notesField()).toHaveValue('box crushed');
  });

  it('sends the retyped remark, with nothing else on the draft touched', async () => {
    // The note is the only edit, so a save handler that forgot to watch it would post the value the
    // modal opened with and the retype would vanish without an error.
    let captured: UpdateVars | null = null;
    await openModal([updateMock((v) => (captured = v))]);

    fireEvent.change(notesField(), { target: { value: 'short 2 per slip' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await vi.waitFor(() => expect(captured).not.toBeNull(), SLOW);
    expect(captured!.input.notes).toBe('short 2 per slip');
    expect(captured!.input.lineItems).toEqual([
      { poLineItemId: 'li-1', quantityReceived: 2, locations: [] },
    ]);
  });

  it('sends the empty string when the remark is cleared, so the clear travels', async () => {
    let captured: UpdateVars | null = null;
    await openModal([updateMock((v) => (captured = v))]);

    fireEvent.change(notesField(), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await vi.waitFor(() => expect(captured).not.toBeNull(), SLOW);
    expect(captured!.input.notes).toBe('');
  });
});

describe('ReceiveDraftEditModal rejected drafts', () => {
  it('saves the fix and puts the draft back in the queue, in that order', async () => {
    let captured: UpdateVars | null = null;
    const rejected = draft({ status: 'REJECTED', rejectionReason: 'Count is two boxes short', reviewedBy: 'Mgr' });
    const { onClose } = await openModal([updateMock((v) => (captured = v)), resubmitMock], rejected);

    // The reason is in front of the author while they fix it.
    expect(screen.getByText(/Mgr sent this back: Count is two boxes short/)).toBeInTheDocument();

    fireEvent.change(within(screen.getByRole('table')).getByRole('spinbutton'), { target: { value: '4' } });
    fireEvent.change(notesField(), { target: { value: 'recounted' } });
    fireEvent.click(screen.getByRole('button', { name: 'Resubmit for Approval' }));

    await vi.waitFor(() => expect(onClose).toHaveBeenCalled(), SLOW);
    expect(captured!.input.notes).toBe('recounted');
    expect(captured!.input.lineItems).toEqual([
      { poLineItemId: 'li-1', quantityReceived: 4, locations: [] },
    ]);
  });
});
