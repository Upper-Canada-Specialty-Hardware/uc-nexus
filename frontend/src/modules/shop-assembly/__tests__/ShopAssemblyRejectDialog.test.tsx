import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShopAssemblyRequestsPage from '../ShopAssemblyRequestsPage';
import {
  GET_SHOP_ASSEMBLY_ALLOCATION_REVIEW,
  GET_SHOP_ASSEMBLY_REQUESTS,
  REJECT_SHOP_ASSEMBLY_REQUEST,
} from '../../../graphql/shop-assembly';

/**
 * #1242: rejecting a shop assembly request says why. The reject dialog will not send without a reason,
 * and sends the trimmed reason it was given. The batch panel is stubbed down to its reject button - the
 * allocation review behind it is not what is under test.
 */

vi.mock('../BatchReviewPanel', () => ({
  default: ({ onReject }: { onReject: () => void }) => (
    <button type="button" onClick={onReject}>
      Reject request
    </button>
  ),
}));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: ['Shop Assembly Manager'],
    hasRole: (role: string) => role === 'Shop Assembly Manager',
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

vi.setConfig({ testTimeout: 60_000 });

function request(status: 'PENDING' | 'REJECTED') {
  return {
    __typename: 'ShopAssemblyRequest',
    id: `req-${status}`,
    requestNumber: status === 'PENDING' ? '80001-009' : '80001-010',
    projectId: 'proj-1',
    projectNumber: '80001',
    projectName: 'Cowichan Dist Hospital',
    status,
    stage: status === 'PENDING' ? 'REQUESTED' : 'REJECTED',
    createdBy: 'Pat Miller',
    createdAt: '2026-10-01T10:00:00Z',
    approvedBy: null,
    approvedAt: null,
    rejectedBy: status === 'REJECTED' ? 'Sam Manager' : null,
    rejectedAt: status === 'REJECTED' ? '2026-10-01T11:00:00Z' : null,
    rejectionReason: status === 'REJECTED' ? 'wrong job' : null,
    integrityNote: null,
    returnNote: null,
    items: [],
    // Rejecting does not touch the opening rows - they stay PENDING.
    openings: [
      {
        __typename: 'ShopAssemblyRequestOpening',
        id: `op-${status}`,
        openingNumber: '01-VEST-400',
        status: 'PENDING',
        batchId: null,
        dismissedBy: null,
        dismissedAt: null,
        dismissalReason: null,
      },
    ],
    batches: [],
  };
}

const rejectCalled = vi.fn();

const mocks: MockedResponse[] = [
  {
    request: { query: GET_SHOP_ASSEMBLY_REQUESTS, variables: { status: 'PENDING' } },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { shopAssemblyRequests: [request('PENDING')] } },
  },
  {
    request: { query: GET_SHOP_ASSEMBLY_ALLOCATION_REVIEW, variables: () => true },
    maxUsageCount: Number.POSITIVE_INFINITY,
    result: { data: { shopAssemblyAllocationReview: null } },
  },
  {
    request: { query: REJECT_SHOP_ASSEMBLY_REQUEST, variables: { id: 'req-PENDING', reason: 'frames not ready' } },
    result: () => {
      rejectCalled();
      return { data: { rejectShopAssemblyRequest: request('REJECTED') } };
    },
  },
];

it('will not reject without a reason, and sends the reason it is given (#1242)', async () => {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter>
          <ShopAssemblyRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );

  fireEvent.click(await screen.findByText('80001-009'));
  fireEvent.click(await screen.findByRole('button', { name: 'Reject request' }));

  const dialog = await screen.findByRole('dialog');
  const reject = screen.getByRole('button', { name: 'Reject' });
  expect(reject).toBeDisabled();

  fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: '   ' } });
  expect(reject).toBeDisabled();

  fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: '  frames not ready  ' } });
  expect(reject).toBeEnabled();
  fireEvent.click(reject);

  await waitFor(() => expect(rejectCalled).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
});
