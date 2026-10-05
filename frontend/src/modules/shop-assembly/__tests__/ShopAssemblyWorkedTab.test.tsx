import { render, screen, fireEvent } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShopAssemblyRequestsPage from '../ShopAssemblyRequestsPage';
import { GET_SHOP_ASSEMBLY_REQUESTS } from '../../../graphql/shop-assembly';

/**
 * #1539: on the Worked tab a PM sees a batch's Discard switched off with nothing saying why (#981), and the
 * header counted worked requests as "in queue". The re-upload note shows once, from the request itself.
 */

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Pat Miller',
    userId: 'user_2',
    roles: ['Project Manager'],
    hasRole: () => false,
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

vi.mock('../BatchReviewPanel', () => ({ default: () => null }));

vi.setConfig({ testTimeout: 60_000 });

const NOTE = 'The schedule was re-uploaded after this request was made.';

function request(status: 'PENDING' | 'APPROVED') {
  return {
    __typename: 'ShopAssemblyRequest',
    id: `req-${status}`,
    requestNumber: status === 'PENDING' ? '80001-009' : '80001-011',
    projectId: 'proj-1',
    projectNumber: '80001',
    projectName: 'Cowichan Dist Hospital',
    status,
    stage: status === 'PENDING' ? 'REQUESTED' : 'BATCHED',
    createdBy: 'Pat Miller',
    createdAt: '2026-10-01T10:00:00Z',
    approvedBy: status === 'APPROVED' ? 'Sam Manager' : null,
    approvedAt: status === 'APPROVED' ? '2026-10-01T11:00:00Z' : null,
    rejectedBy: null,
    rejectedAt: null,
    rejectionReason: null,
    integrityNote: status === 'PENDING' ? NOTE : null,
    returnNote: null,
    items: [],
    openings: [
      {
        __typename: 'ShopAssemblyRequestOpening',
        id: `op-${status}`,
        openingNumber: '01-VEST-400',
        status: status === 'PENDING' ? 'PENDING' : 'BATCHED',
        batchId: status === 'PENDING' ? null : 'b-1',
        dismissedBy: null,
        dismissedAt: null,
        dismissalReason: null,
      },
    ],
    batches:
      status === 'PENDING'
        ? []
        : [
            {
              __typename: 'ShopAssemblyBatch',
              id: 'b-1',
              sequence: 1,
              batchNumber: '80001-011-B1',
              status: 'ACTIVE',
              createdBy: 'Sam Manager',
              createdAt: '2026-10-01T11:00:00Z',
              pullRequestId: 'pr-1',
              pullStatus: 'PENDING',
              items: [
                {
                  __typename: 'ShopAssemblyBatchItem',
                  id: 'bi-1',
                  openingNumber: '01-VEST-400',
                  hardwareCategory: 'HINGE',
                  productCode: 'HG-100',
                  allocatedQuantity: 3,
                },
              ],
            },
          ],
  };
}

const mock = (status: 'PENDING' | 'APPROVED'): MockedResponse => ({
  request: { query: GET_SHOP_ASSEMBLY_REQUESTS, variables: { status } },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { shopAssemblyRequests: [request(status)] } },
});

function renderPage(path: string) {
  render(
    <MockedProvider mocks={[mock('PENDING'), mock('APPROVED')]}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <ShopAssemblyRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('shows the re-upload note once on a pending request', async () => {
  renderPage('/app/shop-assembly/requests');
  fireEvent.click(await screen.findByText('80001-009'));
  expect(await screen.findAllByText(NOTE)).toHaveLength(1);
});

it('counts a queue on Pending', async () => {
  renderPage('/app/shop-assembly/requests');
  expect(await screen.findByText('1 in queue')).toBeInTheDocument();
});

it('counts no queue on Worked - those requests wait on nobody', async () => {
  renderPage('/app/shop-assembly/requests?view=APPROVED');
  await screen.findByText('80001-011');
  expect(screen.queryByText(/in queue/)).not.toBeInTheDocument();
});

it("says why a non-manager's Discard is off", async () => {
  renderPage('/app/shop-assembly/requests?view=APPROVED');
  fireEvent.click(await screen.findByText('80001-011'));

  const discard = await screen.findByRole('button', { name: 'Discard' });
  expect(discard).toBeDisabled();
  fireEvent.mouseOver(discard.parentElement!);
  expect(await screen.findByRole('tooltip')).toHaveTextContent(/discarding are the Shop Assembly Manager/);
});
