import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import MyReceiveDraftsView from '../MyReceiveDraftsView';
import { GET_RECEIVE_DRAFTS, DELETE_RECEIVE_DRAFT } from '../../../graphql/warehouse';

// The author's side of a draft. A rejection is only useful if the person who has to act on it can
// see why, so the reason and the reviewer are what this file is mostly about.

function draft(overrides: Record<string, unknown> = {}) {
  return {
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
    totalQuantity: 4,
    createdAt: '2026-08-02T10:00:00Z',
    updatedAt: '2026-08-02T10:00:00Z',
    lineItems: [],
    ...overrides,
  };
}

function draftsMock(drafts: Record<string, unknown>[]): MockedResponse {
  return {
    request: { query: GET_RECEIVE_DRAFTS, variables: { mine: true } },
    result: { data: { receiveDrafts: drafts } },
    maxUsageCount: Number.POSITIVE_INFINITY,
  };
}

function renderView(mocks: MockedResponse[] = [], drafts = [draft()]) {
  render(
    <MockedProvider mocks={[draftsMock(drafts), ...mocks]}>
      <MemoryRouter>
        <ToastProvider>
          <MyReceiveDraftsView />
        </ToastProvider>
      </MemoryRouter>
    </MockedProvider>,
  );
}

const SLOW = { timeout: 5000 };

vi.setConfig({ testTimeout: 30_000 });

describe('MyReceiveDraftsView', () => {
  it('lists a pending draft as awaiting approval', async () => {
    renderView();

    expect(await screen.findByText('PO-123', undefined, SLOW)).toBeInTheDocument();
    // Twice: the section heading and the card's own chip. Both are the point - the heading groups
    // them, the chip survives being read out of context.
    expect(screen.getAllByText('Awaiting approval')).toHaveLength(2);
    expect(screen.getByText(/4 units/)).toBeInTheDocument();
    expect(screen.queryByText(/Sent back/)).toBeNull();
  });

  it('leads with a rejected draft and says who sent it back and why', async () => {
    renderView(
      [],
      [
        draft({
          id: 'draft-2',
          status: 'REJECTED',
          reviewedBy: 'Manny Manager',
          rejectionReason: 'Count is two boxes short of the packing slip',
        }),
      ],
    );

    expect(await screen.findByText('Sent back — needs your attention', undefined, SLOW)).toBeInTheDocument();
    expect(
      screen.getByText(/Manny Manager sent this back: Count is two boxes short of the packing slip/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Edit & Resubmit' })).toBeInTheDocument();
  });

  it('deletes a draft after a confirmation', async () => {
    let deleted: { id: string } | null = null;
    const deleteMock: MockedResponse<Record<string, unknown>, { id: string }> = {
      request: { query: DELETE_RECEIVE_DRAFT, variables: () => true },
      result: (vars) => {
        deleted = vars;
        return { data: { deleteReceiveDraft: true } };
      },
    };
    renderView([deleteMock]);
    await screen.findByText('PO-123', undefined, SLOW);

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    // The count is the only record of what arrived, so the confirmation says so.
    expect(await screen.findByText(/The count of 4 units against PO-123 is lost/, undefined, SLOW)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete' }).at(-1)!);

    await vi.waitFor(() => expect(deleted).toEqual({ id: 'draft-1' }), SLOW);
  });

  it('says so when the user has nothing waiting', async () => {
    renderView([], []);

    expect(await screen.findByText(/You have no receives waiting on approval/, undefined, SLOW)).toBeInTheDocument();
  });
});
