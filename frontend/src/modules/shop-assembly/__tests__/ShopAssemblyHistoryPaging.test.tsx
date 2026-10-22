import { render, screen, fireEvent, configure } from '@testing-library/react';
import type { MockedResponse } from '@apollo/client/testing';
import { MockedProvider } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import ShopAssemblyRequestsPage from '../ShopAssemblyRequestsPage';
import { GET_SHOP_ASSEMBLY_REQUESTS } from '../../../graphql/shop-assembly';

/**
 * #1888: the Worked and Rejected tabs read a page at a time, newest first, and a full page offers
 * Load more; the Pending board stays one unpaged read.
 */

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: 'Sam Manager',
    userId: 'user_1',
    roles: ['Shop Assembly Manager'],
    hasRole: () => true,
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
configure({ asyncUtilTimeout: 15_000 });

// A page of two keeps the boards small enough to render quickly; the paging is the same at any size.
vi.mock('../requestStages', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../requestStages')>()),
  HISTORY_PAGE_SIZE: 2,
}));

const PAGE = 2;

function request(n: number, status: 'PENDING' | 'APPROVED') {
  return {
    __typename: 'ShopAssemblyRequest',
    id: `req-${n}`,
    requestNumber: `80001-${String(n).padStart(4, '0')}`,
    projectId: 'proj-1',
    projectNumber: '80001',
    projectName: 'Cowichan Dist Hospital',
    status,
    stage: status === 'PENDING' ? 'REQUESTED' : 'DONE',
    createdBy: 'Pat Miller',
    createdAt: '2026-10-01T10:00:00Z',
    approvedBy: null,
    approvedAt: null,
    rejectedBy: null,
    rejectedAt: null,
    rejectionReason: null,
    integrityNote: null,
    returnNote: null,
    items: [],
    openings: [],
    batches: [],
  };
}

const range = (from: number, count: number, status: 'PENDING' | 'APPROVED') =>
  Array.from({ length: count }, (_, i) => request(from + i, status));

function renderPage(mocks: MockedResponse[], path: string) {
  render(
    <MockedProvider mocks={mocks}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <ShopAssemblyRequestsPage />
        </MemoryRouter>
      </ToastProvider>
    </MockedProvider>,
  );
}

it('pages the Worked tab newest first and loads the next page on Load more', async () => {
  renderPage(
    [
      {
        request: {
          query: GET_SHOP_ASSEMBLY_REQUESTS,
          variables: { status: 'APPROVED', limit: PAGE, offset: 0, newestFirst: true },
        },
        result: { data: { shopAssemblyRequests: range(1, PAGE, 'APPROVED') } },
      },
      {
        request: {
          query: GET_SHOP_ASSEMBLY_REQUESTS,
          variables: { status: 'APPROVED', limit: PAGE, offset: PAGE, newestFirst: true },
        },
        result: { data: { shopAssemblyRequests: range(PAGE + 1, 1, 'APPROVED') } },
      },
    ],
    '/app/shop-assembly/requests?view=APPROVED',
  );

  expect(await screen.findByText(`Showing the newest ${PAGE} - older requests exist.`)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Load more' }));

  expect(await screen.findByText('80001-0003')).toBeInTheDocument();
  // A short page is the last one, so nothing more is offered.
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
});

it('reads the Pending board unpaged, with no Load more', async () => {
  renderPage(
    [
      {
        request: { query: GET_SHOP_ASSEMBLY_REQUESTS, variables: { status: 'PENDING' } },
        result: { data: { shopAssemblyRequests: range(1, PAGE, 'PENDING') } },
      },
    ],
    '/app/shop-assembly/requests',
  );

  expect(await screen.findByText(`${PAGE} in queue`)).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
});
