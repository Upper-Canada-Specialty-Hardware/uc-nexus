import { act, render, screen, waitFor, within, configure } from '@testing-library/react';
import { MockedProvider, type MockedResponse } from '@apollo/client/testing/react';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '../../../components/Toast';
import POModule from '../index';
import { PURCHASE_ORDERS_PAGE, GET_PO_STATISTICS, GET_PURCHASE_ORDER } from '../../../graphql/po';
import { GET_PROJECTS, GET_GP_OUTBOX, GET_RELAY_STATUS } from '../../../graphql/shared';

// The register mounts five queries and a full MUI table; jsdom is slow enough at that to trip the
// 1s async-util default once vitest is running files in parallel.
vi.setConfig({ testTimeout: 30_000 });
configure({ asyncUtilTimeout: 15_000 });

// Neither dialog is under test here, and POGenerateDialog drags in @react-pdf/renderer at module
// level (PODetailModal imports it, and the register imports PODetailModal).
vi.mock('../POGenerateDialog', () => ({ default: () => null }));

// The register dialog stands in for itself so a test can fire the hand-off it makes when a PO has
// reached GP and GP's copy has been read back (#702).
const dialog = vi.hoisted(() => ({
  props: null as { onRegistered: (id: string) => void } | null,
}));
vi.mock('../GpPurchaseOrderDialog', () => ({
  default: (props: { onRegistered: (id: string) => void }) => {
    dialog.props = props;
    return null;
  },
}));

// The detail itself is not under test; what is, is that the page opens it, and for which PO.
vi.mock('../PODetailModal', () => ({
  default: ({ open, po }: { open: boolean; po: { id: string } }) =>
    open ? <div>PO detail for {po.id}</div> : null,
}));

// The table reads differently for the two kinds of caller - a UC Nexus Admin sees every company's
// POs at once, a scoped user only their own - so the identity is switchable per test.
const identity = vi.hoisted(() => ({ isNexusAdmin: true, company: null as string | null }));

vi.mock('../../../hooks/useIdentity', () => ({
  useIdentity: () => ({
    displayName: identity.isNexusAdmin ? 'Admin' : 'Bev Buyer',
    userId: identity.isNexusAdmin ? 'user_admin' : 'user_buyer',
    roles: identity.isNexusAdmin ? ['UC Nexus Admin'] : [],
    hasRole: (role: string) => identity.isNexusAdmin && role === 'UC Nexus Admin',
    isNexusAdmin: identity.isNexusAdmin,
    isTenantOwner: false,
    ownsTenant: identity.isNexusAdmin,
    isDbAdmin: false,
    gpBuyerId: null,
    company: identity.company,
    user: null,
  }),
}));

