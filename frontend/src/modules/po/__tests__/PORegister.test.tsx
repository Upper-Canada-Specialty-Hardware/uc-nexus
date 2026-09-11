import { render, screen, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import POModule from '../index';
import { PURCHASE_ORDERS_PAGE, GET_PO_STATISTICS } from '../../../graphql/po';
import { GET_PROJECTS, GET_GP_OUTBOX, GET_RELAY_STATUS } from '../../../graphql/shared';

// The register mounts five queries and a full MUI table; jsdom is slow enough at that to trip the
// 1s async-util default once vitest is running files in parallel.
vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 15_000 });

// Neither dialog is under test here, and POGenerateDialog drags in @react-pdf/renderer at module
// level (PODetailModal imports it, and the register imports PODetailModal).
vi.mock('../POGenerateDialog', () => ({ default: () => null }));
vi.mock('../GpPurchaseOrderDialog', () => ({ default: () => null }));

// The register reads differently for the two kinds of caller - an Admin/Manager sees every company's
// POs at once, a scoped user only their own - so the identity is switchable per test.
const identity = vi.hoisted(() => ({ isAdmin: true, company: null as string | null }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: identity.isAdmin ? 'Admin' : 'Bev Buyer',
    userId: identity.isAdmin ? 'user_admin' : 'user_buyer',
    roles: identity.isAdmin ? ['Admin/Manager'] : [],
    hasRole: (role: string) => identity.isAdmin && role === 'Admin/Manager',
    isAdmin: identity.isAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: null,
  }),
}));

beforeEach(() => {
  identity.isAdmin = true;
  identity.company = null;
});

const INFINITE = Number.POSITIVE_INFINITY;

function row(overrides: Record<string, unknown>) {
  return {
    __typename: 'POListRow',
    id: 'po-1',
    poNumber: null,
    requestNumber: null,
    projectId: null,
    status: 'DRAFT',
    origin: 'NEXUS',
    company: 'TUBC',
    gpCompany: null,
    vendorNameSnapshot: 'Ace Hardware Co',
    createdBy: 'Bev Buyer',
    orderedAt: null,
    expectedDeliveryDate: null,
    createdAt: '2026-07-01T12:00:00Z',
    gpSyncedAt: null,
    lineItemCount: 3,
    ...overrides,
  };
}

// A Nexus draft (no GP registration yet, so no gpCompany) beside a mirrored GP row that has both.
const ROWS = [
  row({ id: 'po-draft', requestNumber: 'PO-REQ-001', status: 'DRAFT', company: 'TUBC', gpCompany: null }),
  row({
    id: 'po-registered',
    poNumber: 'PO-2001',
    status: 'GP_REGISTERED',
    origin: 'GP',
    company: 'UCSH',
    gpCompany: 'UCSH',
  }),
];

// The variable matchers are permissive on purpose: the register's default status filter excludes
// DRAFT, and what is under test is what the row renders, not which rows the server picks.
function mocks(): MockedResponse[] {
  return [
    {
      request: { query: PURCHASE_ORDERS_PAGE, variables: () => true },
      result: {
        data: {
          purchaseOrdersPage: { __typename: 'PurchaseOrderPage', rows: ROWS, totalCount: ROWS.length },
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PO_STATISTICS, variables: () => true },
      result: {
        data: {
          poStatistics: {
            __typename: 'POStatistics',
            total: 2,
            draft: 1,
            gpRegistered: 1,
            vendorConfirmed: 0,
            partiallyReceived: 0,
            closed: 0,
            cancelled: 0,
          },
        },
      },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_PROJECTS, variables: () => true },
      result: { data: { projects: [] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_GP_OUTBOX, variables: () => true },
      result: { data: { gpOutbox: [] } },
      maxUsageCount: INFINITE,
    },
    {
      request: { query: GET_RELAY_STATUS, variables: () => true },
      result: {
        data: {
          relayStatus: {
            __typename: 'RelayStatus',
            connected: true,
            companies: ['TUBC', 'UCSH'],
            gpCompanies: [
              { __typename: 'GpCompany', id: 'TUBC', name: 'Test UBC' },
              { __typename: 'GpCompany', id: 'UCSH', name: 'UC Shop' },
            ],
            companiesError: null,
            build: 'relay-v0.1.0',
            installId: 'install-1',
            lastConnectedAt: null,
            lastDisconnectedAt: null,
            lastDisconnectReason: null,
            previewChannels: [],
          },
        },
      },
      maxUsageCount: INFINITE,
    },
  ];
}

function renderRegister() {
  render(
    <MemoryRouter initialEntries={['/']}>
      <MockedProvider mocks={mocks()}>
        <ToastProvider>
          <POModule />
        </ToastProvider>
      </MockedProvider>
    </MemoryRouter>,
  );
}

/** The Company cell of the row carrying `label` - column 1, after Project. */
async function companyCellOf(label: string) {
  const tr = (await screen.findByText(label)).closest('tr');
  return within(tr as HTMLElement).getAllByRole('cell')[1];
}

// #637: the column used to read gpCompany, which a draft never has, so every draft printed "-" and
// nothing on the register could say whose it was. It reads the tenant now.
it('shows the tenant on a draft that has no GP company yet', async () => {
  renderRegister();

  expect(await companyCellOf('PO-REQ-001')).toHaveTextContent('TUBC');
});

it('shows the tenant on a registered row too', async () => {
  renderRegister();

  expect(await companyCellOf('PO-2001')).toHaveTextContent('UCSH');
});

// The heading answers "whose purchase orders am I looking at?", which nothing on the page said.
it('tells an Admin/Manager the table is every company at once', async () => {
  renderRegister();

  expect(await screen.findByText('All companies')).toBeInTheDocument();
});

it('names the scoped user’s own GP company in the heading, and still gives them the column', async () => {
  identity.isAdmin = false;
  identity.company = 'TUBC';
  renderRegister();

  // The heading carries the code and GP's name for it; the row carries the code. The name arrives
  // with the relay poll, a beat after the heading itself, so it is waited for rather than asserted
  // on the first frame.
  const heading = (await screen.findByText('Purchase Orders')).parentElement as HTMLElement;
  await waitFor(() => expect(heading).toHaveTextContent('Test UBC'));
  expect(heading).toHaveTextContent('TUBC');
  expect(screen.queryByText('All companies')).toBeNull();

  expect(await companyCellOf('PO-REQ-001')).toHaveTextContent('TUBC');
});
