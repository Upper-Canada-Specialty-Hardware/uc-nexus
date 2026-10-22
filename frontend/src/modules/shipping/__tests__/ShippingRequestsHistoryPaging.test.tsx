import { render, screen, fireEvent, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShippingRequestsPage from '../ShippingRequestsPage';
import { GET_SHIPPING_OUT_REQUESTS } from '../../../graphql/shipping';
import { GET_PROJECTS } from '../../../graphql/shared';

/**
 * #1888: the Accepted and Rejected tabs read a page at a time, newest first, and a full page offers
 * Load more; the Pending view stays one unpaged read.
 */

vi.setConfig({ testTimeout: 60_000 });
configure({ asyncUtilTimeout: 15_000 });

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Test User',
    userId: 'user_1',
    roles: ['Shipping Manager'],
    hasRole: (role: string) => role === 'Shipping Manager',
    isNexusAdmin: false,
    isTenantOwner: false,
    ownsTenant: false,
    isDbAdmin: false,
    gpBuyerId: null,
    company: 'TUBC',
    user: null,
  }),
}));

// A page of two keeps the boards small enough to render quickly; the paging is the same at any size.
vi.mock('../../shop-assembly/requestStages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../shop-assembly/requestStages')>()),
  HISTORY_PAGE_SIZE: 2,
}));

const PAGE = 2;

function request(n: number, status: 'PENDING' | 'APPROVED') {
  return {
    __typename: 'ShippingOutRequestType',
    id: `req-${n}`,
    requestNumber: `SOR-${String(n).padStart(4, '0')}`,
    projectId: 'proj-1',
    status,
    stage: status === 'PENDING' ? 'REQUESTED' : 'DONE',
    createdBy: 'Pat Miller',
    createdAt: '2026-09-01T00:00:00Z',
    approvedBy: null,
    approvedAt: null,
    rejectedBy: null,
    rejectedAt: null,
    rejectionReason: null,
    integrityNote: null,
    returnNote: null,
    pullRequestId: null,
    items: [],
  };
}

const range = (from: number, count: number, status: 'PENDING' | 'APPROVED') =>
  Array.from({ length: count }, (_, i) => request(from + i, status));

const projectsMock: MockedResponse = {
  request: { query: GET_PROJECTS },
  maxUsageCount: Number.POSITIVE_INFINITY,
  result: { data: { projects: [] } },
};

function renderPage(mocks: MockedResponse[], path: string) {
  render(
    <MockedProvider mocks={[projectsMock, ...mocks]}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <ShippingRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('pages the Accepted tab newest first and loads the next page on Load more', async () => {
  renderPage(
    [
      {
        request: {
          query: GET_SHIPPING_OUT_REQUESTS,
          variables: { projectId: null, status: 'APPROVED', limit: PAGE, offset: 0, newestFirst: true },
        },
        result: { data: { shippingOutRequests: range(1, PAGE, 'APPROVED') } },
      },
      {
        request: {
          query: GET_SHIPPING_OUT_REQUESTS,
          variables: { projectId: null, status: 'APPROVED', limit: PAGE, offset: PAGE, newestFirst: true },
        },
        result: { data: { shippingOutRequests: range(PAGE + 1, 1, 'APPROVED') } },
      },
    ],
    '/app/shipping/requests?view=APPROVED',
  );

  expect(await screen.findByText(`Showing the newest ${PAGE} - older requests exist.`)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('SOR-0003')).toBeInTheDocument();
  // A short page is the last one, so nothing more is offered.
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
});

it('reads the Pending view unpaged, with no Load more', async () => {
  renderPage(
    [
      {
        request: { query: GET_SHIPPING_OUT_REQUESTS, variables: { projectId: null, status: 'PENDING' } },
        result: { data: { shippingOutRequests: range(1, PAGE, 'PENDING') } },
      },
    ],
    '/app/shipping/requests',
  );

  expect(await screen.findByText(`${PAGE} in queue`)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
});
