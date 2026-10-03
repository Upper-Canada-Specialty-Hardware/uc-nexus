import { render, screen, fireEvent } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShopAssemblyRequestsPage from '../ShopAssemblyRequestsPage';
import { DISMISS_SHOP_ASSEMBLY_OPENINGS, GET_SHOP_ASSEMBLY_REQUESTS } from '../../../graphql/shop-assembly';

/**
 * #983: rejecting a shop assembly request leaves its openings' own status at PENDING, so the list used
 * to say "1 opening waiting" on a request nobody will ever batch. Only a pending request's openings wait.
 */

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

// The panel needs a loaded allocation review before it shows its buttons; these tests are about the
// page around it, so a stub hands back the one callback the dismiss test drives.
vi.mock('../BatchReviewPanel', () => ({
  default: ({ onDismissRemaining }: { onDismissRemaining: () => void }) => (
    <button type="button" onClick={onDismissRemaining}>
      Dismiss remaining
    </button>
  ),
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

const mock = (status: 'PENDING' | 'REJECTED'): MockedResponse => ({
  request: { query: GET_SHOP_ASSEMBLY_REQUESTS, variables: { status } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { shopAssemblyRequests: [request(status)] } },
});

function renderPage(extra: MockedResponse[] = []) {
  render(
    <MockedProvider mocks={[mock('PENDING'), mock('REJECTED'), ...extra]}>
      <ToastProvider>
        <MemoryRouter>
          <ShopAssemblyRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('says a pending request has openings waiting', async () => {
  renderPage();
  expect(await screen.findByText('1 opening waiting')).toBeInTheDocument();
});

it('never says the openings of a rejected request are waiting (#983)', async () => {
  renderPage();
  await screen.findByText('80001-009');

  fireEvent.click(screen.getByRole('button', { name: 'Rejected' }));

  expect(await screen.findByText('80001-010')).toBeInTheDocument();
  expect(screen.getByText('1 opening')).toBeInTheDocument();
  expect(screen.queryByText(/waiting/)).not.toBeInTheDocument();
});

it('sends the reason typed into the dismiss confirm (#1156)', async () => {
  const dismissed = vi.fn(() => ({ data: { dismissShopAssemblyOpenings: request('PENDING') } }));
  renderPage([
    {
      request: {
        query: DISMISS_SHOP_ASSEMBLY_OPENINGS,
        variables: { requestId: 'req-PENDING', openingNumbers: null, reason: 'client supplying' },
      },
      result: dismissed,
    },
  ]);
  fireEvent.click(await screen.findByText('80001-009'));

  fireEvent.click(await screen.findByRole('button', { name: /dismiss remaining/i }));
  const reason = await screen.findByLabelText('Reason (optional)');
  expect(reason).toHaveAttribute('maxlength', '500');
  fireEvent.change(reason, { target: { value: '  client supplying ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

  await vi.waitFor(() => expect(dismissed).toHaveBeenCalled());
});