beforeEach(() => {
  identity.isNexusAdmin = true;
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
// The last three are the #701 cases: an order date GP filled in, the empty date GP writes when
// nobody dated the header, and a GP-raised PO with no vendor on it yet.
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
  row({
    id: 'po-dated',
    poNumber: 'PO-2002',
    status: 'GP_REGISTERED',
    origin: 'GP',
    company: 'UCSH',
    gpCompany: 'UCSH',
    orderedAt: '2026-01-05',
  }),
  row({
    id: 'po-no-gp-date',
    poNumber: 'PO-2003',
    status: 'GP_REGISTERED',
    origin: 'GP',
    company: 'UCSH',
    gpCompany: 'UCSH',
    orderedAt: '1900-01-01',
  }),
  row({
    id: 'po-no-gp-vendor',
    poNumber: 'PO-2004',
    status: 'GP_REGISTERED',
    origin: 'GP',
    company: 'UCSH',
    gpCompany: 'UCSH',
    vendorNameSnapshot: null,
  }),
  row({
    id: 'po-draft-no-vendor',
    requestNumber: 'PO-REQ-002',
    status: 'DRAFT',
    company: 'TUBC',
    gpCompany: null,
    vendorNameSnapshot: null,
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
    purchaseOrderMock(),
  ];
}

/** The full PO the detail read answers with - the same field set GET_PURCHASE_ORDER asks for. */
function purchaseOrderMock(): MockedResponse {
  return {
    request: { query: GET_PURCHASE_ORDER, variables: () => true },
    maxUsageCount: INFINITE,
    result: {
      data: {
        purchaseOrder: {
          __typename: 'PurchaseOrder',
          id: 'po-registered',
          poNumber: 'PO-2001',
          requestNumber: null,
          origin: 'NEXUS',
          gpSyncedAt: '2026-07-02T12:00:05Z',
          nexusRegistered: true,
          projectId: null,
          status: 'GP_REGISTERED',
          company: 'UCSH',
          gpCompany: 'UCSH',
          gpVendorId: 'V-ACE',
          vendorNameSnapshot: 'Ace Hardware Co',
          buyerId: 'JSMITH',
          vendorQuoteNumber: null,
          costCode: '310-000-3',
          shippingCost: 25,
          tariffAmount: null,
          notes: null,
          preferredDeliveryDate: null,
          expectedDeliveryDate: null,
          orderedAt: '2026-01-05',
          createdAt: '2026-07-01T12:00:00Z',
          updatedAt: '2026-07-02T12:00:05Z',
          documentData: null,
          lineItems: [],
          receiveRecords: [],
          documents: [],
        },
      },
    },
  };
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
  return cellOf(label, 1);
}

/** One cell of the row carrying `label`, by column index. The columns are Project, Company, PO
 *  number, Status, Vendor, Raised by, Created, Order Date, Items, and the chevron. */
async function cellOf(label: string, index: number) {
  const tr = (await screen.findByText(label)).closest('tr');
  return within(tr as HTMLElement).getAllByRole('cell')[index];
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
it('tells a UC Nexus Admin the table is every company at once', async () => {
  renderRegister();

  expect(await screen.findByText('All companies')).toBeInTheDocument();
});

// #682: the strip used to be one flat row, which said nothing about who decides a PO's status. The
// draft count sits in its own captioned box because Nexus owns it; the other five arrive from GP.
it('splits the status strip into a Nexus box and a GP box', async () => {
  renderRegister();

  expect(await screen.findByText('NEXUS')).toBeInTheDocument();
  const gpBox = screen.getByText('GP STATUSES').parentElement as HTMLElement;

  expect(screen.getByRole('button', { name: 'Filter by Nexus Draft' })).toBeInTheDocument();

  for (const label of [
    'Filter by GP-Registered',
    'Filter by Vendor Confirmed',
    'Filter by Partially Received',
    'Filter by Closed',
    'Filter by Cancelled',
  ]) {
    expect(within(gpBox).getByRole('button', { name: label })).toBeInTheDocument();
  }

  expect(within(gpBox).queryByRole('button', { name: 'Filter by Total' })).toBeNull();
  expect(within(gpBox).queryByRole('button', { name: 'Filter by Nexus Draft' })).toBeNull();
});

it('names the scoped user’s own GP company in the heading, and still gives them the column', async () => {
  identity.isNexusAdmin = false;
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


// --- #701: what the Order Date and Vendor cells say when GP has nothing in them -------------------

// The order date is GP's document date, a calendar date. It used to be read as a UTC instant, so
// every one of them printed a day early for a viewer behind UTC.
it('prints the calendar day GP holds as the order date', async () => {
  renderRegister();

  expect(await cellOf('PO-2002', 7)).toHaveTextContent(new Date(2026, 0, 5).toLocaleDateString());
});

// 1900-01-01 is what GP holds on a header nobody dated, and it is mirrored exactly as GP holds it.
it('says so in plain words where GP holds an empty document date', async () => {
  renderRegister();

  expect(await cellOf('PO-2003', 7)).toHaveTextContent('No date in GP');
});

it('says so in plain words where a PO from GP has no vendor on it yet', async () => {
  renderRegister();

  expect(await cellOf('PO-2004', 4)).toHaveTextContent('No vendor in GP');
});

// A Nexus draft has no vendor until it is registered into GP, which is not a gap worth naming.
it('leaves a Nexus draft with no vendor on the dash it has always printed', async () => {
  renderRegister();

  expect(await cellOf('PO-REQ-002', 4)).toHaveTextContent('-');
  expect(await cellOf('PO-REQ-002', 4)).not.toHaveTextContent('No vendor in GP');
});


// #702: registering used to drop the person back on the PO table in front of a row they then had to
// find. The register dialog now hands the PO over once GP's copy has been read back, and the page
// opens that PO.
it('opens the detail of a purchase order the register dialog has just finished', async () => {
  renderRegister();
  await screen.findByText('PO-2001');
  expect(screen.queryByText(/^PO detail for/)).toBeNull();

  act(() => dialog.props?.onRegistered('po-registered'));

  expect(await screen.findByText('PO detail for po-registered')).toBeInTheDocument();
});
